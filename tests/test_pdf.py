import re

import pytest
from conftest import load_spec, reports_dir

from bench.pdf import print_pdf
from bench.render import render_html

# Points per page side: US letter and A4.
LETTER = (612.0, 792.0)
A4 = (595.0, 842.0)


def media_boxes(pdf: bytes) -> list[tuple[float, float]]:
    """Each page's width and height. Chromium writes one MediaBox per page."""
    boxes = re.findall(rb"/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", pdf)
    return [(round(float(w)), round(float(h))) for w, h in boxes]


@pytest.fixture
def reports(tmp_path):
    return reports_dir(tmp_path)


@pytest.mark.parametrize(
    ("report", "size"),
    [("R01", LETTER), ("R03", LETTER), ("R04", A4), ("R14", A4)],
)
def test_prints_each_page_at_the_report_size(page, reports, report, size):
    s = load_spec(report)
    html = reports / f"{report}.html"
    html.write_text(render_html(s))
    pdf = print_pdf(page, html, reports / f"{report}.pdf")
    pages = len({row.page for row in s.rows})
    assert media_boxes(pdf.read_bytes()) == [size] * pages


def test_a_font_that_fails_to_load_stops_the_print(page, tmp_path):
    # No fonts directory beside the report, so the Chinese font cannot load.
    html = tmp_path / "R04.html"
    html.write_text(render_html(load_spec("R04")))
    with pytest.raises(RuntimeError, match="Noto Sans SC"):
        print_pdf(page, html, tmp_path / "R04.pdf")
    assert not (tmp_path / "R04.pdf").exists()
