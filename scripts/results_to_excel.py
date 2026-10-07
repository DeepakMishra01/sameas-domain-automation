#!/usr/bin/env python
"""Turn a classify_relationships CSV into a formatted, colour-coded Excel file.

Usage:
  python scripts/results_to_excel.py RESULTS.csv OUTPUT.xlsx

Produces a "Results" sheet (frozen bold header, filters, colour by relationship
type, sorted SAME_AS -> PART_OF -> ACQUIRED -> REVIEW -> UNRELATED) and a
"Summary" sheet with the counts.
"""

from __future__ import annotations

import argparse
import collections
import csv

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

# Columns to show, in order (only those present in the CSV are used).
DISPLAY = [
    "domain1",
    "domain2",
    "feed_sector",
    "relationship_type",
    "relationship_subtype",
    "primary_domain",
    "secondary_domain",
    "parent_domain",
    "acquirer_domain",
    "acquired_domain",
    "direction",
    "confidence",
    "confidence_band",
    "reason_codes",
    "explanation",
    "decision_source",
    "qc_agree",
    "ai_confidence",
    "ai_evidence_quote",
    "ai_reasoning",
    "note",
]
ORDER = {"SAME_AS": 0, "PART_OF": 1, "ACQUIRED": 2, "REVIEW_REQUIRED": 3, "UNRELATED": 4}
COLORS = {
    "SAME_AS": "C6EFCE",
    "PART_OF": "FFEB9C",
    "ACQUIRED": "BDD7EE",
    "REVIEW_REQUIRED": "FCE4D6",
    "UNRELATED": "F2F2F2",
}
WIDTHS = {
    "domain1": 30,
    "domain2": 28,
    "feed_sector": 24,
    "relationship_type": 16,
    "relationship_subtype": 16,
    "primary_domain": 28,
    "secondary_domain": 28,
    "parent_domain": 22,
    "acquirer_domain": 20,
    "acquired_domain": 20,
    "direction": 13,
    "confidence": 11,
    "confidence_band": 14,
    "reason_codes": 24,
    "explanation": 60,
    "decision_source": 22,
    "qc_agree": 16,
    "ai_confidence": 12,
    "ai_evidence_quote": 45,
    "ai_reasoning": 55,
    "note": 24,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_csv")
    parser.add_argument("output_xlsx")
    parser.add_argument(
        "--no-sort",
        action="store_true",
        help="keep the input CSV row order (default: sort by relationship type)",
    )
    args = parser.parse_args()

    with open(args.results_csv, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("no rows in results CSV")

    cols = [c for c in DISPLAY if c in rows[0]]
    if not args.no_sort:
        rows.sort(
            key=lambda r: (ORDER.get(r.get("relationship_type", ""), 9), r.get("domain1", ""))
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append([c.replace("_", " ").title() for c in cols])
    for i in range(1, len(cols) + 1):
        cell = ws.cell(1, i)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
    type_col = cols.index("relationship_type") + 1 if "relationship_type" in cols else 0
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
        rtype = r.get("relationship_type", "")
        if type_col and rtype in COLORS:
            ws.cell(ws.max_row, type_col).fill = PatternFill("solid", fgColor=COLORS[rtype])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(c, 16)

    summary = wb.create_sheet("Summary")
    summary.append(["Relationship Type", "Count"])
    for cell in summary[1]:
        cell.font = Font(bold=True)
    counts = collections.Counter(r.get("relationship_type", "") or "BLANK" for r in rows)
    for key in ["SAME_AS", "PART_OF", "ACQUIRED", "REVIEW_REQUIRED", "UNRELATED", "BLANK"]:
        if counts.get(key):
            summary.append([key, counts[key]])
    summary.append(["TOTAL", len(rows)])
    summary.column_dimensions["A"].width = 20
    summary.column_dimensions["B"].width = 10

    wb.save(args.output_xlsx)
    print(f"Wrote {len(rows)} rows -> {args.output_xlsx}")


if __name__ == "__main__":
    main()
