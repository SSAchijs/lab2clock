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

The scored set is every labelled report that prints at least three of the
nine clock markers, as the core's synonym dictionary maps its item names, and
whose image is not empty. Fewer markers would give too little clock-relevant
data per call. At this revision that is 39 reports, all of them, so nothing is
left to sample: the set follows from the labels, the dictionary and the
revision alone. bench/medrepbench.csv fixes it, committed: each report's ID,
image name, the image's SHA-256 and the markers it prints. Its labelled marker
rows, name, value and unit, are committed in bench/medrepbench_labels.csv, so
the real set is scored, and rescored in CI, without the dataset. Both files
are derived from MedRepBench and are CC BY-NC 4.0.

    uv run python -m bench.medrepbench select

rebuilds that file from the labels, and

    uv run python -m bench.medrepbench

fetches the labels and every image in it, each checked against its hash.
"""

import csv
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

from lab2clock.clock_spec import MARKERS
from lab2clock.synonyms import match

REPO = "MedRepBench/MedRepBench"
REVISION = "e7f968085012e6760895c531cedf344f812e54ff"
FILES = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}"
API = f"https://huggingface.co/api/datasets/{REPO}/paths-info/{REVISION}"

CACHE = Path(__file__).resolve().parent / "data" / "medrepbench"

LABELS = "datasets-meta-zhCN.csv"
LABELS_SHA256 = "f918df98f68124fe344641aa7e986ec596e1d1078d61a2fc05fe2755b13a9fba"

# The scored reports, committed.
SET = Path(__file__).resolve().parent / "medrepbench.csv"

# Their labelled marker rows, committed, so the real set is scored without
# the dataset.
LABELLED = Path(__file__).resolve().parent / "medrepbench_labels.csv"

# The hand check of 10 reports' labels; see bench.audit.
AUDIT = Path(__file__).resolve().parent / "medrepbench_audit.csv"

# A report is scored only if it prints at least this many clock markers.
MIN_MARKERS = 3

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


def marker_rows(items: str) -> list[dict[str, str]]:
    """Every labelled row that maps to a clock marker, in printed order."""
    rows = []
    for item in json.loads(items):
        unit = item["item_unit"] or None
        marker = match(item["item_name"], unit)
        if marker in MARKERS:
            rows.append(
                {
                    "marker": marker,
                    "name": item["item_name"],
                    "value": item["item_value"],
                    "unit": item["item_unit"] or "",
                }
            )
    return rows


def markers(items: str) -> list[str]:
    """The clock markers a report's labelled items map to, in clock order."""
    found = {row["marker"] for row in marker_rows(items)}
    return [marker for marker in MARKERS if marker in found]


def eligible(labelled: pd.DataFrame, hashes: dict[str, str]) -> pd.DataFrame:
    """Every labelled report with enough markers and an image to read, each
    given an ID, M01 onwards, in image order."""
    rows = []
    for image, items in zip(labelled["image"], labelled["items"], strict=True):
        found = markers(items)
        if len(found) >= MIN_MARKERS and hashes[image] != EMPTY_SHA256:
            rows.append(
                {"image": image, "sha256": hashes[image], "markers": ";".join(found)}
            )
    chosen = pd.DataFrame(rows).sort_values("image", ignore_index=True)
    chosen.insert(0, "report", [f"M{i:02d}" for i in range(1, len(chosen) + 1)])
    return chosen


def labelled_rows(labelled: pd.DataFrame, chosen: pd.DataFrame) -> pd.DataFrame:
    """The marker rows of every chosen report, as labelled, in printed order."""
    items = labelled.set_index("image")["items"]
    rows = [
        {"report": report, "image": image, **row}
        for report, image in zip(chosen["report"], chosen["image"], strict=True)
        for row in marker_rows(items[image])
    ]
    return pd.DataFrame(rows)


def select(cache: Path = CACHE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The scored reports, and their labelled marker rows."""
    labelled = pd.read_csv(labels(cache)).dropna(subset=["items"])
    names = list(labelled["image"])
    hashes = {}
    for start in range(0, len(names), 400):
        hashes |= published(names[start : start + 400])
    chosen = eligible(labelled, hashes)
    return chosen, labelled_rows(labelled, chosen)


def read_set(path: Path = SET) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def read_labelled(path: Path = LABELLED) -> dict[str, list[dict[str, str]]]:
    """Per report ID, its labelled marker rows in printed order."""
    out: dict[str, list[dict[str, str]]] = {}
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            out.setdefault(row["report"], []).append(row)
    return out


def read_audit(path: Path = AUDIT) -> list[dict[str, str]]:
    """The hand check's rows: each label, its verdict and what is printed."""
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def main() -> None:
    if sys.argv[1:] == ["select"]:
        chosen, rows = select()
        chosen.to_csv(SET, index=False, lineterminator="\n")
        rows.to_csv(LABELLED, index=False, lineterminator="\n")
        print(f"wrote {len(chosen)} reports to {SET}, {len(rows)} rows to {LABELLED}")
    elif sys.argv[1:]:
        raise SystemExit("usage: python -m bench.medrepbench [select]")
    print(f"labels: {labels()}")
    chosen = read_set()
    for row in chosen:
        image(row["image"], row["sha256"])
    print(f"{len(chosen)} images in {CACHE / 'censored'}")


if __name__ == "__main__":
    main()
