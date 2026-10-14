import hashlib

import pandas as pd
import pytest

from bench import nhanes
from bench.nhanes import FILES, REQUIRED, UNITS, VARIABLES, build, download
from lab2clock.clock_spec import FIELD_NAMES

# A complete adult, in NHANES units.
ADULT = {
    "RIDAGEYR": 52.0,
    "LBXSAL": 4.2,
    "LBXSCR": 0.9,
    "LBXSGL": 95.0,
    "LBXHSCRP": 1.8,
    "LBXLYPCT": 30.1,
    "LBXMCVSI": 89.0,
    "LBXRDW": 13.4,
    "LBXSAPSI": 70.0,
    "LBXWBCSI": 6.5,
    "LBDSALSI": 42.0,
    "LBDSCRSI": 79.56,
    "LBDSGLSI": 5.27,
    "LBDHRPLC": 0.0,
}


def frames(rows: dict[int, dict[str, float]]) -> dict[str, pd.DataFrame]:
    """Split respondents, keyed by SEQN, into the four files they come from."""
    out = {}
    for stem in FILES:
        names = [v.nhanes for v in VARIABLES if v.file == stem]
        out[stem] = pd.DataFrame(
            {seqn: {n: row[n] for n in names if n in row} for seqn, row in rows.items()}
        ).T.reindex(columns=names)
    return out


def test_every_clock_field_has_a_column():
    assert set(FIELD_NAMES) <= set(UNITS)
    assert set(REQUIRED) == set(FIELD_NAMES)


def test_every_variable_comes_from_a_known_file():
    assert {v.file for v in VARIABLES} == set(FILES)


def test_keeps_a_complete_adult_with_renamed_columns():
    table = build(frames({1: ADULT}))
    assert list(table.columns) == list(UNITS)
    assert table.index.name == "SEQN"
    row = table.loc[1]
    assert row["age"] == 52
    assert row["c_reactive_protein"] == 1.8
    assert row["white_blood_cell_count"] == 6.5
    assert not row["crp_below_lod"]


def test_drops_children():
    table = build(frames({1: ADULT, 2: {**ADULT, "RIDAGEYR": 19.0}}))
    assert list(table.index) == [1]


@pytest.mark.parametrize("missing", ["LBXSCR", "LBXHSCRP", "LBXRDW", "RIDAGEYR"])
def test_drops_a_respondent_missing_any_clock_input(missing):
    incomplete = {k: v for k, v in ADULT.items() if k != missing}
    table = build(frames({1: ADULT, 2: incomplete}))
    assert list(table.index) == [1]


def test_drops_a_respondent_absent_from_one_file():
    fs = frames({1: ADULT, 2: ADULT})
    fs["HSCRP_J"] = fs["HSCRP_J"].drop(index=2)
    assert list(build(fs).index) == [1]


def test_flags_crp_below_detection():
    filled = {**ADULT, "LBXHSCRP": 0.11, "LBDHRPLC": 1.0}
    assert build(frames({1: filled})).loc[1, "crp_below_lod"]


def test_restores_sas_zeros(tmp_path, monkeypatch):
    # pandas reads a SAS transport 0 as about 5.4e-79.
    df = pd.DataFrame({"SEQN": [1.0], "LBDHRPLC": [5.397605e-79]})
    monkeypatch.setattr(nhanes, "download", lambda stem, cache: tmp_path)
    monkeypatch.setattr(pd, "read_sas", lambda *a, **k: df.set_index("SEQN"))
    assert nhanes.read("HSCRP_J", tmp_path).loc[1, "LBDHRPLC"] == 0


def test_download_rejects_a_changed_file(tmp_path):
    (tmp_path / "CBC_J.xpt").write_bytes(b"revised")
    with pytest.raises(ValueError, match="SHA-256"):
        download("CBC_J", tmp_path)


def test_download_reuses_a_cached_file(tmp_path, monkeypatch):
    content = b"cached"
    (tmp_path / "CBC_J.xpt").write_bytes(content)
    monkeypatch.setitem(FILES, "CBC_J", hashlib.sha256(content).hexdigest())
    assert download("CBC_J", tmp_path) == tmp_path / "CBC_J.xpt"
