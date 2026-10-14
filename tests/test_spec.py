import itertools
import json
from typing import get_args

import pandas as pd
import pytest
from pydantic import ValidationError

from bench.sample import OUT as PATIENTS
from bench.spec import (
    BASELINE,
    CBC,
    CHEMISTRY,
    MATRIX,
    PLANTED,
    PREVIOUS_DAYS,
    PREVIOUS_DRIFT,
    RENDER_SPEC,
    TRUTH,
    Conditions,
    Language,
    Layout,
    RenderSpec,
    Truth,
    UnitSystem,
    load_matrix,
    printed_value,
    render_spec,
    shifted,
    truth,
)
from lab2clock.assemble import assemble
from lab2clock.clock_spec import MARKERS
from lab2clock.conversions import convert
from lab2clock.synonyms import LYMPHOCYTE_COUNT, match
from lab2clock.units import normalise_unit

REPORTS = [f"R{i:02d}" for i in range(1, 26)]

# Chinese reports print SI units only.
ALL_CONDITIONS = [
    Conditions(layout=layout, language=language, unit_system=units)
    for layout, language, units in itertools.product(
        get_args(Layout), get_args(Language), get_args(UnitSystem)
    )
    if language == "en" or units == "si"
]


@pytest.fixture(scope="module")
def patients():
    return pd.read_csv(PATIENTS, index_col="report")


def load(model, folder, report):
    return model.model_validate_json((folder / f"{report}.json").read_text())


# The committed files.


def test_one_truth_and_one_render_spec_per_report():
    assert sorted(p.stem for p in TRUTH.glob("*.json")) == REPORTS
    assert sorted(p.stem for p in RENDER_SPEC.glob("*.json")) == REPORTS


@pytest.mark.parametrize("report", REPORTS)
def test_committed_files_pass_the_schema(report):
    assert load(Truth, TRUTH, report).report == report
    assert load(RenderSpec, RENDER_SPEC, report).report == report


@pytest.mark.parametrize("report", REPORTS)
def test_committed_files_match_a_fresh_build(patients, report):
    # Catches a hand edit, or a change to the builder without regenerating.
    patient = patients.loc[report]
    assert load(Truth, TRUTH, report) == truth(patient)
    conditions = load_matrix()[report]
    assert load(RenderSpec, RENDER_SPEC, report) == render_spec(patient, conditions)


@pytest.mark.parametrize("report", REPORTS)
def test_truth_holds_the_sampled_patient(patients, report):
    t = load(Truth, TRUTH, report)
    patient = patients.loc[report]
    assert (t.seqn, t.age, t.split) == (
        patient["SEQN"],
        patient["age"],
        patient["split"],
    )
    assert t.values == {m: patient[m] for m in MARKERS}


# Round trip: what a perfect reader returns comes back to the truth.


def assert_round_trip(spec: RenderSpec, t: Truth):
    """Every marker comes back to the truth, bar those the conditions break.

    A planted slip and a missing marker must each raise an error on their
    marker. A planted white-cell count also breaks the lymphocyte cross-check,
    which cannot tell which of the two is wrong.
    """
    out = assemble(spec.stage1(), age=t.age)
    planted = {row.analyte for row in spec.rows if row.planted}
    expected = planted | {spec.conditions.missing} - {None}
    allowed = set(expected)
    if "white_blood_cell_count" in planted:
        allowed.add("lymphocyte_percent")
    errored = {i["analyte"] for i in out["issues"] if i["severity"] == "error"}
    assert expected <= errored <= allowed, out["issues"]
    assert out["ok"] == (not expected)
    assert set(out["missing"]) == errored
    # Exactly the distractors stay unmapped.
    distractors = [row.name for row in spec.rows if row.analyte is None]
    assert [item["name"] for item in out["unmapped"]] == distractors
    for row in spec.rows:
        assert match(row.name, row.unit) == row.analyte
        if row.analyte not in MARKERS or row.analyte in errored:
            continue
        # Rounding to the printed decimals moves a value by at most half a step.
        step = convert(row.analyte, 10.0**-row.decimals, normalise_unit(row.unit))
        got = out["inputs"][row.analyte]["value"]
        assert got == pytest.approx(t.values[row.analyte], abs=step / 2 + 1e-9)


