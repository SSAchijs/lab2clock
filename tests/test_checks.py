from dataclasses import replace

import pytest

from lab2clock.checks import (
    Reading,
    duplicates,
    lymphocyte_consistency,
    missing,
    plausibility,
)
from lab2clock.clock_spec import BY_NAME, MARKERS
from lab2clock.conversions import convert
from lab2clock.synonyms import LYMPHOCYTE_COUNT
from lab2clock.values import parse_value


def reading(analyte, printed, unit):
    """A Reading as the pipeline builds it: parsed, then converted with its step."""
    parsed = parse_value(printed)
    return Reading(
        convert(analyte, parsed.value, unit),
        convert(analyte, 10.0**-parsed.decimals, unit),
    )


# Plausibility.


@pytest.mark.parametrize(
    ("analyte", "value"),
    [
        ("glucose", 5.5),
        ("c_reactive_protein", 0.2),
        ("white_blood_cell_count", 6.5),
        ("age", 120),
    ],
)
def test_typical_values_pass(analyte, value):
    assert plausibility(analyte, value) is None


@pytest.mark.parametrize(
    ("analyte", "value"),
    [
        ("glucose", 0.1),
        ("albumin", 0.5),
        ("lymphocyte_percent", 100),
        ("white_blood_cell_count", 1360),
    ],
)
def test_extreme_but_possible_values_warn_and_do_not_fail(analyte, value):
    assert plausibility(analyte, value).severity == "warning"


@pytest.mark.parametrize(
    ("analyte", "value"),
    [
        ("glucose", -1),
        ("glucose", 151),
        # Creatinine in umol/L multiplied by 88.4 a second time.
        ("creatinine", 7072),
        ("lymphocyte_percent", 101),
        ("mean_cell_volume", 9.0),
        # White cells in cells/uL left unconverted.
        ("white_blood_cell_count", 6500),
    ],
)
def test_impossible_values_fail(analyte, value):
    issue = plausibility(analyte, value)
    assert issue.check == "plausibility"
    assert issue.severity == "error"
    assert issue.analyte == analyte


@pytest.mark.parametrize(
    "analyte",
    ["glucose", "white_blood_cell_count", "albumin", "creatinine", "mean_cell_volume"],
)
def test_a_zero_no_living_person_has_fails(analyte):
    # A lab prints a detection limit, not 0; a urine test's "-" read as 0
    # must not reach the clock as a blood value.
    issue = plausibility(analyte, 0)
    assert (issue.check, issue.severity) == ("plausibility", "error")


@pytest.mark.parametrize("analyte", ["c_reactive_protein", "lymphocyte_percent"])
def test_a_zero_that_can_be_real_does_not_fail(analyte):
    issue = plausibility(analyte, 0)
    assert issue is None or issue.severity == "warning"


@pytest.mark.parametrize(
    ("analyte", "value"),
    [
        # A diabetic's glucose: real, so it warns and does not fail.
        ("glucose", 20.0),
        ("glucose", 3.0),
        # Glucose left in mg/dL: possible in mmol/L, but unusual.
        ("glucose", 95),
        ("c_reactive_protein", 8.0),
        ("mean_cell_volume", 35.4),
    ],
)
def test_unusual_values_warn(analyte, value):
    assert plausibility(analyte, value).severity == "warning"


def test_crp_left_in_mg_per_litre_usually_passes():
    # 2 mg/L read as 2 mg/dL: inside both tiers. Only the unit catches it.
    assert plausibility("c_reactive_protein", 2.0) is None


def test_error_tier_wins_over_warning_tier():
    assert plausibility("glucose", 200).severity == "error"


def test_warning_tier_limits_are_inclusive():
    low, high = BY_NAME["glucose"].warn
    assert plausibility("glucose", high) is None
    assert plausibility("glucose", low) is None


def test_no_warning_tier_skips_the_warning(monkeypatch):
    monkeypatch.setitem(BY_NAME, "glucose", replace(BY_NAME["glucose"], warn=None))
    assert plausibility("glucose", 30) is None


# Missing fields.


def test_nothing_missing():
    assert missing(MARKERS) == []


def test_missing_markers_fail():
    found = [marker for marker in MARKERS if marker != "c_reactive_protein"]
    [issue] = missing(found)
    assert issue.check == "missing"
    assert issue.severity == "error"
    assert issue.analyte == "c_reactive_protein"


def test_empty_report_misses_all_nine():
    assert [issue.analyte for issue in missing([])] == list(MARKERS)


