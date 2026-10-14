import csv
from pathlib import Path

import pytest

from lab2clock.clock_spec import BY_NAME, FIELD_NAMES, FIELDS, MARKERS

REFERENCE = Path(__file__).parent / "data" / "phenoage_reference.csv"


def test_field_names_are_unique():
    assert len(set(FIELD_NAMES)) == len(FIELD_NAMES) == 10


def test_field_names_match_pyaging_columns_in_order():
    with REFERENCE.open() as f:
        header = next(csv.reader(line for line in f if not line.startswith("#")))
    assert tuple(header[1:-1]) == FIELD_NAMES


def test_nine_markers_exclude_age():
    assert len(MARKERS) == 9
    assert "age" not in MARKERS


def test_units_that_are_easy_to_get_wrong():
    assert BY_NAME["c_reactive_protein"].unit == "mg/dL"
    assert BY_NAME["white_blood_cell_count"].unit == "10^3/uL"
    assert BY_NAME["creatinine"].unit == "umol/L"


def test_only_crp_is_transformed_by_the_clock():
    transformed = [field.name for field in FIELDS if field.transform]
    assert transformed == ["c_reactive_protein"]


def test_units_are_ascii():
    for field in FIELDS:
        assert field.unit.isascii(), field.name


@pytest.mark.parametrize("name", MARKERS)
def test_every_marker_has_both_tiers(name):
    assert BY_NAME[name].error is not None
    assert BY_NAME[name].warn is not None


@pytest.mark.parametrize("field", FIELDS, ids=FIELD_NAMES)
def test_limits_are_ordered_and_warn_sits_inside_error(field):
    for limits in (field.warn, field.error):
        if limits is not None:
            low, high = limits
            assert low < high
    if field.warn is not None and field.error is not None:
        assert field.error[0] <= field.warn[0]
        assert field.warn[1] <= field.error[1]


@pytest.mark.parametrize(
    ("name", "slip"),
    [
        # 90 umol/L converted again as if it were mg/dL.
        ("creatinine", 90 * 88.42),
        # White cells printed per uL (6500) instead of per 10^3 uL (6.5).
        ("white_blood_cell_count", 6500),
        # A lymphocyte share above the whole.
        ("lymphocyte_percent", 150),
        ("glucose", -1),
    ],
)
def test_error_tier_rejects_impossible_values(name, slip):
    low, high = BY_NAME[name].error
    assert not low <= slip <= high
