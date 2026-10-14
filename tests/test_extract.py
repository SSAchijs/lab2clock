import base64
import hashlib
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from bench import degrade, extract, medrepbench, prompts, render, responses
from bench.spec import RENDER_SPEC, RenderSpec
from lab2clock.stage1 import RawItem, RawReport

REPORT = RawReport(items=[RawItem(name="CRP", value="2,4", unit="mg/L", page=1)])
VALID = REPORT.model_dump_json()


def spec(report):
    return RenderSpec.model_validate_json((RENDER_SPEC / f"{report}.json").read_text())


def specs():
    return [spec(path.stem) for path in sorted(RENDER_SPEC.glob("*.json"))]


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    """Stand-ins for the printed PDFs and photos, which bench/data holds only
    once generated; every file gets its own bytes, as a real one would."""
    reports, photos = tmp_path / "data" / "reports", tmp_path / "data" / "photos"
    reports.mkdir(parents=True)
    photos.mkdir()
    for s in specs():
        (reports / f"{s.report}.pdf").write_bytes(f"%PDF {s.report}".encode())
        if s.conditions.photo:
            for page in {row.page for row in s.rows}:
                photo = f"{s.report}-{page}.jpg"
                (photos / photo).write_bytes(b"\xff\xd8" + photo.encode())
    monkeypatch.setattr(render, "OUT", reports)
    monkeypatch.setattr(degrade, "OUT", photos)


def pages():
    return extract.Input(
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
    response = extract.read(client, "claude-haiku-5-5", prompts.load(), pages(), 1)
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
    assert request["messages"] == [{"role": "user", "content": pages().content}]
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
def test_every_report_is_sent_as_its_pdf_or_its_photos(report):
    s = spec(report)
    sent = extract.report_input(s)
    if s.conditions.photo:
        pages = sorted({row.page for row in s.rows})
        assert sent.form == "photo"
        assert [p.name for p in sent.files] == [f"{report}-{p}.jpg" for p in pages]
    else:
        assert (sent.form, [p.name for p in sent.files]) == ("pdf", [f"{report}.pdf"])


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
    assert response.key == extract.key(MODEL, prompts.load(), pages(), 1)
    # Both attempts were billed.
    assert (response.usage.input_tokens, response.usage.output_tokens) == (2000, 400)


def test_a_rerun_makes_no_api_call(tmp_path):
    dev = [s for s in specs() if s.split == "dev"]
    first, second = client(), client()
    assert extract.run(
        first, MODEL, prompts.load(), extract.synthetic_jobs(dev), 1, tmp_path
    ) == (5, 0)
    assert extract.run(
        second, MODEL, prompts.load(), extract.synthetic_jobs(dev), 1, tmp_path
    ) == (0, 5)
    assert len(first.messages.calls) == 5
    assert second.messages.calls == []
    out = tmp_path / "claude-haiku-5-5_extract_v1" / "1"
    assert sorted(p.stem for p in out.glob("*.json")) == [s.report for s in dev]


def test_each_run_is_read_separately(tmp_path):
    [r01] = [s for s in specs() if s.report == "R01"]
    fake = client()
    for number in (1, 2, 3):
        assert extract.run(
            fake, MODEL, prompts.load(), extract.synthetic_jobs([r01]), number, tmp_path
        ) == (
            1,
            0,
        )
    assert len(fake.messages.calls) == 3


def test_the_key_changes_with_anything_that_can_change_the_answer(tmp_path):
    prompt = prompts.load()
    base = extract.key(MODEL, prompt, pages(), 1)
    edited = prompts.Prompt(prompt.version, prompt.text + " ")
    copy = tmp_path / "R01.pdf"
    copy.write_bytes(pages().files[0].read_bytes() + b"%")
    other_file = extract.Input("pdf", [copy], pages().content)
    assert (
        len(
            {
                base,
                extract.key("claude-opus-5-5", prompt, pages(), 1),
                extract.key(MODEL, edited, pages(), 1),
                extract.key(MODEL, prompt, other_file, 1),
                extract.key(MODEL, prompt, pages(), 2),
            }
        )
        == 5
    )


def test_a_saved_response_read_from_other_inputs_stops_the_run(tmp_path):
    [r01] = [s for s in specs() if s.report == "R01"]
    extract.run(
        client(), MODEL, prompts.load(), extract.synthetic_jobs([r01]), 1, tmp_path
    )
    path = tmp_path / "claude-haiku-5-5_extract_v1" / "1" / "R01.json"
    saved = responses.read(path)
    responses.write("R01", saved.model_copy(update={"key": "stale"}), path.parent)
    with pytest.raises(SystemExit, match="different inputs"):
        extract.run(
            client(), MODEL, prompts.load(), extract.synthetic_jobs([r01]), 1, tmp_path
        )


# The test set waits for the frozen prompt.


def test_no_test_report_is_read_before_the_prompt_is_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "FROZEN", tmp_path / "frozen.json")
    test = [s for s in specs() if s.split == "test"][:1]
    fake = client()
    with pytest.raises(SystemExit, match="not frozen"):
        extract.run(
            fake, MODEL, prompts.load(), extract.synthetic_jobs(test), 1, tmp_path
        )
    assert fake.messages.calls == []
    prompts.freeze(prompts.load())
    assert extract.run(
        fake, MODEL, prompts.load(), extract.synthetic_jobs(test), 1, tmp_path
    ) == (1, 0)


