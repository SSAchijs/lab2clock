import csv
import math
from pathlib import Path

import pytest

from bench.phenoage import INPUTS, phenoage

REFERENCE = Path(__file__).parent / "data" / "phenoage_reference.csv"


def load_reference():
    with REFERENCE.open() as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return [
            (
                row["sample"],
                {name: float(row[name]) for name in INPUTS},
                float(row["phenoage_pyaging"]),
            )
            for row in rows
        ]


REFERENCE_ROWS = load_reference()


def test_reference_has_all_example_rows():
    assert len(REFERENCE_ROWS) == 30


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [(inputs, expected) for _, inputs, expected in REFERENCE_ROWS],
    ids=[sample for sample, _, _ in REFERENCE_ROWS],
)
def test_matches_pyaging_within_a_tenth_of_a_year(inputs, expected):
    assert phenoage(**inputs) == pytest.approx(expected, abs=0.1)


def test_crp_left_in_mg_per_l_adds_about_2_4_years():
    _, inputs, _ = REFERENCE_ROWS[0]
    in_mg_per_l = {**inputs, "c_reactive_protein": inputs["c_reactive_protein"] * 10}

    shift = phenoage(**in_mg_per_l) - phenoage(**inputs)
    assert shift == pytest.approx(math.log(10) * 0.0954 / 0.090165)
    assert shift == pytest.approx(2.44, abs=0.01)


def test_non_positive_crp_is_rejected():
    _, inputs, _ = REFERENCE_ROWS[0]
    with pytest.raises(ValueError, match="CRP"):
        phenoage(**{**inputs, "c_reactive_protein": 0.0})
