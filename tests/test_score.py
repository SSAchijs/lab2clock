import pytest

import lab2clock.assemble as assemble_module
from bench import medrepbench, oracle, prompts, responses
from bench.prompts import Prompt
from bench.responses import Failure, Response
from bench.score import (
    COLUMNS,
    RESULTS,
    SUMMARY,
    TOLERANCE,
    Labelled,
    Outcome,
    Rate,
    expected_input,
    metrics,
    read_results,
    real_expected,
    real_inputs,
    real_labels,
    real_metrics,
    same_input,
    same_unit,
    same_value,
    score_real,
    score_report,
    score_responses,
    summary,
    wilson,
    withheld,
    write_results,
)
from bench.spec import RENDER_SPEC, TRUTH, RenderSpec, Truth
from lab2clock.checks import Issue
from lab2clock.stage1 import RawItem, RawReport
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


def test_a_misread_count_is_blamed_for_the_inputs_it_withholds():
    spec = load(RenderSpec, RENDER_SPEC, "R07")
    count = next(row for row in spec.rows if row.analyte == "lymphocyte_count")
    result = outcomes("R07", edit("R07", count.name, value="4.1"))
    assert count.value != "4.1"
    wrong = {m: (o.error, o.got) for m, o in result.items() if o.error}
    assert wrong == {
        "lymphocyte_percent": ("value", None),
        "white_blood_cell_count": ("value", None),
    }


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


# Results and summary.


def test_one_row_per_marker_per_report_per_run():
    rows = score_responses()
    assert all(list(row) == list(COLUMNS) for row in rows)
    keys = [(row["extractor"], row["run"], row["report"]) for row in rows]
    labels = real_labels() | real_labels(medrepbench.HELDOUT_LABELLED)
    labelled = {r: len(rows) for r, rows in labels.items()}
    printed = [
        (row["extractor"], row["run"], row["report"])
        for row in rows
        if row["printed"] or row["split"] not in ("real", "heldout")
    ]
    for key in set(keys):
        report = key[2]
        assert printed.count(key) == labelled.get(report, 9)
    oracle_reports = {k for k in set(keys) if k[:2] == ("oracle", "1")}
    assert len(oracle_reports) == 25


def test_results_read_back_as_written(tmp_path):
    rows = score_responses()
    write_results(rows, tmp_path / "results.csv")
    read = read_results(tmp_path / "results.csv")
    assert [outcome for _, outcome in read] == [
        Outcome(**{f: row[f] for f in Outcome.__dataclass_fields__}) for row in rows
    ]
    # The context reads back as text, an empty cell for no condition.
    assert read[0][0] == {
        key: "" if rows[0][key] is None else str(rows[0][key]) for key in read[0][0]
    }


def test_the_summary_counts_every_extractor_run_and_error(tmp_path):
    # Two runs of a reader that misreads R07's CRP unit, beside the oracle.
    for extractor, run in [("oracle", "1"), ("sloppy", "1"), ("sloppy", "2")]:
        for report in REPORTS:
            r = response(report)
            if extractor == "sloppy" and report == "R07":
                r = RawReport(items=edit("R07", "超敏C反应蛋白", unit="mg/dL"))
            oracle.write(report, r, tmp_path / extractor / run)
    write_results(score_responses(tmp_path), tmp_path / "results.csv")
    text = summary(read_results(tmp_path / "results.csv"))
    assert "| sloppy | – | test | 2 | 99.4% (96.9%–99.9%), 179/180 |" in text
    assert "| sloppy | – | test | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |" in text
    assert "| oracle | – | test | 1 | 100.0% (97.9%–100.0%), 180/180 |" in text
    assert "| sloppy | – | dev | 1 | 100.0%" in text


def test_each_row_names_its_prompt(tmp_path):
    prompt = prompts.load()
    for report in REPORTS:
        responses.write(
            report, Response.of(response(report), prompt), tmp_path / "model" / "1"
        )
    rows = score_responses(tmp_path)
    assert {row["prompt"] for row in rows} == {"extract_v1"}
    text = summary(read_results_of(rows, tmp_path))
    assert "| model | extract_v1 | test | 1 | 100.0%" in text


