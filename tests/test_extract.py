import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from bench import degrade, extract, prompts, render, responses
from bench.spec import RENDER_SPEC, RenderSpec
from lab2clock.stage1 import RawItem, RawReport

REPORT = RawReport(items=[RawItem(name="CRP", value="2,4", unit="mg/L", page=1)])
VALID = REPORT.model_dump_json()
PAGES = extract.Input(
    "pdf",
    [render.OUT / "R01.pdf"],
    [{"type": "text", "text": "a stand-in for the report's pages"}],
)


class FakeMessages:
    """Answers each call with the next (stop reason, text) in the script, or
    with a valid answer once the script runs out."""

    def __init__(self, script=()):
        self.script = list(script)
        self.calls = []

    def create(self, **request):
        self.calls.append(request)
        stop_reason, text = self.script.pop(0) if self.script else ("end_turn", VALID)
        return SimpleNamespace(
            stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=text),
            ],
        )


def read(*script):
    messages = FakeMessages(script)
    client = SimpleNamespace(messages=messages)
    response = extract.read(client, "claude-haiku-5-5", prompts.load(), PAGES, 1)
    return response, messages.calls


def test_a_valid_answer_is_kept_without_a_retry():
    response, calls = read(("end_turn", VALID))
    assert response.report == REPORT
    assert response.failures == []
    assert len(calls) == 1


def test_the_request_holds_the_answer_to_the_stage1_schema():
    _, [request] = read(("end_turn", VALID))
    assert request["model"] == "claude-haiku-5-5"
    assert request["system"] == prompts.load().text
    assert request["messages"] == [{"role": "user", "content": PAGES.content}]
    assert request["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": extract.SCHEMA},
    }
    assert request["thinking"] == {"type": "adaptive"}


def test_every_setting_sent_is_pinned_in_the_key():
    _, [request] = read(("end_turn", VALID))
    assert extract.SETTINGS["max_tokens"] == request["max_tokens"]
    assert extract.SETTINGS["effort"] == request["output_config"]["effort"]
    assert extract.SETTINGS["thinking"] == request["thinking"]
    # Neither model accepts a sampling setting, so none is sent.
    assert not {"temperature", "top_p", "top_k"} & set(request)


def test_each_report_is_read_three_times():
    assert extract.RUNS == 3


def test_the_schema_sent_leaves_out_only_what_the_api_cannot_enforce():
    text = json.dumps(extract.SCHEMA)
    assert "minLength" not in text.replace("{minLength: 1}", "")
    assert extract.SCHEMA["required"] == ["items"]
    item = extract.SCHEMA["$defs"]["RawItem"]
    assert item["required"] == ["name", "value", "unit", "page"]
    assert item["additionalProperties"] is False


def test_a_failed_answer_is_retried_once_and_the_failure_kept():
    response, calls = read(("end_turn", "{not json"), ("end_turn", VALID))
    assert response.report == REPORT
    [failure] = response.failures
    assert failure.output == "{not json"
    assert len(calls) == 2


def test_the_response_records_the_form_and_files_sent():
    for script in [[("end_turn", VALID)], [("end_turn", "{"), ("end_turn", "{")]]:
        response, _ = read(*script)
        assert response.form == "pdf"
        assert list(response.files) == ["R01.pdf"]


def test_a_second_failure_is_recorded_not_retried():
    response, calls = read(("end_turn", "{not json"), ("end_turn", "[]"))
    assert response.report is None
    assert [f.output for f in response.failures] == ["{not json", "[]"]
    assert (response.prompt, response.prompt_sha256) == (
        prompts.CURRENT,
        prompts.load().sha256,
    )
    assert len(calls) == 2


def test_rules_the_api_does_not_enforce_are_checked_here():
    empty_name = json.dumps(
        {"items": [{"name": "", "value": "2,4", "unit": "mg/L", "page": 1}]}
    )
    page_zero = json.dumps(
        {"items": [{"name": "CRP", "value": "2,4", "unit": "mg/L", "page": 0}]}
    )
    response, _ = read(("end_turn", empty_name), ("end_turn", page_zero))
    assert response.report is None
    assert "name" in response.failures[0].reason
    assert "page" in response.failures[1].reason


def test_a_refused_or_cut_off_answer_fails_even_if_it_parses():
    response, _ = read(("refusal", VALID), ("max_tokens", VALID))
    assert response.report is None
    assert [f.reason for f in response.failures] == [
        "the answer stopped with refusal",
        "the answer stopped with max_tokens",
    ]


# The report in its native form.


def spec(report):
    return RenderSpec.model_validate_json((RENDER_SPEC / f"{report}.json").read_text())


def specs():
    return [spec(path.stem) for path in sorted(RENDER_SPEC.glob("*.json"))]


def test_a_digital_report_goes_as_its_pdf():
    s = next(s for s in specs() if not s.conditions.photo)
    sent = extract.report_input(s)
    assert (sent.form, sent.files) == ("pdf", [render.OUT / f"{s.report}.pdf"])
    [block] = sent.content
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(block["source"]["data"]) == sent.files[0].read_bytes()


