import json
import subprocess
import sys
from pathlib import Path

import pytest

from lab2clock.__main__ import main
from lab2clock.assemble import assemble
from lab2clock.clock_spec import FIELD_NAMES, MARKERS
from lab2clock.stage1 import RawReport

EXAMPLE = Path(__file__).parent / "data" / "stage1_example.json"

# One row per marker, every one in the clock's unit except where noted.
COMPLETE = [
    ("Albumin", "42", "g/L"),
    ("Creatinine", "88", "umol/L"),
    ("Glucose", "5.5", "mmol/L"),
    ("CRP", "1.2", "mg/L"),
    ("Lymphocytes", "30.0", "%"),
    ("MCV", "90", "fL"),
    ("RDW-CV", "13.0", "%"),
    ("ALP", "70", "U/L"),
    ("WBC", "7.00", "10^9/L"),
]


def report(*rows):
    return RawReport(
        items=[
            {"name": name, "value": value, "unit": unit, "page": 1}
            for name, value, unit in rows
        ]
    )


def without(name):
    return [row for row in COMPLETE if row[0] != name]


def issues(output, check):
    return [issue for issue in output["issues"] if issue["check"] == check]


def test_complete_report_is_ok():
    output = assemble(report(*COMPLETE), age=52)
    assert output["ok"] is True
    assert list(output["inputs"]) == list(FIELD_NAMES)
    assert output["missing"] == []
    assert output["issues"] == []


def test_values_are_converted_and_keep_their_source():
    output = assemble(report(*COMPLETE), age=52)
    crp = output["inputs"]["c_reactive_protein"]
    assert crp["value"] == pytest.approx(0.12)
    assert crp["unit"] == "mg/dL"
    assert crp["source"] == {"name": "CRP", "value": "1.2", "unit": "mg/L", "page": 1}


def test_flags_and_censoring_are_kept():
    rows = [*without("CRP"), ("CRP", "<0.3", "mg/L")]
    rows = [
        row if row[0] != "Glucose" else ("Glucose", "8.1 H", "mmol/L") for row in rows
    ]
    output = assemble(report(*rows), age=52)
    assert output["ok"] is True
    assert output["inputs"]["glucose"]["flags"] == ["H"]
    crp = output["inputs"]["c_reactive_protein"]
    assert (crp["censored"], crp["limit"]) == (True, "<")
    assert crp["value"] == pytest.approx(0.03)
    # Delivered, but with a warning that the true value is lower.
    [issue] = [i for i in output["issues"] if i["check"] == "limit"]
    assert issue["severity"] == "warning"


def test_a_value_above_a_limit_is_withheld():
    # >5.0 mg/L could be 6 or 60: delivering 5.0 would understate it.
    output = assemble(report(*without("CRP"), ("CRP", ">5.0", "mg/L")), age=52)
    assert output["ok"] is False
    assert "c_reactive_protein" not in output["inputs"]
    [issue] = output["issues"]
    assert (issue["check"], issue["severity"]) == ("limit", "error")


def test_missing_age_is_an_error():
    output = assemble(report(*COMPLETE))
    assert output["ok"] is False
    assert output["missing"] == ["age"]
    [issue] = issues(output, "missing")
    assert issue["analyte"] == "age"


def test_missing_marker_is_listed():
    output = assemble(report(*without("ALP")), age=52)
    assert output["ok"] is False
    assert output["missing"] == ["alkaline_phosphatase"]


def test_empty_report_misses_everything():
    output = assemble(report())
    assert output["inputs"] == {}
    assert output["missing"] == list(FIELD_NAMES)
    assert len(issues(output, "missing")) == len(MARKERS) + 1


def test_unmapped_rows_are_listed_not_used():
    output = assemble(report(*COMPLETE, ("Prealbumin", "250", "mg/L")), age=52)
    assert output["ok"] is True
    assert output["unmapped"] == [
        {"name": "Prealbumin", "value": "250", "unit": "mg/L", "page": 1}
    ]


@pytest.mark.parametrize(
    ("row", "check"),
    [
        (("ALP", "7O", "U/L"), "value"),
        (("ALP", "70", "U/HPF"), "unit"),
        (("ALP", "70", None), "conversion"),
        (("ALP", "70", "mg/dL"), "conversion"),
    ],
)
def test_unreadable_row_is_withheld(row, check):
    output = assemble(report(*without("ALP"), row), age=52)
    assert output["ok"] is False
    assert "alkaline_phosphatase" not in output["inputs"]
    assert output["missing"] == ["alkaline_phosphatase"]
    [issue] = output["issues"]
    assert issue["check"] == check
    assert issue["analyte"] == "alkaline_phosphatase"


def test_impossible_value_is_withheld():
    # White cells printed in cells/uL but labelled 10^9/L.
    output = assemble(report(*without("WBC"), ("WBC", "7000", "10^9/L")), age=52)
    assert "white_blood_cell_count" not in output["inputs"]
    [issue] = output["issues"]
    assert issue["check"] == "plausibility"


def test_agreeing_duplicate_warns_and_delivers():
    output = assemble(report(*COMPLETE, ("Glucose", "99", "mg/dL")), age=52)
    assert output["ok"] is True
    assert output["inputs"]["glucose"]["value"] == pytest.approx(5.5)
    [issue] = output["issues"]
    assert (issue["check"], issue["severity"]) == ("duplicate", "warning")


