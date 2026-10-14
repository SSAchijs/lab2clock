import pytest
from pydantic import ValidationError

from bench import prompts, responses
from bench.prompts import Prompt
from bench.responses import Response
from lab2clock.stage1 import RawItem, RawReport

REPORT = RawReport(items=[RawItem(name="CRP", value="2,4 H", unit="mg/L", page=1)])


def test_the_current_prompt_is_its_own_file():
    prompt = prompts.load()
    assert prompt.version == prompts.CURRENT == "extract_v1"
    assert prompt.text == (prompts.PROMPTS / "extract_v1.txt").read_text()


def test_the_prompt_asks_for_a_transcription_not_an_interpretation():
    text = prompts.load().text
    for instruction in [
        "exactly as printed",
        "Do not convert units, translate names",
        "Include every analyte",
        "previous results, reference intervals",
    ]:
        assert instruction in text


def test_any_edit_changes_the_hash():
    text = prompts.load().text
    assert Prompt("extract_v1", text + " ").sha256 != prompts.load().sha256


def test_a_response_records_its_prompt_and_reads_back(tmp_path):
    prompt = prompts.load()
    path = responses.write("R01", Response.of(REPORT, prompt), tmp_path)
    saved = responses.read(path)
    assert saved.report == REPORT
    assert (saved.prompt, saved.prompt_sha256) == (prompt.version, prompt.sha256)


@pytest.mark.parametrize("prompt, sha", [("extract_v1", None), (None, "ab12")])
def test_a_version_without_its_hash_is_refused(prompt, sha):
    with pytest.raises(ValidationError, match="needs its hash"):
        Response(prompt=prompt, prompt_sha256=sha, report=REPORT)
