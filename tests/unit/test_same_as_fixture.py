import csv
from pathlib import Path

from domain_resolver.normalization import normalize_domain

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "same_as_examples.csv"


def test_same_as_fixture_contains_exactly_the_gold_labels() -> None:
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as fixture_file:
        rows = list(csv.DictReader(fixture_file))

    assert len(rows) == 14
    assert {row["label_source"] for row in rows} == {"CPT_GOLD"}
    assert all(normalize_domain(row["secondary_domain"]) == row["secondary_domain"] for row in rows)
    assert all(normalize_domain(row["primary_domain"]) == row["primary_domain"] for row in rows)
    assert all(row["secondary_domain"] != row["primary_domain"] for row in rows)
