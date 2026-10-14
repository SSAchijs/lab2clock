"""Rasterise each report's PDF to one PNG per page, with PyMuPDF.

The images are the starting point for the photo-degraded reports, and the
image arm of the PDF-versus-image experiment, so both see exactly the pixels
of the printed PDF.

200 DPI: the smallest printed text, the 7.5pt reference intervals, comes out
about 21 pixels tall, readable with room to spare once a photo blurs and
shrinks it. A Letter page is 1700 by 2200 pixels, an A4 page 1653 by 2339.
Pages are rendered without an alpha channel, on white as on paper, and the
same PDF always gives the same bytes.

Needs the PDFs from bench.pdf. Then

    uv run python -m bench.raster

writes bench/data/images/R01-1.png, R03-1.png, R03-2.png and so on, one per
page, numbered from 1.
"""

from pathlib import Path

import pymupdf

from bench import render
from bench.spec import RENDER_SPEC

OUT = render.OUT.parent / "images"

DPI = 200


def rasterise(pdf: Path, out: Path, dpi: int = DPI) -> list[Path]:
    """Write each page of `pdf` to `out` as <stem>-<page>.png; return the paths."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    with pymupdf.open(pdf) as doc:
        for number, page in enumerate(doc, start=1):
            path = out / f"{pdf.stem}-{number}.png"
            page.get_pixmap(dpi=dpi, alpha=False).save(path)
            written.append(path)
    return written


def main() -> None:
    reports = sorted(path.stem for path in RENDER_SPEC.glob("*.json"))
    written = []
    for report in reports:
        pdf = render.OUT / f"{report}.pdf"
        if not pdf.exists():
            raise FileNotFoundError(f"{pdf} is missing; run bench.pdf first")
        written += rasterise(pdf, OUT)
    print(f"wrote {len(written)} pages of {len(reports)} reports to {OUT}")


if __name__ == "__main__":
    main()
