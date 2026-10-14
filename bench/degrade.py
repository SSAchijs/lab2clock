"""Degrade the photo reports' page images to look like phone photos, with OpenCV.

Each step follows a phone photo of a printed page, in the order it happens:
the page lies on a desk, the camera sees it turned and at a slant
(perspective warp), the room lights it unevenly and warmly, the lens blurs
it, the sensor adds noise, and the phone saves a JPEG.

Every step is drawn from the report's degradation seed in its render spec,
with the page number, so the same seed always gives the same photo and each
page of a multi-page report is photographed differently. The ranges keep
every value legible: the reader should struggle as with a real photo, not
face an unreadable page.

Needs the page images from bench.raster. Then

    uv run python -m bench.degrade

writes bench/data/photos/R05-1.jpg and so on for every report with photo set,
plus steps.json with the steps drawn for each page.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from bench import raster
from bench.spec import RENDER_SPEC, RenderSpec

OUT = raster.OUT.parent / "photos"

# Desk visible around the page, as a fraction of the page's width.
MARGIN = 0.08


@dataclass(frozen=True)
class Steps:
    """The degradation drawn for one page.

    angle: rotation in degrees, positive anticlockwise.
    slant: each page corner's shift, as a fraction of the page's width, in
        the order top left, top right, bottom right, bottom left.
    desk: the desk's colour, BGR.
    light_floor: the dimmest light across the page, as a fraction of full.
    light_direction: where the light falls off towards, in degrees.
    warmth: the light's blue and green channels, as a fraction of red.
    blur: the lens blur's Gaussian sigma, in pixels at raster.DPI.
    noise: the sensor noise's standard deviation, in 8-bit levels.
    quality: the JPEG quality.
    """

    angle: float
    slant: tuple[tuple[float, float], ...]
    desk: tuple[int, int, int]
    light_floor: float
    light_direction: float
    warmth: tuple[float, float]
    blur: float
    noise: float
    quality: int


def desk(rng: np.random.Generator) -> tuple[int, int, int]:
    """A grey to brown desk, BGR: one grey level, warmed towards red."""
    grey = int(rng.integers(45, 120))
    warm = int(rng.integers(0, 25))
    return (grey, grey + warm // 2, grey + warm)


def draw(rng: np.random.Generator) -> Steps:
    """Draw one page's degradation."""
    return Steps(
        angle=round(float(rng.uniform(-3, 3)), 2),
        slant=tuple(
            (round(float(x), 4), round(float(y), 4))
            for x, y in rng.uniform(-0.03, 0.03, size=(4, 2))
        ),
        desk=desk(rng),
        light_floor=round(float(rng.uniform(0.62, 0.85)), 3),
        light_direction=round(float(rng.uniform(0, 360)), 1),
        warmth=(
            round(float(rng.uniform(0.86, 0.95)), 3),
            round(float(rng.uniform(0.94, 0.99)), 3),
        ),
        blur=round(float(rng.uniform(0.6, 1.3)), 2),
        noise=round(float(rng.uniform(2, 5)), 2),
        quality=int(rng.integers(55, 81)),
    )


def photograph(page: np.ndarray, steps: Steps, rng: np.random.Generator) -> bytes:
    """The JPEG of `page` (BGR, 8-bit) after `steps`; `rng` draws the noise."""
    h, w = page.shape[:2]
    pad = round(MARGIN * w)
    size = (w + 2 * pad, h + 2 * pad)

    # The page on the desk, turned and slanted.
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    placed = corners + pad + np.float32(steps.slant) * w
    centre = (size[0] / 2, size[1] / 2)
    turn = cv2.getRotationMatrix2D(centre, steps.angle, 1.0)
    placed = cv2.transform(placed[None], turn)[0].astype(np.float32)
    warp = cv2.getPerspectiveTransform(corners, placed)
    image = cv2.warpPerspective(
        page,
        warp,
        size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=steps.desk,
    ).astype(np.float32)

    # Uneven, warm light: a linear fall-off towards one side, and a vignette.
    ys, xs = np.mgrid[0 : size[1], 0 : size[0]].astype(np.float32)
    xs = (xs - centre[0]) / size[0]
    ys = (ys - centre[1]) / size[1]
    theta = np.deg2rad(steps.light_direction)
    along = xs * np.cos(theta) + ys * np.sin(theta)
    along = (along - along.min()) / (along.max() - along.min())
    light = 1 - (1 - steps.light_floor) * along
    light *= 1 - 0.25 * (xs**2 + ys**2)
    tint = np.float32([steps.warmth[0], steps.warmth[1], 1.0])
    image *= light[..., None] * tint

    # The lens, then the sensor.
    image = cv2.GaussianBlur(image, (0, 0), steps.blur)
    image += rng.normal(0, steps.noise, size=image.shape).astype(np.float32)

    image = np.clip(np.rint(image), 0, 255).astype(np.uint8)
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, steps.quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return jpeg.tobytes()


def degrade(png: Path, seed: int, page: int) -> tuple[bytes, Steps]:
    """The photo of the page image `png`, page `page` of a report with `seed`."""
    rng = np.random.default_rng([seed, page])
    steps = draw(rng)
    image = cv2.imread(str(png), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"{png} is missing; run bench.raster first")
    return photograph(image, steps, rng), steps


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log = {}
    for path in sorted(RENDER_SPEC.glob("*.json")):
        spec = RenderSpec.model_validate_json(path.read_text())
        if spec.degradation is None:
            continue
        pages = sorted({row.page for row in spec.rows})
        for page in pages:
            name = f"{spec.report}-{page}"
            jpeg, steps = degrade(
                raster.OUT / f"{name}.png", spec.degradation.seed, page
            )
            (OUT / f"{name}.jpg").write_bytes(jpeg)
            log[name] = asdict(steps)
    (OUT / "steps.json").write_text(json.dumps(log, indent=2) + "\n")
    print(f"wrote {len(log)} photos to {OUT}")


if __name__ == "__main__":
    main()
