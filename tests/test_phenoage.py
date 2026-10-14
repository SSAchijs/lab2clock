import csv
import math
from pathlib import Path

import pytest

from lab2clock.clock_spec import FIELD_NAMES
from lab2clock.phenoage import phenoage

REFERENCE = Path(__file__).parent / "data" / "phenoage_reference.csv"


def load_reference():
    with REFERENCE.open() as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return [
            (
                row["sample"],
                {name: float(row[name]) for name in FIELD_NAMES},
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


@pytest.mark.parametrize("crp", [0.0, 0.001])
def test_crp_below_the_floor_counts_as_the_floor(crp):
    # As pyaging floors it at 0.01 mg/dL before the log.
    _, inputs, _ = REFERENCE_ROWS[0]
    floored = phenoage(**{**inputs, "c_reactive_protein": 0.01})
    assert phenoage(**{**inputs, "c_reactive_protein": crp}) == floored
