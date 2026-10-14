from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from bench import fonts
from bench.pdf import print_pdf
from bench.render import render_html
from bench.spec import RENDER_SPEC, RenderSpec

# Printed once per session: every layout, both languages, previous columns.
PRINTED = ("R01", "R02", "R04", "R07", "R08")


def load_spec(report: str) -> RenderSpec:
    return RenderSpec.model_validate_json((RENDER_SPEC / f"{report}.json").read_text())


def reports_dir(root: Path) -> Path:
    """A reports directory beside a fonts directory, as in bench/data."""
    out = root / "reports"
    out.mkdir()
    (root / "fonts").mkdir()
    for weight in fonts.FILES:
        cached = fonts.download(weight)
        (root / "fonts" / cached.name).symlink_to(cached)
    return out


@pytest.fixture(scope="session")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser.new_page()
        browser.close()


@pytest.fixture(scope="session")
def printed(page, tmp_path_factory) -> Path:
    """The PRINTED reports as PDFs, printed with the embedded font."""
    out = reports_dir(tmp_path_factory.mktemp("printed"))
    for report in PRINTED:
        html = out / f"{report}.html"
        html.write_text(render_html(load_spec(report)))
        print_pdf(page, html, out / f"{report}.pdf")
    return out
