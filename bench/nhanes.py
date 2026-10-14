"""Real biomarker combinations from NHANES 2017-2018, the ground truth's source.

Joins four public files on the respondent number (SEQN) into one table: age plus
the nine PhenoAge markers for every adult with all ten present. Values stay in
the units NHANES publishes; converting them is the job of lab2clock's own
conversion table, so this table is also a test of it.

Every variable name and unit below was checked against its codebook, the .htm
page beside each .xpt file. Two codebook facts shape the table:

- Age is top-coded: everyone 80 or older is recorded as 80.
- hs-CRP is in mg/L, with a lower limit of detection of 0.15 mg/L. Results below
  it are filled with 0.15 / sqrt(2) and coded LBDHRPLC = 1, kept here as
  crp_below_lod so the substitution stays visible.

Downloads are cached in bench/data/nhanes/ and checked against a SHA-256, so a
silently revised file fails instead of changing the truth. Needs network access
to wwwn.cdc.gov on the first run:

    uv run python -m bench.nhanes
"""

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lab2clock.clock_spec import MARKERS

DATA = Path(__file__).resolve().parent / "data"
CACHE = DATA / "nhanes"
OUT = DATA / "nhanes_adults.csv"

BASE_URL = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles"

# File stem -> SHA-256 of the .xpt, as downloaded on 14 October 2026.
FILES: dict[str, str] = {
    # Demographics.
    "DEMO_J": "c0b46e0345ea19404928656277c8b0d10b0cca348a9b2fe4fc3c67e8b7ee73ec",
    # Complete blood count with 5-part differential.
    "CBC_J": "00f964098dc91272e415344554cbf1b627ecaeb2eda201518527446a7d81e742",
    # Standard biochemistry profile.
    "BIOPRO_J": "5bcd5722c1892883b96a9d7fed0befadabacae313f800fadc0133cd5dd00c4c6",
    # High-sensitivity C-reactive protein.
    "HSCRP_J": "19109fab0661ba23352bdf17dd9828bbd5dd8be34759888a2a64d9e33397bfe6",
}

# NHANES adults are 20 and over.
ADULT_AGE = 20


@dataclass(frozen=True)
class Variable:
    """One NHANES column kept in the table.

    file: the file stem it comes from.
    nhanes: the variable name in that file.
    column: its name in the table; a clock field name for the ten inputs.
    unit: the unit as the codebook prints it.
    """

    file: str
    nhanes: str
    column: str
    unit: str


VARIABLES: tuple[Variable, ...] = (
    Variable("DEMO_J", "RIDAGEYR", "age", "years"),
    Variable("BIOPRO_J", "LBXSAL", "albumin", "g/dL"),
    Variable("BIOPRO_J", "LBXSCR", "creatinine", "mg/dL"),
    Variable("BIOPRO_J", "LBXSGL", "glucose", "mg/dL"),
    Variable("HSCRP_J", "LBXHSCRP", "c_reactive_protein", "mg/L"),
    Variable("CBC_J", "LBXLYPCT", "lymphocyte_percent", "%"),
    Variable("CBC_J", "LBXMCVSI", "mean_cell_volume", "fL"),
    Variable("CBC_J", "LBXRDW", "red_cell_distribution_width", "%"),
    Variable("BIOPRO_J", "LBXSAPSI", "alkaline_phosphatase", "IU/L"),
    Variable("CBC_J", "LBXWBCSI", "white_blood_cell_count", "1000 cells/uL"),
    # NHANES also publishes three markers in SI units: an independent check on
    # the conversion table.
    Variable("BIOPRO_J", "LBDSALSI", "albumin_si", "g/L"),
    Variable("BIOPRO_J", "LBDSCRSI", "creatinine_si", "umol/L"),
    Variable("BIOPRO_J", "LBDSGLSI", "glucose_si", "mmol/L"),
    # 1 when CRP was below the detection limit and filled with LLOD / sqrt(2).
    Variable("HSCRP_J", "LBDHRPLC", "crp_below_lod", "code"),
)

UNITS: dict[str, str] = {v.column: v.unit for v in VARIABLES}

# The columns a respondent must have to count as complete.
REQUIRED: tuple[str, ...] = ("age", *MARKERS)

# SAS transport files store 0 as a tiny float that pandas reads as about 5e-79.
_SAS_ZERO = 1e-70


def download(stem: str, cache: Path = CACHE) -> Path:
    """Return the cached .xpt for `stem`, downloading it first if needed."""
    path = cache / f"{stem}.xpt"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(f"{BASE_URL}/{stem}.xpt", tmp)
        tmp.rename(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != FILES[stem]:
        raise ValueError(
            f"{path} has SHA-256 {digest}, expected {FILES[stem]}. "
            "NHANES may have revised the file; check its codebook before "
            "updating the hash."
        )
    return path


def read(stem: str, cache: Path = CACHE) -> pd.DataFrame:
    """Read one file, indexed by SEQN, with SAS zeros restored to 0."""
    df = pd.read_sas(download(stem, cache), format="xport", index="SEQN")
    df.index = df.index.astype(int)
    return df.mask(df.abs() < _SAS_ZERO, 0.0)


def build(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join the files into one row per adult with all ten clock inputs.

    frames maps each file stem to its table, indexed by SEQN. An inner join on
    SEQN keeps only respondents present in every file; rows missing any
    required value are then dropped.
    """
    parts = []
    for stem in FILES:
        kept = [v for v in VARIABLES if v.file == stem]
        df = frames[stem][[v.nhanes for v in kept]]
        parts.append(df.rename(columns={v.nhanes: v.column for v in kept}))
    table = pd.concat(parts, axis=1, join="inner")[list(UNITS)]
    table = table[table["age"] >= ADULT_AGE].dropna(subset=list(REQUIRED))
    table["age"] = table["age"].astype(int)
    table["crp_below_lod"] = table["crp_below_lod"] == 1
    table.index.name = "SEQN"
    return table.sort_index()


def load(cache: Path = CACHE) -> pd.DataFrame:
    """Download (or reuse) the four files and return the adult table."""
    return build({stem: read(stem, cache) for stem in FILES})


def main() -> None:
    table = load()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        f.write(f"# NHANES 2017-2018 adults with all clock inputs; units: {UNITS}\n")
        table.to_csv(f)
    print(f"wrote {len(table)} adults to {OUT}")


if __name__ == "__main__":
    main()