@pytest.mark.parametrize("report", REPORTS)
def test_committed_specs_read_back_to_the_truth(report):
    assert_round_trip(load(RenderSpec, RENDER_SPEC, report), load(Truth, TRUTH, report))


@pytest.mark.parametrize(
    "conditions",
    ALL_CONDITIONS,
    ids=lambda c: f"{c.layout}-{c.language}-{c.unit_system}",
)
def test_every_condition_reads_back_to_the_truth(patients, conditions):
    for _, patient in patients.iterrows():
        assert_round_trip(render_spec(patient, conditions), truth(patient))


def test_multi_page_puts_chemistry_on_page_two(patients):
    conditions = BASELINE.model_copy(update={"layout": "multi_page"})
    spec = render_spec(patients.iloc[0], conditions)
    pages = {row.analyte: row.page for row in spec.rows}
    assert pages["white_blood_cell_count"] == 1
    assert pages["creatinine"] == 2


def test_mixed_units_mix(patients):
    conditions = BASELINE.model_copy(update={"unit_system": "mixed"})
    units = {
        row.analyte: row.unit for row in render_spec(patients.iloc[0], conditions).rows
    }
    assert units["albumin"] == "g/L"
    assert units["glucose"] == "mg/dL"


# Printed values.


@pytest.mark.parametrize(
    ("marker", "value", "unit", "decimals", "expected"),
    [
        # Half up, as labs round, not half to even: 2.25 mg/L is 2.3.
        ("c_reactive_protein", 0.225, "mg/L", 1, "2.3"),
        # Float noise: 0.2259999999999999 mg/dL is 2.26 mg/L.
        ("c_reactive_protein", 0.2259999999999999, "mg/L", 1, "2.3"),
        ("c_reactive_protein", 0.04, "mg/dL", 2, "0.04"),
        ("albumin", 37.0, "g/L", 0, "37"),
        ("albumin", 37.0, "g/dL", 1, "3.7"),
        ("creatinine", 88.40, "µmol/L", 0, "88"),
        ("creatinine", 88.40, "mg/dL", 2, "1.00"),
        ("glucose", 5.55, "mg/dL", 0, "100"),
        ("white_blood_cell_count", 6.5, "x10^3/uL", 1, "6.5"),
    ],
)
def test_printed_value(marker, value, unit, decimals, expected):
    assert printed_value(marker, value, unit, decimals) == expected


def test_a_value_that_rounds_to_zero_fails():
    with pytest.raises(ValueError, match="rounds to 0"):
        printed_value("c_reactive_protein", 0.001, "mg/dL", 2)


# The schema.


def test_truth_needs_all_nine_markers():
    t = json.loads((TRUTH / "R01.json").read_text())
    del t["values"]["glucose"]
    with pytest.raises(ValidationError):
        Truth.model_validate(t)


def test_render_spec_refuses_unknown_keys():
    spec = json.loads((RENDER_SPEC / "R01.json").read_text())
    spec["rows"][0]["colour"] = "red"
    with pytest.raises(ValidationError):
        RenderSpec.model_validate(spec)


def test_stage1_view_drops_what_the_reader_cannot_see():
    spec = load(RenderSpec, RENDER_SPEC, "R01")
    item = spec.stage1().items[0].model_dump()
    assert set(item) == {"name", "value", "unit", "page"}


# Extra rows.


def test_us_report_calls_urea_bun(patients):
    conditions = BASELINE.model_copy(update={"unit_system": "us"})
    rows = {row.name: row for row in render_spec(patients.iloc[0], conditions).rows}
    assert rows["BUN"].unit == "mg/dL"
    assert "Urea" not in rows


def test_every_report_prints_the_same_extras(patients):
    for _, patient in patients.iterrows():
        rows = render_spec(patient, BASELINE).rows
        assert len(rows) == len(CBC) + len(CHEMISTRY)


def test_absolute_lymphocytes_feed_the_cross_check(patients):
    rows = render_spec(patients.iloc[0], BASELINE).rows
    assert [r.analyte for r in rows].count(LYMPHOCYTE_COUNT) == 1


# The variation matrix.