def test_age_and_extra_analytes_are_not_required():
    # Age comes from elsewhere; the absolute count is only a derivation input.
    assert missing([*MARKERS, LYMPHOCYTE_COUNT]) == []


# Duplicates.


def test_single_readings_are_not_duplicates():
    assert duplicates({"glucose": [Reading(5.5, 0.1)], "albumin": []}) == []


def test_same_result_in_two_units_warns():
    # Glucose printed as 5.5 mmol/L and 99 mg/dL: 99 mg/dL is 5.495 mmol/L.
    readings = [reading("glucose", "5.5", "mmol/L"), reading("glucose", "99", "mg/dL")]
    [issue] = duplicates({"glucose": readings})
    assert issue.check == "duplicate"
    assert issue.severity == "warning"


def test_same_result_printed_twice_warns():
    [issue] = duplicates({"albumin": [Reading(42, 1), Reading(42, 1)]})
    assert issue.severity == "warning"


def test_current_and_previous_result_fail():
    # The previous-result column read as a second current result.
    readings = [
        reading("glucose", "5.5", "mmol/L"),
        reading("glucose", "6.1", "mmol/L"),
    ]
    [issue] = duplicates({"glucose": readings})
    assert issue.severity == "error"
    assert issue.analyte == "glucose"


def test_one_differing_reading_of_three_fails():
    readings = [Reading(42, 1), Reading(42, 1), Reading(38, 1)]
    [issue] = duplicates({"albumin": readings})
    assert issue.severity == "error"


# Lymphocyte cross-check.


@pytest.mark.parametrize(
    ("percent", "count", "white_cells"),
    [
        ("30.0", "2.10", "7.00"),
        # An analyzer rounds each value separately: 2.14 / 6.96 is 30.7%.
        ("30.7", "2.1", "7.0"),
        ("30.7", "2.14", "6.96"),
        # Few decimals at low counts leave a wide range: 0.45 / 3.05 to 0.55 / 2.95.
        ("17", "0.5", "3.0"),
    ],
)
def test_consistent_counts_pass(percent, count, white_cells):
    assert (
        lymphocyte_consistency(
            reading("lymphocyte_percent", percent, "%"),
            reading(LYMPHOCYTE_COUNT, count, "10^3/uL"),
            reading("white_blood_cell_count", white_cells, "10^3/uL"),
        )
        is None
    )


def test_counts_in_cells_per_microlitre_are_compared_in_one_unit():
    assert (
        lymphocyte_consistency(
            reading("lymphocyte_percent", "30.7", "%"),
            reading(LYMPHOCYTE_COUNT, "2140", "/uL"),
            reading("white_blood_cell_count", "6.96", "10^3/uL"),
        )
        is None
    )


@pytest.mark.parametrize(
    ("percent", "count", "white_cells"),
    [
        # 35.7 misread as 30.7: both plausible, only the counts disagree.
        ("30.7", "2.50", "7.00"),
        # Count misread: 1.2 for 2.1.
        ("30.0", "1.20", "7.00"),
        # White cells misread: 1.7 for 7.1.
        ("30.0", "2.10", "1.70"),
    ],
)
def test_misread_digit_fails(percent, count, white_cells):
    issue = lymphocyte_consistency(
        reading("lymphocyte_percent", percent, "%"),
        reading(LYMPHOCYTE_COUNT, count, "10^3/uL"),
        reading("white_blood_cell_count", white_cells, "10^3/uL"),
    )
    assert issue.check == "consistency"
    assert issue.severity == "error"
    assert issue.analyte == "lymphocyte_percent"


def test_rounding_boundary_is_consistent():
    # The highest the counts allow is 2.15 / 6.95 = 30.94%. 30.9 may be as
    # low as 30.85, so it passes; 31.0 is at least 30.95, so it fails.
    assert (
        lymphocyte_consistency(Reading(30.9, 0.1), Reading(2.1, 0.1), Reading(7.0, 0.1))
        is None
    )
    assert lymphocyte_consistency(
        Reading(31.0, 0.1), Reading(2.1, 0.1), Reading(7.0, 0.1)
    )


def test_zero_white_cells_is_left_to_plausibility():
    assert (
        lymphocyte_consistency(Reading(30, 0.1), Reading(2.1, 0.1), Reading(0, 0))
        is None
    )


@pytest.mark.parametrize("value", [0.001, 0.008, 0.04])
def test_a_urine_white_cell_count_per_microlitre_fails(value):
    # 1 to 40 cells/uL under the blood name 白细胞 converts to these.
    issue = plausibility("white_blood_cell_count", value)
    assert (issue.check, issue.severity) == ("plausibility", "error")
