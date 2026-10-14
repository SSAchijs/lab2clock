import hashlib

import pandas as pd
import pytest

from bench import nhanes
from bench.nhanes import (
    FILES,
    REQUIRED,
    UNITS,
    VARIABLES,
    build,
    check_si,
    download,
    to_clock_units,
)
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


def test_converts_to_clock_units():
    clock = to_clock_units(build(frames({1: ADULT})))
    assert list(clock.columns) == [*FIELD_NAMES, "crp_below_lod"]
    row = clock.loc[1]
    assert row["age"] == 52
    assert row["albumin"] == pytest.approx(42)
    assert row["creatinine"] == pytest.approx(79.56, rel=1e-4)
    assert row["glucose"] == pytest.approx(5.27, abs=0.01)
    # mg/L to mg/dL: the trap the CRP codebook sets.
    assert row["c_reactive_protein"] == pytest.approx(0.18)
    assert row["white_blood_cell_count"] == 6.5
    assert row["alkaline_phosphatase"] == 70


# Published values (SEQN: albumin g/dL, g/L; creatinine mg/dL, umol/L; glucose
# mg/dL, mmol/L): the first three adults, and the rows where our factors come
# furthest from NHANES's rounded ones.
REAL = {
    93705: (4.4, 44.0, 0.92, 81.33, 85.0, 4.72),
    93708: (3.9, 39.0, 0.58, 51.27, 116.0, 6.44),
    93709: (3.7, 37.0, 1.32, 116.69, 96.0, 5.33),
    93735: (3.8, 38.0, 11.46, 1013.06, 79.0, 4.39),
    95358: (3.8, 38.0, 1.08, 95.47, 353.0, 19.6),
}


def real_table() -> pd.DataFrame:
    columns = ("LBXSAL", "LBDSALSI", "LBXSCR", "LBDSCRSI", "LBXSGL", "LBDSGLSI")
    rows = {
        seqn: {**ADULT, **dict(zip(columns, values, strict=True))}
        for seqn, values in REAL.items()
    }
    return build(frames(rows))


def test_agrees_with_nhanes_si_columns():
    table = real_table()
    check_si(table, to_clock_units(table))


@pytest.mark.parametrize(
    ("marker", "factor"),
    [
        ("albumin", 0.1),  # left in g/dL
        ("glucose", 18.016),  # left in mg/dL
        ("creatinine", 1 / 88.4),  # left in mg/dL
        ("creatinine", 1.01),  # a 1% wrong factor
    ],
)
def test_si_check_catches_a_wrong_conversion(marker, factor):
    table = real_table()
    clock = to_clock_units(table)
    clock[marker] *= factor
    with pytest.raises(ValueError, match=marker):
        check_si(table, clock)
