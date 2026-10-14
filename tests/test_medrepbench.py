import hashlib

import pytest

from bench import medrepbench


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
