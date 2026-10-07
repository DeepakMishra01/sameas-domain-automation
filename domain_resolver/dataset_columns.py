"""Locate input columns by header name, so column ORDER doesn't matter.

Input spreadsheets vary: some are ``Company ID | Domain 1 | Domain 2``; newer ones
insert a sector column: ``Company ID | Domain 1 | Feed Sector(Domain 1) | Domain 2``.
Reading by fixed index breaks when a column is inserted, so we resolve indices from
the header row by name and fall back to the classic positions if a header is absent.

Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence


def resolve_columns(header: Sequence[object]) -> dict[str, int]:
    """Return column indices for company / domain1 / domain2 / sector from a header.

    Matches on header text (case-insensitive), e.g. "Domain 1"/"Domain A",
    "Domain 2"/"Domain B", "Feed Sector(Domain 1)"/"sector", "Company ID". Missing
    keys fall back to the classic layout (company=0, domain1=1, domain2=2, or 3 when
    a sector column is present). ``sector`` is omitted when no sector header exists.
    """
    idx: dict[str, int] = {}
    for i, cell in enumerate(header):
        if cell is None:
            continue
        text = str(cell).strip().lower()
        if not text:
            continue
        if "sector" in text:
            idx.setdefault("sector", i)
        elif "domain 2" in text or "domain b" in text or text in {"domain2", "domainb"}:
            idx.setdefault("domain2", i)
        elif "domain 1" in text or "domain a" in text or text in {"domain1", "domaina"}:
            idx.setdefault("domain1", i)
        elif "company" in text:
            idx.setdefault("company", i)

    idx.setdefault("company", 0)
    idx.setdefault("domain1", 1)
    idx.setdefault("domain2", 3 if "sector" in idx else 2)
    return idx
