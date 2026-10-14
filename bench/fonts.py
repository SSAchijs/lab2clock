"""Noto Sans SC, the font the Chinese reports are printed in.

Without an embedded CJK font a headless browser prints Chinese as empty boxes,
or borrows whatever system font it finds, so a PDF would differ between a Mac
and CI. The Chinese templates load these files through @font-face and the
browser embeds them in the PDF.

The files are the Simplified Chinese subset OTFs of the noto-cjk Sans2.004
release, under the SIL Open Font License. Downloads are cached in
bench/data/fonts/ and checked against a SHA-256. Needs network access to
github.com on the first run:

    uv run python -m bench.fonts
"""

import hashlib
import urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "data" / "fonts"

FAMILY = "Noto Sans SC"

BASE_URL = "https://github.com/notofonts/noto-cjk/raw/Sans2.004/Sans/SubsetOTF/SC"

# CSS font-weight -> file name and SHA-256, as downloaded on 14 October 2026.
FILES: dict[int, tuple[str, str]] = {
    400: (
        "NotoSansSC-Regular.otf",
        "faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9",
    ),
    700: (
        "NotoSansSC-Bold.otf",
        "c6cb5a93abaa9edc8ee7463b7ebb7f42d618d40e6ed2f7a5371c97b0b64767c0",
    ),
}


def download(weight: int, cache: Path = CACHE) -> Path:
    """Return the cached font file for `weight`, downloading it first if needed."""
    name, expected = FILES[weight]
    path = cache / name
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(f"{BASE_URL}/{name}", tmp)
        tmp.rename(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError(
            f"{path} has SHA-256 {digest}, expected {expected}. "
            "Delete it to download it again."
        )
    return path


def main() -> None:
    for weight in FILES:
        print(download(weight))


if __name__ == "__main__":
    main()