@pytest.fixture(scope="module")
def matrix():
    return pd.read_csv(MATRIX, index_col="report", keep_default_na=False)


def test_matrix_lists_every_report_with_its_split(matrix, patients):
    assert list(matrix.index) == REPORTS
    assert list(matrix["split"]) == list(patients["split"])


def test_every_matrix_row_is_valid_conditions():
    assert len(load_matrix()) == len(REPORTS)


def counts(rows, column):
    return rows[column].value_counts().to_dict()


def test_test_set_spreads_each_condition_at_least_three_times(matrix):
    test = matrix[matrix["split"] == "test"]
    assert counts(test, "unit_system") == {"us": 7, "si": 7, "mixed": 6}
    assert counts(test, "layout") == {"table": 7, "two_column": 7, "multi_page": 6}
    assert counts(test, "language")["zh"] == 3
    assert counts(test, "photo")["yes"] == 5
    assert counts(test, "previous")["yes"] == 4
    assert (test["missing"] != "").sum() == 3
    assert (test["planted"] != "").sum() == 3
    # One of each planted kind, and three different missing markers.
    assert set(test["planted"]) - {""} == set(PLANTED)
    assert (test["missing"] != "").sum() == len(set(test["missing"]) - {""})


def test_dev_set_has_one_of_each_condition(matrix):
    dev = matrix[matrix["split"] == "dev"]
    assert set(dev["unit_system"]) == set(get_args(UnitSystem))
    assert set(dev["layout"]) == set(get_args(Layout))
    for column in ("photo", "previous", "missing", "planted"):
        assert (dev[column] != "").sum() == 1, column
    assert (dev["language"] == "zh").sum() == 1


def test_conditions_spare_the_values_a_patient_was_drawn_for(matrix, patients):
    forced = {"high_crp": "c_reactive_protein", "high_glucose": "glucose"}
    for report, row in matrix.iterrows():
        marker = forced.get(patients.loc[report, "reason"])
        if marker is None:
            continue
        planted = PLANTED[row["planted"]][0] if row["planted"] else None
        assert marker not in {row["missing"], planted}, report


@pytest.mark.parametrize("report", REPORTS)
def test_committed_conditions_are_printed(report):
    spec = load(RenderSpec, RENDER_SPEC, report)
    c = spec.conditions
    analytes = [row.analyte for row in spec.rows]
    assert (spec.degradation is not None) == c.photo
    assert (spec.previous_collected is not None) == c.previous
    assert all((row.previous is not None) == c.previous for row in spec.rows)
    if c.missing:
        assert c.missing not in analytes
    planted = [row for row in spec.rows if row.planted]
    assert [row.planted for row in planted] == ([c.planted] if c.planted else [])
    if c.previous:
        days = (spec.identity.collected - spec.previous_collected).days
        assert PREVIOUS_DAYS[0] <= days <= PREVIOUS_DAYS[1]


@pytest.mark.parametrize("report", REPORTS)
def test_previous_results_stay_near_the_current_ones(report):
    spec = load(RenderSpec, RENDER_SPEC, report)
    for row in spec.rows:
        if row.previous is None or row.planted:
            continue
        current, previous = float(row.value), float(row.previous)
        # Within the drift, plus a printed step either side for rounding.
        step = 10.0**-row.decimals
        assert abs(previous - current) <= PREVIOUS_DRIFT * current + 2 * step


@pytest.mark.parametrize(
    ("printed", "power", "expected"),
    [
        ("89.3", -1, ("8.93", 2)),
        ("30.7", 1, ("307", 0)),
        ("9.8", 3, ("9800", 0)),
        ("10.0", 3, ("10000", 0)),
    ],
)
def test_a_slip_moves_the_decimal_point_and_keeps_the_digits(printed, power, expected):
    assert shifted(printed, power) == expected


@pytest.mark.parametrize(
    "fields",
    [
        {"language": "zh", "unit_system": "us"},
        {"layout": "two_column", "previous": True},
        {"missing": "hemoglobin"},
        {"missing": "mean_cell_volume", "planted": "mcv_decimal"},
    ],
)
def test_incoherent_conditions_are_refused(fields):
    with pytest.raises(ValidationError):
        Conditions(**{**BASELINE.model_dump(), **fields})
