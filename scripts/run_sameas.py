#!/usr/bin/env python
"""One command, whole Same As pipeline: crawl -> classify -> AI verify -> Excel.

Instead of running run_batch_fast.py, classify_relationships.py, ai_verify.py and
results_to_excel.py by hand, this runs all four steps in order for one input file.

Usage:
  python scripts/run_sameas.py INPUT.xlsx OUTPUT.xlsx [--limit N] [--workers W]
                               [--skip-crawl] [--qc-all] [--resume]

  --limit N      only the first N pairs
  --workers W    parallel workers for crawl and AI verify (default 6 crawl, 4 AI)
  --skip-crawl   reuse observations already in the database (no re-crawl)
  --qc-all       run the Serper web QC on every pair (DERE_SERP_ALL=1)
  --resume       reuse AI verdicts from a previous OUTPUT run (no --no-resume)

Intermediate CSVs are written next to OUTPUT (…_observe.csv, …_classify.csv,
…_ai.csv) so a run can be inspected or resumed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from domain_resolver.config.dotenv import load_env_file

HERE = Path(__file__).resolve().parent


def _run(step: str, args: list[str], env: dict[str, str]) -> None:
    print(f"\n{'=' * 70}\n>>> {step}\n{'=' * 70}", flush=True)
    start = time.time()
    result = subprocess.run([sys.executable, str(HERE / args[0]), *args[1:]], env=env)
    if result.returncode != 0:
        raise SystemExit(f"Step failed ({step}); stopping. Exit code {result.returncode}.")
    print(f"--- {step} done in {time.time() - start:.0f}s", flush=True)


def main() -> None:
    load_env_file()  # make DB URL, LLM provider/key, Serper key available to all steps
    parser = argparse.ArgumentParser(description="Run the whole Same As pipeline in one command.")
    parser.add_argument("input", help="input .xlsx (Company, Domain A, Domain B[, Sector])")
    parser.add_argument("output", help="output .xlsx (colour-coded results)")
    parser.add_argument("--limit", type=int, default=100000)
    parser.add_argument("--workers", type=int, default=0, help="override workers for both steps")
    parser.add_argument("--skip-crawl", action="store_true", help="reuse stored observations")
    parser.add_argument("--qc-all", action="store_true", help="Serper web QC on every pair")
    parser.add_argument("--resume", action="store_true", help="reuse prior AI verdicts")
    args = parser.parse_args()

    out = Path(args.output)
    stem = out.with_suffix("")
    observe_csv = f"{stem}_observe.csv"
    classify_csv = f"{stem}_classify.csv"
    ai_csv = f"{stem}_ai.csv"
    limit = str(args.limit)
    crawl_workers = str(args.workers or 25)
    ai_workers = str(args.workers or 4)

    env = dict(os.environ)
    if args.qc_all:
        env["DERE_SERP_ALL"] = "1"

    if not args.skip_crawl:
        _run(
            "Step 1/4  Crawl and read the domains",
            [
                "run_batch_fast.py",
                args.input,
                observe_csv,
                "--limit",
                limit,
                "--workers",
                crawl_workers,
            ],
            env,
        )
    else:
        print(">>> Skipping crawl (using observations already in the database).")

    _run(
        "Step 2/4  Classify (deterministic rules)",
        ["classify_relationships.py", args.input, classify_csv, "--limit", limit],
        env,
    )

    ai_args = ["ai_verify.py", classify_csv, ai_csv, "--workers", ai_workers]
    if not args.resume:
        ai_args.append("--no-resume")
    _run("Step 3/4  Verify the uncertain pairs (AI + Google)", ai_args, env)

    _run("Step 4/4  Build the Excel report", ["results_to_excel.py", ai_csv, args.output], env)

    print(f"\nAll done. Final report: {args.output}")


if __name__ == "__main__":
    main()
