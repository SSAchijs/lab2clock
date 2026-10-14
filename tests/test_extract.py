import json
from types import SimpleNamespace

from bench import extract, prompts
from lab2clock.stage1 import RawItem, RawReport

REPORT = RawReport(items=[RawItem(name="CRP", value="2,4", unit="mg/L", page=1)])
VALID = REPORT.model_dump_json()
PAGES = [{"type": "text", "text": "a stand-in for the report's pages"}]


class FakeMessages:
    """Answers each call with the next (stop reason, text) in the script."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **request):
        self.calls.append(request)
        stop_reason, text = self.script.pop(0)
        return SimpleNamespace(
            stop_reason=stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=text),
            ],
        )


def read(*script):
    messages = FakeMessages(script)
    client = SimpleNamespace(messages=messages)
    response = extract.read(client, "claude-haiku-5-5", prompts.load(), PAGES)
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
    assert request["messages"] == [{"role": "user", "content": PAGES}]
    assert request["output_config"] == {
        "format": {"type": "json_schema", "schema": extract.SCHEMA}
    }


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
