"""MedRepBench: real Chinese lab report images, fetched from Hugging Face.

MedRepBench (arXiv 2508.16674) publishes 1,925 de-identified Chinese medical
report images with the items printed on each: name, value, unit, reference
range and abnormal flag. Its labels record what was printed, which is exactly
stage 1's contract, so it scores stage 1 on real reports.

The dataset is licensed CC BY-NC 4.0, so it is never committed: redistributing
it inside this MIT repository would muddy the licensing, and a script is
enough to reproduce it. This module fetches it into bench/data/medrepbench/,
which git ignores, from one pinned revision, so the same files come back
every time:

- the labels, datasets-meta-zhCN.csv, checked against the SHA-256 below.
- report images by name, each checked against the SHA-256 Hugging Face
  publishes for it at that revision. The images total 2 GB, so only the ones
  scored are fetched.

At this revision 387 of the images are empty files, 133 of them with labels.
Fetching one fails, since there is nothing on it to read.

    uv run python -m bench.medrepbench [IMAGE ...]

fetches the labels, and the named images if any.
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO = "MedRepBench/MedRepBench"
REVISION = "e7f968085012e6760895c531cedf344f812e54ff"
FILES = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}"
API = f"https://huggingface.co/api/datasets/{REPO}/paths-info/{REVISION}"

CACHE = Path(__file__).resolve().parent / "data" / "medrepbench"

LABELS = "datasets-meta-zhCN.csv"
LABELS_SHA256 = "f918df98f68124fe344641aa7e986ec596e1d1078d61a2fc05fe2755b13a9fba"

# The SHA-256 of zero bytes, which Hugging Face lists for an empty image.
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download(url: str, path: Path) -> None:
    urllib.request.urlretrieve(url, path)


def fetch(name: str, sha256: str, cache: Path = CACHE) -> Path:
    """The file `name` of the dataset, downloaded unless already cached, and
    checked against `sha256` either way."""
    path = cache / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        _download(f"{FILES}/{name}", part)
        part.rename(path)
    digest = _sha256(path)
    if digest != sha256:
        path.unlink()
        raise ValueError(f"{name} has SHA-256 {digest}, expected {sha256}")
    return path


def labels(cache: Path = CACHE) -> Path:
    return fetch(LABELS, LABELS_SHA256, cache)


def published(images: list[str]) -> dict[str, str]:
    """The SHA-256 Hugging Face publishes for each image at the revision."""
    paths = [f"censored/{image}" for image in images]
    request = urllib.request.Request(
        API,
        data=json.dumps({"paths": paths, "expand": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        info = json.load(response)
    hashes = {
        item["path"].removeprefix("censored/"): item["lfs"]["oid"] for item in info
    }
    if missing := set(images) - set(hashes):
        raise ValueError(f"not in MedRepBench at {REVISION}: {sorted(missing)}")
    return hashes


def image(name: str, sha256: str, cache: Path = CACHE) -> Path:
    """One report image, refused if the dataset holds an empty file for it."""
    if sha256 == EMPTY_SHA256:
        raise ValueError(f"{name} is an empty file at {REVISION}; nothing to read")
    return fetch(f"censored/{name}", sha256, cache)


def main() -> None:
    print(f"labels: {labels()}")
    names = sys.argv[1:]
    for name, sha256 in published(names).items():
        print(f"image: {image(name, sha256)}")


if __name__ == "__main__":
    main()