def test_differing_duplicate_is_withheld():
    output = assemble(report(*COMPLETE, ("Glucose", "6.1", "mmol/L")), age=52)
    assert output["ok"] is False
    assert "glucose" not in output["inputs"]
    assert output["missing"] == ["glucose"]


def test_derives_lymphocyte_percent_from_counts():
    rows = [*without("Lymphocytes"), ("Lymphocytes", "2.10", "10^9/L")]
    output = assemble(report(*rows), age=52)
    assert output["ok"] is True
    percent = output["inputs"]["lymphocyte_percent"]
    assert percent["value"] == pytest.approx(30)
    assert percent["derived"] is True
    assert [source["name"] for source in percent["sources"]] == ["Lymphocytes", "WBC"]


def test_count_above_white_cells_fails_derivation():
    rows = [*without("Lymphocytes"), ("Lymphocytes", "21.0", "10^9/L")]
    output = assemble(report(*rows), age=52)
    assert output["missing"] == ["lymphocyte_percent"]
    [issue] = output["issues"]
    assert issue["check"] == "derivation"


def test_censored_count_cannot_derive():
    rows = [*without("Lymphocytes"), ("Lymphocytes", "<0.1", "10^9/L")]
    output = assemble(report(*rows), age=52)
    [issue] = output["issues"]
    assert issue["check"] == "derivation"


def test_count_without_white_cells_leaves_percent_missing():
    rows = [*without("Lymphocytes"), ("Lymphocytes", "2.10", "10^9/L")]
    output = assemble(report(*[row for row in rows if row[0] != "WBC"]), age=52)
    assert output["missing"] == ["lymphocyte_percent", "white_blood_cell_count"]
    assert {issue["check"] for issue in output["issues"]} == {"missing"}


def test_printed_percent_is_not_derived():
    output = assemble(report(*COMPLETE, ("Lymph#", "2.10", "10^9/L")), age=52)
    assert output["ok"] is True
    assert output["inputs"]["lymphocyte_percent"]["derived"] is False


def test_misread_percent_fails_cross_check():
    # 35.7 misread as 30.7: the counts give 30.0.
    rows = [*without("Lymphocytes"), ("Lymphocytes", "30.7", "%")]
    output = assemble(report(*rows, ("Lymph#", "2.10", "10^9/L")), age=52)
    assert output["ok"] is False
    # Either could be the misread one, so neither reaches the clock.
    assert set(output["missing"]) == {"lymphocyte_percent", "white_blood_cell_count"}
    assert {issue["check"] for issue in output["issues"]} == {"consistency"}


def test_misread_white_cells_fail_cross_check_and_are_withheld():
    # A white-cell count of 5.70 hidden under a pen line, guessed as 5.16: the
    # count and percent printed beside it give 5.72 to 5.77.
    rows = [row for row in COMPLETE if row[0] not in ("WBC", "Lymphocytes")]
    rows += [("WBC", "5.16", "10^9/L"), ("Lymphocytes", "29.4", "%")]
    rows += [("Lymph#", "1.69", "10^9/L")]
    output = assemble(report(*rows), age=52)
    assert "white_blood_cell_count" not in output["inputs"]
    assert "lymphocyte_percent" not in output["inputs"]


# Command line.


def test_cli_runs_end_to_end_on_example():
    result = subprocess.run(
        [sys.executable, "-m", "lab2clock", str(EXAMPLE), "--age", "52"],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["ok"] is True
    assert output["missing"] == []
    assert output["inputs"]["lymphocyte_percent"]["derived"] is True


def test_cli_exits_1_on_report_errors(capsys):
    assert main([str(EXAMPLE)]) == 1
    assert json.loads(capsys.readouterr().out)["missing"] == ["age"]


def test_cli_exits_2_on_invalid_input(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"items": [{"name": "Albumin", "value": 42}]}')
    assert main([str(path)]) == 2
    assert capsys.readouterr().err.startswith("lab2clock:")


def test_the_lab2clock_command_runs_main():
    from importlib.metadata import entry_points

    [script] = entry_points(group="console_scripts", name="lab2clock")
    assert script.load() is main


@pytest.mark.parametrize("age", ["-3", "0", "200", "fifty"])
def test_the_cli_refuses_an_age_that_is_not_one(age, capsys):
    with pytest.raises(SystemExit) as exit:
        main([str(EXAMPLE), "--age", age])
    assert exit.value.code == 2
    assert "--age" in capsys.readouterr().err


def test_a_urine_white_cell_count_is_not_the_blood_marker():
    # 204 per uL from a urinalysis, under the blood marker's name.
    output = assemble(report(*without("WBC"), ("白细胞(WBC)", "204", "个/ul")), age=52)
    assert "white_blood_cell_count" not in output["inputs"]
    assert "white_blood_cell_count" in output["missing"]
    assert any(i["check"] == "specimen" for i in output["issues"])
    assert output["unmapped"][0]["value"] == "204"


def test_a_blood_count_beside_a_urine_count_still_counts():
    output = assemble(report(*COMPLETE, ("白细胞(WBC)", "204", "个/ul")), age=52)
    assert output["inputs"]["white_blood_cell_count"]["value"] == 7.0


def test_a_blood_count_per_microlitre_is_read():
    output = assemble(report(*without("WBC"), ("WBC", "6500", "/uL")), age=52)
    assert output["inputs"]["white_blood_cell_count"]["value"] == 6.5
