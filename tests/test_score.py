import pytest

import lab2clock.assemble as assemble_module
from bench import oracle
from bench.score import (
    TOLERANCE,
    Outcome,
    Rate,
    expected_input,
    metrics,
    same_input,
    same_unit,
    same_value,
    score_report,
    wilson,
    withheld,
)
from bench.spec import RENDER_SPEC, TRUTH, RenderSpec, Truth
from lab2clock.checks import Issue
from lab2clock.stage1 import RawReport
from lab2clock.units import UnitError

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


# Attribution: every error lands on the stage that made it.


def response(report):
    return oracle.extract(load(RenderSpec, RENDER_SPEC, report))


def outcomes(report, items=None):
    spec = load(RenderSpec, RENDER_SPEC, report)
    r = RawReport(items=items) if items is not None else oracle.extract(spec)
    return {o.marker: o for o in score_report(spec, r, load(Truth, TRUTH, report).age)}


def edit(report, name, /, **changes):
    """The oracle's response with the item called `name` changed."""
    items = response(report).items
    i = next(i for i, item in enumerate(items) if item.name == name)
    items[i] = items[i].model_copy(update=changes)
    return items


def only_error(result):
    """The one marker that is not fully correct, with its error."""
    wrong = [(m, o) for m, o in result.items() if o.error or not o.correct]
    assert len(wrong) == 1, wrong
    return wrong[0]


@pytest.mark.parametrize("report", REPORTS)
def test_the_oracle_scores_every_marker_correct(report):
    for o in outcomes(report).values():
        assert o.correct and o.error is None, o


def test_withheld_markers_follow_the_conditions():
    spec = {r: load(RenderSpec, RENDER_SPEC, r) for r in ("R10", "R11", "R20")}
    assert withheld(spec["R10"]) == {"mean_cell_volume"}
    assert withheld(spec["R11"]) == {"albumin"}
    assert withheld(spec["R20"]) == {"white_blood_cell_count", "lymphocyte_percent"}
    assert all(o.expected is None and o.correct for o in [outcomes("R11")["albumin"]])


def test_a_misread_value():
    marker, o = only_error(outcomes("R15", edit("R15", "MCV", value="83.9")))
    assert (marker, o.error, o.correct) == ("mean_cell_volume", "value", False)


def test_a_misread_unit():
    marker, o = only_error(outcomes("R07", edit("R07", "超敏C反应蛋白", unit="mg/dL")))
    assert (marker, o.error, o.correct) == ("c_reactive_protein", "unit", False)


def test_a_renamed_unit_is_a_stage1_error_that_leaves_the_input_right():
    marker, o = only_error(outcomes("R07", edit("R07", "白细胞计数", unit="K/uL")))
    assert (marker, o.error, o.correct) == ("white_blood_cell_count", "unit", True)


def test_an_omitted_row():
    items = [item for item in response("R15").items if item.name != "Albumin"]
    marker, o = only_error(outcomes("R15", items))
    assert (marker, o.error, o.got) == ("albumin", "omitted", None)


def test_a_misread_name_that_maps_to_nothing():
    marker, o = only_error(outcomes("R15", edit("R15", "Glucose", name="Glucoes")))
    assert (marker, o.error, o.correct) == ("glucose", "mapping", False)


def test_a_distractor_mapped_to_a_marker():
    items = edit("R15", "Total Protein", name="Albumin")
    marker, o = only_error(outcomes("R15", items))
    assert (marker, o.error, o.correct) == ("albumin", "mapping", False)


def test_a_distractor_mapped_to_a_missing_marker():
    items = edit("R11", "Total Protein", name="Albumin")
    marker, o = only_error(outcomes("R11", items))
    assert (marker, o.error, o.correct) == ("albumin", "mapping", False)


def test_a_wrong_conversion(monkeypatch):
    real = assemble_module.convert

    def tenfold_glucose(analyte, value, unit):
        return real(analyte, value, unit) * (10 if analyte == "glucose" else 1)

    monkeypatch.setattr(assemble_module, "convert", tenfold_glucose)
    marker, o = only_error(outcomes("R15"))
    assert (marker, o.error, o.correct) == ("glucose", "conversion", False)


def test_a_unit_the_core_fails_to_read(monkeypatch):
    real = assemble_module.normalise_unit

    def no_mg_per_dl(unit):
        if unit == "mg/dL":
            raise UnitError(unit)
        return real(unit)

    monkeypatch.setattr(assemble_module, "normalise_unit", no_mg_per_dl)
    result = outcomes("R15")
    wrong = {m: o.error for m, o in result.items() if not o.correct}
    assert wrong == dict.fromkeys(
        ["creatinine", "glucose", "c_reactive_protein"], "conversion"
    )