def test_development_reports_are_read_before_the_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "FROZEN", tmp_path / "frozen.json")
    dev = [s for s in specs() if s.split == "dev"][:1]
    assert extract.run(
        client(), MODEL, prompts.load(), extract.synthetic_jobs(dev), 1, tmp_path
    ) == (1, 0)


# Real reports.


def test_a_real_report_goes_as_its_image_labelled_page_1(tmp_path, monkeypatch):
    monkeypatch.setattr(medrepbench, "CACHE", tmp_path)
    (tmp_path / "censored").mkdir()
    (tmp_path / "censored" / "a.png").write_bytes(b"\x89PNG stand-in")
    sent = extract.real_input("a.png")
    assert (sent.form, sent.files) == ("image", [tmp_path / "censored" / "a.png"])
    label, image = sent.content
    assert label == {"type": "text", "text": "Page 1"}
    assert image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == b"\x89PNG stand-in"


def test_an_image_too_large_for_the_api_is_reencoded_at_the_same_size(
    tmp_path, monkeypatch
):
    pixels = np.random.default_rng(0).integers(0, 255, (300, 400, 3), np.uint8)
    path = tmp_path / "big.png"
    cv2.imwrite(str(path), pixels)
    monkeypatch.setattr(
        extract, "MAX_IMAGE", len(base64.b64encode(path.read_bytes())) - 1
    )
    data, media = extract._image(path)
    assert media == "image/jpeg"
    assert len(base64.b64encode(data)) <= extract.MAX_IMAGE
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == pixels.shape


def test_an_image_within_the_limit_is_sent_as_it_is(tmp_path):
    path = tmp_path / "a.jpeg"
    path.write_bytes(b"\xff\xd8 stand-in")
    assert extract._image(path) == (b"\xff\xd8 stand-in", "image/jpeg")


def test_every_real_report_is_a_job_by_its_id():
    jobs = extract.real_jobs()
    assert [j.report for j in jobs] == [f"M{i:02d}" for i in range(1, 40)]
    assert {j.split for j in jobs} == {"real"}


def test_no_real_report_is_read_before_the_prompt_is_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "FROZEN", tmp_path / "frozen.json")
    job = extract.Job("M01", "real", pages)
    fake = client()
    with pytest.raises(SystemExit, match="not frozen"):
        extract.run(fake, MODEL, prompts.load(), [job], 1, tmp_path)
    assert fake.messages.calls == []


def test_an_image_type_comes_from_its_bytes_not_its_name(tmp_path):
    path = tmp_path / "named.jpg"
    path.write_bytes(b"\x89PNG actually")
    assert extract._image(path)[1] == "image/png"
    path.write_bytes(b"GIF89a")
    with pytest.raises(ValueError, match="not a PNG or JPEG"):
        extract._image(path)
