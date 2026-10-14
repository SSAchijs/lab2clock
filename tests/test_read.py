import json
from types import SimpleNamespace

import pytest

import lab2clock.__main__ as cli
from lab2clock import read
from lab2clock.read import ReadError, content, read_report, request

PDF = b"%PDF-1.7 report"
PNG = b"\x89PNG\r\n\x1a\n page"
JPEG = b"\xff\xd8\xff page"

ROWS = [
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
ANSWER = json.dumps(
    {"items": [{"name": n, "value": v, "unit": u, "page": 1} for n, v, u in ROWS]}
)


def files(tmp_path, **named):
    out = []
    for name, data in named.items():
        path = tmp_path / name.replace("_", ".")
        path.write_bytes(data)
        out.append(path)
    return out


def message(text, stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop, content=[SimpleNamespace(type="text", text=text)]
    )


class Client:
    """A stand-in for the API client that answers from a list."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.messages = self

    def create(self, **call):
        self.calls.append(call)
        return self.answers.pop(0)


def test_a_pdf_is_sent_as_one_document(tmp_path):
    [block] = content(files(tmp_path, report_pdf=PDF))
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


def test_images_are_sent_as_numbered_pages_by_their_bytes(tmp_path):
    # The first is named .jpg but holds a PNG; its bytes decide.
    blocks = content(files(tmp_path, a_jpg=PNG, b_jpg=JPEG))
    assert [b.get("text") for b in blocks[::2]] == ["Page 1", "Page 2"]
    media = [b["source"]["media_type"] for b in blocks[1::2]]
    assert media == ["image/png", "image/jpeg"]


@pytest.mark.parametrize(
    "named",
    [{"notes_txt": b"hello"}, {"report_pdf": PDF, "page_png": PNG}],
)
def test_other_files_or_a_pdf_with_more_are_refused(tmp_path, named):
    with pytest.raises(ReadError):
        content(files(tmp_path, **named))


def test_the_call_uses_the_benchmarks_settings():
    call = request("claude-haiku-5-5", "prompt", [])
    assert call["output_config"]["effort"] == read.EFFORT
    assert call["output_config"]["format"]["schema"] == read.SCHEMA
    assert call["thinking"] == read.THINKING


def test_a_report_is_read_with_the_frozen_prompt(tmp_path):
    client = Client(message(ANSWER))
    report = read_report(files(tmp_path, a_png=PNG), client=client)
    assert len(report.items) == 9
    [call] = client.calls
    assert call["system"] == read.PROMPT.read_text(encoding="utf-8")
    assert call["model"] == read.MODEL


def test_a_broken_answer_is_retried_once_then_refused(tmp_path):
    client = Client(message("{"), message(ANSWER))
    assert len(read_report(files(tmp_path, a_png=PNG), client=client).items) == 9
    client = Client(message("{"), message(ANSWER, stop="max_tokens"))
    with pytest.raises(ReadError, match="2 attempts"):
        read_report(files(tmp_path, a_png=PNG), client=client)


def test_the_cli_reads_a_report_and_estimates_its_age(tmp_path, monkeypatch, capsys):
    client = Client(message(ANSWER))
    real = read.read_report
    monkeypatch.setattr(
        read, "read_report", lambda paths, model: real(paths, model, client)
    )
    [path] = files(tmp_path, report_png=PNG)
    assert cli.main([str(path), "--age", "52", "--age-estimate"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["inputs"]["albumin"]["source"]["name"] == "Albumin"
    assert 20 < output["phenoage"]["years"] < 90
    assert "not a diagnosis" in output["phenoage"]["note"]


def test_no_age_estimate_from_an_incomplete_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(read, "read_report", lambda paths, model: _missing_one())
    [path] = files(tmp_path, report_png=PNG)
    assert cli.main([str(path), "--age", "52", "--age-estimate"]) == 1
    assert json.loads(capsys.readouterr().out)["phenoage"] is None


def _missing_one():
    from lab2clock.stage1 import RawReport

    items = json.loads(ANSWER)["items"][1:]
    return RawReport.model_validate({"items": items})


def test_the_cli_exits_2_when_the_report_cannot_be_read(tmp_path, monkeypatch, capsys):
    # The file is refused before the key is looked for, with or without one.
    for name in read.KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "load_env", lambda: False)
    [path] = files(tmp_path, notes_txt=b"hello")
    assert cli.main([str(path), "--age", "52"]) == 2
    assert capsys.readouterr().err.startswith("lab2clock: not a PDF")


def test_without_an_api_key_the_cli_says_so_and_exits_2(tmp_path, monkeypatch, capsys):
    for name in read.KEYS:
        monkeypatch.delenv(name, raising=False)
    # No .env either: the repository's own may hold a key.
    monkeypatch.setattr(cli, "load_env", lambda: False)
    [path] = files(tmp_path, report_pdf=PDF)
    assert cli.main([str(path), "--age", "52"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("lab2clock: no API key")
    assert "Traceback" not in err


def test_a_value_below_a_limit_gives_an_age_range(tmp_path, monkeypatch, capsys):
    rows = [(n, "<5.00" if n == "CRP" else v, u) for n, v, u in ROWS]
    items = [{"name": n, "value": v, "unit": u, "page": 1} for n, v, u in rows]
    client = Client(message(json.dumps({"items": items})))
    real = read.read_report
    monkeypatch.setattr(
        read, "read_report", lambda paths, model: real(paths, model, client)
    )
    [path] = files(tmp_path, report_png=PNG)
    assert cli.main([str(path), "--age", "52", "--age-estimate"]) == 0
    age = json.loads(capsys.readouterr().out)["phenoage"]
    low, high = age["range"]
    assert age["years"] is None and low < high
    # The top is the age at the limit itself: CRP 5.00 mg/L is 0.5 mg/dL.
    assert "CRP <5.00" in age["note"]
