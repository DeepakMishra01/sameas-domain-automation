"""Unit tests for header-based input column resolution."""

from domain_resolver.dataset_columns import resolve_columns


def test_classic_layout_without_sector() -> None:
    col = resolve_columns(("Company ID", "Domain 1", "Domain 2"))
    assert col == {"company": 0, "domain1": 1, "domain2": 2}


def test_layout_with_sector_column_shifts_domain2() -> None:
    col = resolve_columns(("Company ID", "Domain 1", "Feed Sector(Domain 1)", "Domain 2"))
    assert col["domain1"] == 1
    assert col["sector"] == 2
    assert col["domain2"] == 3


def test_domain_a_b_aliases() -> None:
    col = resolve_columns(("Company ID ", "Domain A", "Domain B"))
    assert col["domain1"] == 1
    assert col["domain2"] == 2


def test_missing_header_falls_back_to_classic_positions() -> None:
    col = resolve_columns(("", "", ""))
    assert col == {"company": 0, "domain1": 1, "domain2": 2}


def test_sector_detected_anywhere() -> None:
    col = resolve_columns(("Domain 1", "Domain 2", "Sector"))
    assert col["sector"] == 2
    assert col["domain1"] == 0
    assert col["domain2"] == 1
