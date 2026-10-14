import hashlib
import json
import re

import pandas as pd
import pytest

from bench import medrepbench
from lab2clock.clock_spec import MARKERS


@pytest.fixture
def served(monkeypatch):
    """A stand-in for Hugging Face: serves these bytes by URL, counting calls."""
    files, calls = {}, []

    def download(url, path):
        calls.append(url)
        path.write_bytes(files[url])

    monkeypatch.setattr(medrepbench, "_download", download)
    return files, calls


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def test_a_file_is_fetched_from_the_pinned_revision_and_checked(tmp_path, served):
    files, calls = served
    url = f"{medrepbench.FILES}/censored/a.png"
    files[url] = b"report"
    path = medrepbench.image("a.png", sha256(b"report"), tmp_path)
    assert path.read_bytes() == b"report"
    assert calls == [url]
    assert medrepbench.REVISION in url


def test_a_cached_file_is_checked_but_not_fetched_again(tmp_path, served):
    files, calls = served
    files[f"{medrepbench.FILES}/censored/a.png"] = b"report"
    medrepbench.image("a.png", sha256(b"report"), tmp_path)
    medrepbench.image("a.png", sha256(b"report"), tmp_path)
    assert len(calls) == 1


def test_a_file_that_does_not_match_its_hash_is_deleted(tmp_path, served):
    files, _ = served
    files[f"{medrepbench.FILES}/censored/a.png"] = b"tampered"
    with pytest.raises(ValueError, match="expected"):
        medrepbench.image("a.png", sha256(b"report"), tmp_path)
    assert not (tmp_path / "censored" / "a.png").exists()


def test_an_empty_image_is_refused_without_fetching(tmp_path, served):
    _, calls = served
    with pytest.raises(ValueError, match="empty file"):
        medrepbench.image("b.png", medrepbench.EMPTY_SHA256, tmp_path)
    assert calls == []


def test_the_labels_are_pinned_by_hash(tmp_path, served):
    files, _ = served
    files[f"{medrepbench.FILES}/{medrepbench.LABELS}"] = b"not the labels"
    with pytest.raises(ValueError, match=medrepbench.LABELS_SHA256):
        medrepbench.labels(tmp_path)


def test_the_data_is_kept_where_git_ignores_it():
    root = medrepbench.CACHE.parent.parent.parent
    ignored = (root / ".gitignore").read_text().splitlines()
    assert medrepbench.CACHE.relative_to(root).parts[:2] == ("bench", "data")
    assert "bench/data/" in ignored


# The scored set.


def items(*names_units):
    return json.dumps(
        [
            {
                "item_name": n,
                "item_value": "1",
                "item_unit": u,
                "item_range": "",
                "is_abnormal": "0",
            }
            for n, u in names_units
        ],
        ensure_ascii=False,
    )


def test_markers_are_mapped_by_the_core_dictionary_in_clock_order():
    report = items(
        ("白细胞计数", "10^9/L"),
        ("白蛋白", "g/L"),
        ("前白蛋白", "mg/L"),
        ("淋巴细胞", ""),
    )
    # Prealbumin is a lookalike, and a lymphocyte row without a unit could be
    # the count or the percent, so neither maps.
    assert medrepbench.markers(report) == ["albumin", "white_blood_cell_count"]


def test_a_report_needs_three_markers_and_an_image():
    three = items(("白蛋白", "g/L"), ("肌酐", "umol/L"), ("葡萄糖", "mmol/L"))
    two = items(("白蛋白", "g/L"), ("肌酐", "umol/L"))
    labelled = pd.DataFrame(
        {
            "image": ["b.png", "a.png", "empty.png", "few.png"],
            "items": [three, three, three, two],
        }
    )
    hashes = {
        "a.png": "aa",
        "b.png": "bb",
        "empty.png": medrepbench.EMPTY_SHA256,
        "few.png": "ff",
    }
    chosen = medrepbench.eligible(labelled, hashes)
    assert list(chosen["image"]) == ["a.png", "b.png"]
    assert list(chosen["sha256"]) == ["aa", "bb"]
    assert set(chosen["markers"]) == {"albumin;creatinine;glucose"}


def test_the_committed_set_is_every_eligible_report():
    rows = medrepbench.read_set()
    assert len(rows) == 39
    images = [row["image"] for row in rows]
    assert images == sorted(set(images))
    for row in rows:
        found = row["markers"].split(";")
        assert len(found) >= medrepbench.MIN_MARKERS
        assert set(found) <= set(MARKERS)
        assert re.fullmatch("[0-9a-f]{64}", row["sha256"])
        assert row["sha256"] != medrepbench.EMPTY_SHA256


def test_the_held_out_set_is_apart_from_the_scored_set():
    held = medrepbench.read_set(medrepbench.HELDOUT)
    scored = {row["image"] for row in medrepbench.read_set()}
    assert held and not scored & {row["image"] for row in held}
    assert [row["report"] for row in held] == [
        f"H{i:03d}" for i in range(1, len(held) + 1)
    ]
    for row in held:
        assert row["markers"] and set(row["markers"].split(";")) <= set(MARKERS)
        assert row["sha256"] != medrepbench.EMPTY_SHA256


def test_every_held_out_report_has_labelled_rows():
    held = {row["report"] for row in medrepbench.read_set(medrepbench.HELDOUT)}
    assert set(medrepbench.read_labelled(medrepbench.HELDOUT_LABELLED)) == held
