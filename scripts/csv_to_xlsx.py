#!/usr/bin/env python
"""Turn a results CSV into a clean, readable Excel file.

Adds a bold frozen header, an auto-filter, and sensible column widths so the
output opens as a tidy table. Usage:
  python scripts/csv_to_xlsx.py INPUT.csv OUTPUT.xlsx
"""

from __future__ import annotations

import argparse
import csv

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()

    with open(args.input, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        print("empty input")
        return

    # Sort data rows by Company ID (numeric when possible) so the output is
    # ordered, not in the order the parallel run happened to finish.
    header, data = rows[0], rows[1:]

    def _key(row: list[str]) -> tuple[int, float | str]:
        value = row[0] if row else ""
        try:
            return (0, float(value))
        except ValueError:
            return (1, value)

    data.sort(key=_key)
    rows = [header, *data]

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Results"

    header_fill = PatternFill("solid", fgColor="1F5C99")
    header_font = Font(bold=True, color="FFFFFF")
    for row in rows:
        sheet.append(row)

    for col, _ in enumerate(rows[0], start=1):
        cell = sheet.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")

    # Auto-size columns (capped) based on the longest value in each.
    widths = [len(str(v)) for v in rows[0]]
    for row in rows[1:]:
        for i, value in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(value)))
    for i, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(rows[0]))}{len(rows)}"
    workbook.save(args.output)
    print(f"Wrote {len(rows) - 1} data rows to {args.output}")


if __name__ == "__main__":
    main()
