from html.parser import HTMLParser

import pytest

from bench.render import LABELS, day, render_html
from bench.spec import RENDER_SPEC, RenderSpec

SPECS = [
    RenderSpec.model_validate_json(path.read_text())
    for path in sorted(RENDER_SPEC.glob("*.json"))
]
# Chinese reports wait for the Chinese template.
RENDERED = [spec for spec in SPECS if spec.conditions.language in LABELS]


class Rows(HTMLParser):
    """Collects the text of every element with data-row, and counts pages."""

    def __init__(self):
        super().__init__()
        self.rows: dict[int, list[str]] = {}
        self.pages = 0
        self._stack: list[int | None] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "page" in (attrs.get("class") or "").split():
            self.pages += 1
        if "data-row" in attrs:
            self._stack.append(int(attrs["data-row"]))
            self.rows[self._stack[-1]] = []
        else:
            self._stack.append(None)

    def handle_endtag(self, tag):
        self._stack.pop()

    def handle_data(self, data):
        for row in self._stack:
            if row is not None and data.strip():
                self.rows[row].append(data.strip())


def parse(spec: RenderSpec) -> Rows:
    parser = Rows()
    parser.feed(render_html(spec))
    return parser


@pytest.mark.parametrize("spec", RENDERED, ids=lambda s: s.report)
def test_every_row_prints_its_strings_in_its_own_row(spec):
    printed = parse(spec).rows
    assert sorted(printed) == list(range(len(spec.rows)))
    for i, row in enumerate(spec.rows):
        text = " ".join(printed[i])
        for expected in (row.name, row.value, row.unit, row.reference):
            assert expected in text, (row.name, expected)
        if row.flag:
            assert row.flag in printed[i] or f"{row.value} {row.flag}" in printed[i]
        if row.previous:
            assert row.previous in printed[i]


@pytest.mark.parametrize("spec", RENDERED, ids=lambda s: s.report)
def test_one_page_per_printed_page(spec):
    assert parse(spec).pages == len({row.page for row in spec.rows})


@pytest.mark.parametrize("spec", RENDERED, ids=lambda s: s.report)
def test_the_header_prints_the_identity(spec):
    html = render_html(spec)
    who = spec.identity
    t = LABELS[spec.conditions.language]
    for text in (who.name, who.patient_id, who.specimen_id, who.physician):
        assert text in html
    assert day(who.date_of_birth, t) in html
    if spec.previous_collected:
        assert day(spec.previous_collected, t) in html


def test_two_column_prints_the_flag_in_the_result_cell():
    spec = next(
        s
        for s in RENDERED
        if s.conditions.layout == "two_column" and any(r.flag for r in s.rows)
    )
    printed = parse(spec).rows
    i, row = next((i, r) for i, r in enumerate(spec.rows) if r.flag)
    assert f"{row.value} {row.flag}" in printed[i]
    # And the perfect reader's value says the same.
    assert spec.stage1().items[i].value == f"{row.value} {row.flag}"


def test_every_layout_is_rendered():
    assert {s.conditions.layout for s in RENDERED} == {
        "table",
        "two_column",
        "multi_page",
    }
