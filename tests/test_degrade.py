import cv2
import numpy as np
import pytest

from bench.degrade import MARGIN, Steps, degrade, desk, draw, photograph

# A small white page with black bars, as a raster page with printed rows.
PAGE = np.full((220, 170, 3), 255, np.uint8)
PAGE[40:48, 20:150] = 0
PAGE[80:88, 20:150] = 0


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "R99-1.png"
    cv2.imwrite(str(path), PAGE)
    return path


def decode(jpeg: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def test_the_same_seed_and_page_give_the_same_photo(png):
    assert degrade(png, 7, 1) == degrade(png, 7, 1)


def test_each_page_and_seed_is_photographed_differently(png):
    first, steps = degrade(png, 7, 1)
    assert degrade(png, 7, 2)[1] != steps
    assert degrade(png, 8, 1)[1] != steps
    assert degrade(png, 7, 2)[0] != first


@pytest.mark.parametrize("seed", range(50))
def test_steps_stay_in_their_legible_ranges(seed):
    s = draw(np.random.default_rng([seed, 1]))
    assert -3 <= s.angle <= 3
    assert all(abs(x) <= 0.03 and abs(y) <= 0.03 for x, y in s.slant)
    assert 0.62 <= s.light_floor <= 0.85
    assert 0.6 <= s.blur <= 1.3
    assert 2 <= s.noise <= 5
    assert 55 <= s.quality <= 80


@pytest.mark.parametrize("seed", range(50))
def test_the_desk_is_grey_or_warm(seed):
    blue, green, red = desk(np.random.default_rng(seed))
    assert blue <= green <= red <= blue + 25


def test_the_photo_shows_the_page_on_a_desk(png):
    jpeg, steps = degrade(png, 7, 1)
    image = decode(jpeg)
    pad = round(MARGIN * PAGE.shape[1])
    assert image.shape == (PAGE.shape[0] + 2 * pad, PAGE.shape[1] + 2 * pad, 3)
    # A corner is desk; the middle is lit paper, brighter than the desk.
    assert np.abs(image[0, 0].astype(int) - steps.desk).max() <= 20
    middle = image[image.shape[0] // 2, image.shape[1] // 2]
    assert middle.mean() > np.mean(steps.desk) + 60


def test_printed_rows_stay_dark_on_light_paper():
    steps = Steps(
        angle=0.0,
        slant=((0.0, 0.0),) * 4,
        desk=(80, 80, 80),
        light_floor=0.62,
        light_direction=0.0,
        warmth=(0.86, 0.94),
        blur=1.3,
        noise=5.0,
        quality=55,
    )
    image = decode(photograph(PAGE, steps, np.random.default_rng(0)))
    pad = round(MARGIN * PAGE.shape[1])
    row = image[pad + 44, pad + 30 : pad + 140].mean()
    paper = image[pad + 64, pad + 30 : pad + 140].mean()
    # At the harshest end of every range, ink and paper stay far apart.
    assert paper - row > 100


def test_a_missing_page_image_says_what_to_run(tmp_path):
    with pytest.raises(FileNotFoundError, match="bench.raster"):
        degrade(tmp_path / "R99-1.png", 7, 1)
