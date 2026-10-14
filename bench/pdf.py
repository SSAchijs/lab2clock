"""Print each HTML report to PDF with Playwright's headless Chromium.

The browser that lays out the HTML also prints it, so the PDF has the same CSS
and fonts as the page you open to eyeball it. The page size comes from each
report's own @page rule (Letter or A4), and backgrounds are printed so the
header and panel bars look as they do on screen.

Each report is opened from its file, not passed in as a string, so the
relative URLs of the embedded Chinese font resolve. Before printing, every
font the page declares is loaded, and a font that fails to load stops the run
instead of letting the browser fall back to a system font.

Needs Chromium once: uv run playwright install chromium. Then

    uv run python -m bench.pdf

renders every report to HTML, prints bench/data/reports/R01.pdf and so on, and
runs bench.selfcheck on the result.
"""

from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from bench import render, selfcheck

# Loads every declared font face and resolves to the families that failed.
LOAD_FONTS = """
async () => {
  const faces = [...document.fonts];
  const results = await Promise.allSettled(faces.map((face) => face.load()));
  return faces
    .filter((face, i) => results[i].status === "rejected")
    .map((face) => `${face.family} ${face.weight}`);
}
"""


def print_pdf(page: Page, html: Path, pdf: Path) -> Path:
    """Print the report at `html` to `pdf` in the browser tab `page`."""
    page.goto(html.resolve().as_uri())
    failed = page.evaluate(LOAD_FONTS)
    if failed:
        raise RuntimeError(f"{html.name}: fonts failed to load: {', '.join(failed)}")
    page.pdf(path=pdf, prefer_css_page_size=True, print_background=True)
    return pdf


def main() -> None:
    htmls = render.main()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for html in htmls:
            print_pdf(page, html, html.with_suffix(".pdf"))
        browser.close()
    print(f"printed {len(htmls)} PDFs to {render.OUT}")
    selfcheck.main()


if __name__ == "__main__":
    main()