def test_an_invalid_response_loses_every_printed_marker_to_the_schema(tmp_path):
    failed = Response.of(None, prompts.load(), [Failure(reason="x", output="{")])
    responses.write("R07", failed, tmp_path / "model" / "1")
    rows = score_responses(tmp_path)
    spec = load(RenderSpec, RENDER_SPEC, "R07")
    printed = {row.analyte for row in spec.rows if row.analyte}
    for row in rows:
        if row["marker"] in printed:
            assert (row["error"], row["got"]) == ("invalid", None)
        else:
            # Nothing was delivered, and a missing marker should not be.
            assert row["correct"] and row["error"] is None


def test_an_extractor_that_mixes_prompts_is_refused(tmp_path):
    # The same version name, but its text edited in place between two runs.
    v1 = prompts.load()
    edited = Prompt(v1.version, v1.text + "Also read the comments.\n")
    for run, prompt in [("1", v1), ("2", edited)]:
        responses.write(
            "R01", Response.of(response("R01"), prompt), tmp_path / "model" / run
        )
    with pytest.raises(ValueError, match="model mixes prompts"):
        score_responses(tmp_path)


def read_results_of(rows, tmp_path):
    write_results(rows, tmp_path / "results.csv")
    return read_results(tmp_path / "results.csv")


def test_committed_results_match_a_fresh_run(tmp_path):
    # Catches a response, spec or scorer changed without rerunning bench.score.
    write_results(score_responses(), tmp_path / "results.csv")
    assert (tmp_path / "results.csv").read_text() == RESULTS.read_text()
    assert summary(read_results(RESULTS)) == SUMMARY.read_text()


# The real set.


def labelled(*rows):
    return [Labelled(m, n, v, u) for m, n, v, u in rows]


def read(*items):
    return RawReport(
        items=[RawItem(name=n, value=v, unit=u, page=1) for n, v, u in items]
    )


def test_a_real_row_read_as_printed_is_correct_and_reaches_the_clock():
    rows = labelled(("white_blood_cell_count", "白细胞", "6.72", "10^9/L"))
    [o] = score_real("M01", rows, read(("白细胞", "6.72", "10^9/L")))
    assert (o.correct, o.error, o.expected, o.got) == (True, None, 6.72, 6.72)
    assert real_inputs([o]) == [(True, "right")]


def test_a_real_row_under_another_name_is_found_by_value_and_unit():
    rows = labelled(("white_blood_cell_count", "白细胞(WBC)", "5.70", None))
    [o] = score_real("M01", rows, read(("★白细胞(WBC)", "5.70", None)))
    assert o.correct and o.read_value == "5.70"


def test_real_rows_misread_omitted_or_unreadable():
    rows = labelled(
        ("albumin", "白蛋白", "40.1", "g/L"),
        ("glucose", "葡萄糖", "5.2", "mmol/L"),
        ("creatinine", "肌酐", "71", "umol/L"),
    )
    response = read(("白蛋白", "40.7", "g/L"), ("葡萄糖", "5.2", "mmol/l"))
    errors = [o.error for o in score_real("M01", rows, response)]
    # mmol/l is mmol/L up to letter case, so glucose is correct.
    assert errors == ["value", None, "omitted"]
    assert {o.error for o in score_real("M01", rows, None)} == {"invalid"}


def test_two_rows_for_one_marker_are_each_scored():
    rows = labelled(
        ("c_reactive_protein", "超敏C反应蛋白", ">5.0", "mg/l"),
        ("c_reactive_protein", "C反应蛋白", "5.5", "mg/l"),
    )
    response = read(("C反应蛋白", "5.5", "mg/l"), ("超敏C反应蛋白", ">5.0", "mg/l"))
    assert [o.read_value for o in score_real("M01", rows, response)] == [">5.0", "5.5"]


def test_the_hand_checked_corrections_replace_the_labels():
    labels = real_labels()
    m02 = {row.name: row for row in labels["M02"]}
    # The label gave 10^9/L, which the row does not print.
    assert m02["白细胞计数"].unit is None
    rows = [row for rows in labels.values() for row in rows]
    assert not any(row.unit == "mg/1" for row in rows)
    assert sum(len(rows) for rows in labels.values()) == 149


