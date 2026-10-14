import pytest

from bench import oracle, responses
from bench.responses import Response
from bench.spec import RENDER_SPEC, RenderSpec

REPORTS = [f"R{i:02d}" for i in range(1, 26)]


def spec(report: str) -> RenderSpec:
    return RenderSpec.model_validate_json((RENDER_SPEC / f"{report}.json").read_text())


def flagged(layout: str) -> RenderSpec:
    return next(
        s
        for s in map(spec, REPORTS)
        if s.conditions.layout == layout and any(r.flag for r in s.rows)
    )


def test_the_reader_sees_only_the_printed_result_columns():
    item = oracle.extract(spec("R01")).items[0].model_dump()
    assert set(item) == {"name", "value", "unit", "page"}


def test_every_row_is_read_in_printed_order():
    s = spec("R03")
    items = oracle.extract(s).items
    assert [(i.name, i.unit, i.page) for i in items] == [
        (r.name, r.unit, r.page) for r in s.rows
    ]


def test_a_flag_is_part_of_the_value_only_in_the_two_column_layout():
    s = flagged("two_column")
    for row, item in zip(s.rows, oracle.extract(s).items, strict=True):
        assert item.value == (f"{row.value} {row.flag}" if row.flag else row.value)
    s = flagged("table")
    for row, item in zip(s.rows, oracle.extract(s).items, strict=True):
        assert item.value == row.value


def test_a_written_response_reads_back_as_the_same_report(tmp_path):
    response = oracle.extract(spec("R07"))
    path = oracle.write("R07", response, tmp_path)
    assert path == tmp_path / "R07.json"
    saved = responses.read(path)
    assert saved.report == response
    assert (saved.prompt, saved.prompt_sha256) == (None, None)
    # Chinese is written as printed, not escaped.
    assert "白细胞计数" in path.read_text()


def test_one_response_per_report():
    assert sorted(p.stem for p in oracle.OUT.glob("*.json")) == REPORTS


@pytest.mark.parametrize("report", REPORTS)
def test_committed_responses_match_a_fresh_run(report):
    # Catches a render spec regenerated without rerunning the oracle.
    committed = (oracle.OUT / f"{report}.json").read_text()
    assert Response.model_validate_json(committed).report == oracle.extract(
        spec(report)
    )