def test_a_false_flag(monkeypatch):
    def albumin_implausible(analyte, value):
        if analyte == "albumin":
            return Issue("plausibility", "error", analyte, "injected")
        return None

    monkeypatch.setattr(assemble_module, "plausibility", albumin_implausible)
    marker, o = only_error(outcomes("R15"))
    assert (marker, o.error, o.got) == ("albumin", "flag", None)


def test_a_missed_flag(monkeypatch):
    monkeypatch.setattr(assemble_module, "plausibility", lambda analyte, value: None)
    marker, o = only_error(outcomes("R10"))
    assert (marker, o.error, o.correct) == ("mean_cell_volume", "flag", False)
    assert o.expected is None and o.got is not None


def test_a_misread_count_is_blamed_for_the_percent_it_withholds():
    spec = load(RenderSpec, RENDER_SPEC, "R07")
    count = next(row for row in spec.rows if row.analyte == "lymphocyte_count")
    marker, o = only_error(outcomes("R07", edit("R07", count.name, value="4.1")))
    assert count.value != "4.1"
    assert (marker, o.error, o.got) == ("lymphocyte_percent", "value", None)


def test_a_planted_slip_corrected_by_the_reader_is_a_misread():
    marker, o = only_error(outcomes("R10", edit("R10", "MCV", value="90.1")))
    assert (marker, o.error, o.correct) == ("mean_cell_volume", "value", False)


# Metrics.


@pytest.mark.parametrize(
    "k, n, low, high",
    [
        # At 100%, the lower bound is n / (n + z^2), and the upper is 100%.
        (20, 20, 20 / (20 + 1.959964**2), 1.0),
        (0, 10, 0.0, 1.959964**2 / (10 + 1.959964**2)),
        (5, 10, 0.2366, 0.7634),
        (171, 180, 0.9078, 0.9734),
    ],
)
def test_wilson_interval(k, n, low, high):
    assert wilson(k, n) == pytest.approx((low, high), abs=1e-4)


def test_wilson_stays_inside_zero_to_one_where_the_normal_interval_does_not():
    # The normal approximation at 19 of 20 runs past 100%.
    p, n = 19 / 20, 20
    assert p + 1.96 * (p * (1 - p) / n) ** 0.5 > 1
    low, high = wilson(19, 20)
    assert 0 < low < high < 1


def test_a_rate_of_nothing_has_no_value():
    assert Rate(0, 0).value is None and Rate(0, 0).interval is None


def all_outcomes():
    return [o for report in REPORTS for o in outcomes(report).values()]


def test_the_oracle_scores_100_percent_on_every_metric():
    result = metrics(all_outcomes())
    for name, rate in result.items():
        assert rate.k == rate.n > 0, name
    assert result["value_accuracy"].n == 25 * 9
    assert result["report_accuracy"].n == 25
    # 4 missing markers print no row.
    assert result["stage1_accuracy"].n == 25 * 9 - 4
    # mcv in R03 and R10, lymphocyte percent in R09, and in R20 the white-cell
    # count with the percent it knocks out.
    assert result["flag_recall"].n == 5


def outcome(report, marker="albumin", **fields):
    defaults = dict(printed=True, expected=40.0, got=40.0, correct=True, error=None)
    return Outcome(report, marker, **{**defaults, **fields})


def test_one_wrong_marker_fails_its_whole_report():
    result = metrics(
        [
            outcome("R01"),
            outcome("R01", "glucose", got=50.0, correct=False, error="conversion"),
            outcome("R02"),
            outcome("R02", "glucose"),
        ]
    )
    assert (result["value_accuracy"].k, result["value_accuracy"].n) == (3, 4)
    assert (result["report_accuracy"].k, result["report_accuracy"].n) == (1, 2)


def test_a_wrong_input_with_a_correct_transcription_counts_only_end_to_end():
    result = metrics([outcome("R01", got=4.0, correct=False, error="conversion")])
    assert result["stage1_accuracy"].k == 1
    assert result["value_accuracy"].k == 0


def test_a_renamed_unit_counts_only_at_stage_1():
    result = metrics([outcome("R01", error="unit")])
    assert result["stage1_accuracy"].k == 0
    assert result["value_accuracy"].k == 1


def test_flags_count_false_alarms_and_misses():
    result = metrics(
        [
            # Caught.
            outcome("R01", "mean_cell_volume", expected=None, got=None),
            # Missed: a planted slip delivered.
            outcome("R01", expected=None, got=0.4, correct=False, error="flag"),
            # False alarm: a correct value withheld.
            outcome("R01", "glucose", got=None, correct=False, error="flag"),
            # A missing marker is neither.
            outcome("R01", "creatinine", printed=False, expected=None, got=None),
        ]
    )
    assert (result["flag_precision"].k, result["flag_precision"].n) == (1, 2)
    assert (result["flag_recall"].k, result["flag_recall"].n) == (1, 2)
