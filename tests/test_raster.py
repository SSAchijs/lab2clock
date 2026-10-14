import pymupdf
import pytest

from bench.raster import DPI, rasterise

LETTER = (612, 792)


@pytest.fixture
def pdf(tmp_path):
    """A two-page Letter PDF with a value printed on each page."""
    path = tmp_path / "R99.pdf"
    with pymupdf.open() as doc:
        for value in ("4.85", "19.3"):
            page = doc.new_page(width=LETTER[0], height=LETTER[1])
            page.insert_text((72, 72), value, fontsize=12)
        doc.save(path)
    return path


def test_writes_one_png_per_page_numbered_from_one(pdf, tmp_path):
    out = tmp_path / "images"
    assert rasterise(pdf, out) == [out / "R99-1.png", out / "R99-2.png"]


def test_pages_are_opaque_at_the_chosen_dpi(pdf, tmp_path):
    for path in rasterise(pdf, tmp_path / "images"):
        image = pymupdf.Pixmap(path)
        assert (image.width, image.height) == (
            LETTER[0] * DPI // 72,
            LETTER[1] * DPI // 72,
        )
        assert image.alpha == 0
        # Paper stays white: the corner pixel has no ink.
        assert image.pixel(0, 0) == (255, 255, 255)


def test_the_same_pdf_gives_the_same_bytes(pdf, tmp_path):
    first = [p.read_bytes() for p in rasterise(pdf, tmp_path / "a")]
    second = [p.read_bytes() for p in rasterise(pdf, tmp_path / "b")]
    assert first == second


def test_each_page_shows_its_own_text(pdf, tmp_path):
    # Different pages, different pixels: page 2 is not a copy of page 1.
    one, two = rasterise(pdf, tmp_path / "images")
    assert one.read_bytes() != two.read_bytes()