def test_a_photographed_report_goes_as_one_labelled_photo_per_page():
    s = next(
        s for s in specs() if s.conditions.photo and len({r.page for r in s.rows}) > 1
    )
    sent = extract.report_input(s)
    assert sent.form == "photo"
    assert sent.files == [degrade.OUT / f"{s.report}-{p}.jpg" for p in (1, 2)]
    assert [b["type"] for b in sent.content] == ["text", "image", "text", "image"]
    assert [b["text"] for b in sent.content[::2]] == ["Page 1", "Page 2"]
    for block, photo in zip(sent.content[1::2], sent.files, strict=True):
        assert block["source"]["media_type"] == "image/jpeg"
        assert base64.b64decode(block["source"]["data"]) == photo.read_bytes()


@pytest.mark.parametrize(
    "report", [path.stem for path in sorted(RENDER_SPEC.glob("*.json"))]
)
def test_every_report_has_the_files_it_is_sent_as(report):
    sent = extract.report_input(spec(report))
    assert sent.form == ("photo" if spec(report).conditions.photo else "pdf")
    assert all(path.exists() for path in sent.files)


# The cache.

MODEL = "claude-haiku-5-5"


def client():
    return SimpleNamespace(messages=FakeMessages())


def test_a_response_records_what_it_was_read_from_and_its_cost():
    response, _ = read(("end_turn", "{"), ("end_turn", VALID))
    assert response.model == MODEL
    assert response.settings == extract.SETTINGS
    assert response.files == {
        "R01.pdf": hashlib.sha256((render.OUT / "R01.pdf").read_bytes()).hexdigest()
    }
    assert response.key == extract.key(MODEL, prompts.load(), PAGES, 1)
    # Both attempts were billed.
    assert (response.usage.input_tokens, response.usage.output_tokens) == (2000, 400)


def test_a_rerun_makes_no_api_call(tmp_path):
    dev = [s for s in specs() if s.split == "dev"]
    first, second = client(), client()
    assert extract.run(first, MODEL, prompts.load(), dev, 1, tmp_path) == (5, 0)
    assert extract.run(second, MODEL, prompts.load(), dev, 1, tmp_path) == (0, 5)
    assert len(first.messages.calls) == 5
    assert second.messages.calls == []
    out = tmp_path / "claude-haiku-5-5_extract_v1" / "1"
    assert sorted(p.stem for p in out.glob("*.json")) == [s.report for s in dev]


def test_each_run_is_read_separately(tmp_path):
    [r01] = [s for s in specs() if s.report == "R01"]
    fake = client()
    for number in (1, 2, 3):
        assert extract.run(fake, MODEL, prompts.load(), [r01], number, tmp_path) == (
            1,
            0,
        )
    assert len(fake.messages.calls) == 3


def test_the_key_changes_with_anything_that_can_change_the_answer(tmp_path):
    prompt = prompts.load()
    base = extract.key(MODEL, prompt, PAGES, 1)
    edited = prompts.Prompt(prompt.version, prompt.text + " ")
    copy = tmp_path / "R01.pdf"
    copy.write_bytes(PAGES.files[0].read_bytes() + b"%")
    other_file = extract.Input("pdf", [copy], PAGES.content)
    assert (
        len(
            {
                base,
                extract.key("claude-opus-5-5", prompt, PAGES, 1),
                extract.key(MODEL, edited, PAGES, 1),
                extract.key(MODEL, prompt, other_file, 1),
                extract.key(MODEL, prompt, PAGES, 2),
            }
        )
        == 5
    )


def test_a_saved_response_read_from_other_inputs_stops_the_run(tmp_path):
    [r01] = [s for s in specs() if s.report == "R01"]
    extract.run(client(), MODEL, prompts.load(), [r01], 1, tmp_path)
    path = tmp_path / "claude-haiku-5-5_extract_v1" / "1" / "R01.json"
    saved = responses.read(path)
    responses.write("R01", saved.model_copy(update={"key": "stale"}), path.parent)
    with pytest.raises(SystemExit, match="different inputs"):
        extract.run(client(), MODEL, prompts.load(), [r01], 1, tmp_path)


# The test set waits for the frozen prompt.


def test_no_test_report_is_read_before_the_prompt_is_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "FROZEN", tmp_path / "frozen.json")
    test = [s for s in specs() if s.split == "test"][:1]
    fake = client()
    with pytest.raises(SystemExit, match="not frozen"):
        extract.run(fake, MODEL, prompts.load(), test, 1, tmp_path)
    assert fake.messages.calls == []
    prompts.freeze(prompts.load())
    assert extract.run(fake, MODEL, prompts.load(), test, 1, tmp_path) == (1, 0)


def test_development_reports_are_read_before_the_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "FROZEN", tmp_path / "frozen.json")
    dev = [s for s in specs() if s.split == "dev"][:1]
    assert extract.run(client(), MODEL, prompts.load(), dev, 1, tmp_path) == (1, 0)