def test_real_rates_count_value_and_unit_separately():
    rows = labelled(
        ("albumin", "白蛋白", "40.1", "g/L"),
        ("glucose", "葡萄糖", "5.2", None),
        ("creatinine", "肌酐", "71", "umol/L"),
    )
    response = read(("白蛋白", "40.1", "g/L"), ("葡萄糖", "5.2", "mmol/L"))
    rates = real_metrics(score_real("M01", rows, response))
    assert [(rates[k].k, rates[k].n) for k in ("value", "unit", "both")] == [
        (2, 3),
        (1, 3),
        (1, 3),
    ]


def test_a_real_row_under_another_name_and_a_noisy_label_unit_is_found_by_value():
    rows = labelled(("albumin", "白蛋白", "38.6", "g/1"))
    [o] = score_real("M01", rows, read(("ALB", "38.6", "g/l")))
    # Found, so not omitted; the unit disagrees with the noisy label.
    assert (o.read_value, o.error) == ("38.6", "unit")


@pytest.mark.parametrize("got", ["50.68 +", "32.38 -", "50.68+"])
def test_a_plus_or_minus_flag_is_not_part_of_the_value(got):
    assert same_value(got, got.rstrip("+- "))


def test_a_real_crp_is_expected_in_the_clocks_unit():
    [row] = labelled(("c_reactive_protein", "C反应蛋白", "16.0↑", "mg/L"))
    assert real_expected(row) == pytest.approx(1.6)


@pytest.mark.parametrize(
    "row",
    [
        ("white_blood_cell_count", "白细胞(WBC)", "5.70", None),
        ("red_cell_distribution_width", "RDW", "36.40", "fL"),
    ],
)
def test_a_label_that_cannot_say_the_clock_input_expects_none(row):
    [row] = labelled(row)
    assert real_expected(row) is None


def test_what_reaches_the_clock_from_a_real_report():
    rows = labelled(
        ("albumin", "白蛋白", "40.1", "g/L"),
        ("glucose", "葡萄糖", "5.2", "mmol/L"),
        ("creatinine", "肌酐", "71", "umol/L"),
        ("mean_cell_volume", "平均红细胞体积", "88.2", None),
    )
    response = read(
        ("白蛋白", "40.7", "g/L"),  # misread, and delivered
        ("葡萄糖", "5.2", "mmol/L"),
        ("平均红细胞体积", "88.2", "fL"),  # the label gives no unit to check
        ("碱性磷酸酶", "81", "U/L"),  # no label row names it
    )
    outcomes = score_real("M01", rows, response)
    assert real_inputs(outcomes) == [
        (True, "wrong"),
        (True, "right"),
        (True, "missing"),
        (True, "unverified"),
        (False, "unverified"),
    ]
    extra = outcomes[-1]
    assert (extra.marker, extra.printed, extra.got) == (
        "alkaline_phosphatase",
        False,
        81,
    )


def test_an_unlabelled_delivery_does_not_count_toward_the_stage_1_rates():
    rows = labelled(("glucose", "葡萄糖", "5.2", "mmol/L"))
    response = read(("葡萄糖", "5.2", "mmol/L"), ("碱性磷酸酶", "81", "U/L"))
    rates = real_metrics(score_real("M01", rows, response))
    assert (rates["both"].k, rates["both"].n) == (1, 1)


def test_one_of_two_labelled_rows_for_a_marker_makes_its_input_right():
    rows = labelled(
        ("c_reactive_protein", "超敏C反应蛋白", ">5.0", "mg/l"),
        ("c_reactive_protein", "C反应蛋白", "5.5", "mg/l"),
    )
    # Only the CRP row is read, so the core delivers it, unduplicated.
    outcomes = score_real("M01", rows, read(("C反应蛋白", "5.5", "mg/l")))
    assert real_inputs(outcomes) == [(True, "right")]


def test_nothing_reaches_the_clock_from_an_invalid_real_response():
    rows = labelled(("glucose", "葡萄糖", "5.2", "mmol/L"))
    assert real_inputs(score_real("M01", rows, None)) == [(True, "missing")]
