import pytest

from bench import oracle
from bench.score import (
    TOLERANCE,
    expected_input,
    same_input,
    same_unit,
    same_value,
)
from bench.spec import RENDER_SPEC, TRUTH, RenderSpec, Truth
from lab2clock.assemble import assemble
from lab2clock.clock_spec import MARKERS

REPORTS = [f"R{i:02d}" for i in range(1, 26)]


def load(model, folder, report):
    return model.model_validate_json((folder / f"{report}.json").read_text())


# Stage 1: the same transcription, up to typography.


@pytest.mark.parametrize(
    "got, printed",
    [
        ("5.6", "5.6"),
        (" 5.6 ", "5.6"),
        ("5,6", "5.6"),
        ("<0,5", "<0.5"),
        ("1,2345", "1.2345"),
        ("146 H", "146"),
        ("146H", "146"),
        ("146 H", "146 H"),
        ("1.2 (H)", "1.2"),
        ("3.1 L", "3.1"),
        ("12.0↑", "12.0"),
        ("１４６", "146"),
        ("−1.5", "-1.5"),
    ],
)
def test_values_that_differ_only_in_typography_are_the_same(got, printed):
    assert same_value(got, printed)


@pytest.mark.parametrize(
    "got, printed",
    [
        ("56", "5.6"),
        # The printed decimals are part of the reading.
        ("5.60", "5.6"),
        ("146", "147"),
        # A comma before three digits may separate thousands.
        ("5,500", "5.500"),
        ("<0.5", "0.5"),
        ("8.93", "89.3"),
        ("9800", "9.8"),
    ],
)
def test_values_that_read_differently_are_not_the_same(got, printed):
    assert not same_value(got, printed)


@pytest.mark.parametrize(
    "got, printed",
    [
        ("μmol/L", "µmol/L"),
        ("umol/L", "µmol/L"),
        ("10⁹/L", "10^9/L"),
        ("×10^3/uL", "x10^3/uL"),
        ("x10³/µL", "x10^3/uL"),
        ("mg/dl", "mg/dL"),
        ("mmol / L", "mmol/L"),
        ("ｍｇ/Ｌ", "mg/L"),
        (None, None),
        ("", None),
    ],
)
def test_units_that_differ_only_in_typography_are_the_same(got, printed):
    assert same_unit(got, printed)


@pytest.mark.parametrize(
    "got, printed",
    [
        # The same magnitude, renamed: the core reads both alike, but it is
        # not what was printed.
        ("K/uL", "10^9/L"),
        ("U/L", "IU/L"),
        ("10^9/L", "x10^9/L"),
        ("mg/L", "mg/dL"),
        ("109/L", "10^9/L"),
        (None, "%"),
        ("%", None),
    ],
)
def test_units_that_read_differently_are_not_the_same(got, printed):
    assert not same_unit(got, printed)


# End to end: the printed value in the clock's unit, within 0.5%.


@pytest.mark.parametrize(
    "marker, printed, unit, expected",
    [
        ("glucose", "100", "mg/dL", 5.55),
        ("creatinine", "1.00", "mg/dL", 88.4),
        ("albumin", "4.2", "g/dL", 42.0),
        ("c_reactive_protein", "2.4", "mg/L", 0.24),
        ("c_reactive_protein", "0.24", "mg/dL", 0.24),
        ("creatinine", "68", "µmol/L", 68.0),
        ("white_blood_cell_count", "6.0", "10^9/L", 6.0),
        ("alkaline_phosphatase", "74", "IU/L", 74.0),
    ],
)
def test_expected_input(marker, printed, unit, expected):
    assert expected_input(marker, printed, unit) == pytest.approx(expected, rel=1e-3)


def test_the_tolerance_admits_noise_and_refuses_a_slip():
    assert same_input(5.55 * (1 + TOLERANCE * 0.99), 5.55)
    assert same_input(5.55 * (1 - TOLERANCE * 0.99), 5.55)
    assert not same_input(5.55 * (1 + TOLERANCE * 1.2), 5.55)
    assert not same_input(0.24 * 10, 0.24)


# The oracle meets both rules.


@pytest.mark.parametrize("report", REPORTS)
def test_the_oracle_reads_every_marker_correctly(report):
    spec = load(RenderSpec, RENDER_SPEC, report)
    t = load(Truth, TRUTH, report)
    response = oracle.extract(spec)
    out = assemble(response, age=t.age)
    # A planted value is withheld, and a planted white-cell count takes the
    # lymphocyte percent with it, since the cross-check cannot tell which of
    # the two is wrong.
    withheld = {row.analyte for row in spec.rows if row.planted}
    if "white_blood_cell_count" in withheld:
        withheld.add("lymphocyte_percent")
    for row, item in zip(spec.rows, response.items, strict=True):
        if row.analyte not in MARKERS:
            continue
        assert same_value(item.value, row.value)
        assert same_unit(item.unit, row.unit)
        if row.analyte in withheld:
            assert row.analyte not in out["inputs"]
            continue
        got = out["inputs"][row.analyte]["value"]
        assert same_input(got, expected_input(row.analyte, row.value, row.unit))
