"""Real biomarker combinations from NHANES 2017-2018, the ground truth's source.

Joins four public files on the respondent number (SEQN) into one table: age plus
the nine PhenoAge markers for every adult with all ten present. Values stay in
the units NHANES publishes. to_clock_units then converts them with lab2clock's
own unit normaliser and conversion table, and check_si compares the result with
the SI columns NHANES computed itself: the first real test of that table.

The table in clock units also sets the plausibility tiers in clock_spec: the
warning tier is its 0.5th and 99.5th percentiles, and no value in it may break
the error tier, since every one was measured in a real person.

Every variable name and unit below was checked against its codebook, the .htm
page beside each .xpt file. Two codebook facts shape the table:

- Age is top-coded: everyone 80 or older is recorded as 80.
- hs-CRP is in mg/L, with a lower limit of detection of 0.15 mg/L. Results below
  it are filled with 0.15 / sqrt(2) and coded LBDHRPLC = 1, kept here as
  crp_below_lod so the substitution stays visible.

The table also keeps twelve results that are not clock inputs, from the same
files: the rest of a blood count and a metabolic panel. The reports print them
as distractors, so every row on a report is one real person's result. They are
not required, so they do not change who counts as complete.

Downloads are cached in bench/data/nhanes/ and checked against a SHA-256, so a
silently revised file fails instead of changing the truth. Needs network access
to wwwn.cdc.gov on the first run:

    uv run python -m bench.nhanes

This writes the table as published (nhanes_adults.csv) and in clock units
(nhanes_clock.csv), after the SI check passes, then fails if clock_spec's tiers
disagree with the data, printing the warning limits to put there.
"""

import hashlib
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lab2clock.clock_spec import BY_NAME, FIELD_NAMES, MARKERS, Range
from lab2clock.conversions import convert
from lab2clock.units import normalise_unit

DATA = Path(__file__).resolve().parent / "data"
CACHE = DATA / "nhanes"
OUT = DATA / "nhanes_adults.csv"
CLOCK_OUT = DATA / "nhanes_clock.csv"

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


# Printed on the reports as distractors, never clock inputs. NHANES's SI
# columns are kept where it publishes them.
DISTRACTOR_VARIABLES: tuple[Variable, ...] = (
    Variable("CBC_J", "LBXRBCSI", "red_blood_cell_count", "million cells/uL"),
    Variable("CBC_J", "LBXHGB", "hemoglobin", "g/dL"),
    Variable("CBC_J", "LBXHCT", "hematocrit", "%"),
    Variable("CBC_J", "LBXPLTSI", "platelet_count", "1000 cells/uL"),
    Variable("CBC_J", "LBXNEPCT", "neutrophil_percent", "%"),
    # Printed beside the percent; the cross-check compares the two.
    Variable("CBC_J", "LBDLYMNO", "lymphocyte_count", "1000 cells/uL"),
    Variable("BIOPRO_J", "LBXSNASI", "sodium", "mmol/L"),
    Variable("BIOPRO_J", "LBXSKSI", "potassium", "mmol/L"),
    Variable("BIOPRO_J", "LBXSBU", "urea_nitrogen", "mg/dL"),
    Variable("BIOPRO_J", "LBDSBUSI", "urea_nitrogen_si", "mmol/L"),
    Variable("BIOPRO_J", "LBXSTP", "total_protein", "g/dL"),
    Variable("BIOPRO_J", "LBDSTPSI", "total_protein_si", "g/L"),
    Variable("BIOPRO_J", "LBXSTB", "total_bilirubin", "mg/dL"),
    Variable("BIOPRO_J", "LBDSTBSI", "total_bilirubin_si", "umol/L"),
    Variable("BIOPRO_J", "LBXSATSI", "alanine_aminotransferase", "U/L"),
)

DISTRACTORS: tuple[str, ...] = tuple(v.column for v in DISTRACTOR_VARIABLES)

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
    *DISTRACTOR_VARIABLES,
)

UNITS: dict[str, str] = {v.column: v.unit for v in VARIABLES}

# The columns a respondent must have to count as complete.
REQUIRED: tuple[str, ...] = ("age", *MARKERS)

# Marker -> the SI column NHANES derived from it. The BIOPRO_J codebook gives
# the factors: albumin x 10, creatinine x 88.4, glucose x 0.0555.
SI_COLUMNS: dict[str, str] = {
    "albumin": "albumin_si",
    "creatinine": "creatinine_si",
    "glucose": "glucose_si",
}

# How close a converted value must come to NHANES's SI column. Our molar-mass
# factors (88.40 and 0.055506) differ from NHANES's rounded ones by 0.002% and
# 0.011%, and the SI columns are printed to two decimals; NHANES's own factors
# reproduce its glucose column only to 0.0085. A unit slip is off by 10x or more.
SI_RTOL = 2e-4
SI_ATOL = 0.01

# The warning tier: these percentiles of the adults in clock units, unweighted,
# so they describe the respondents the reports are sampled from.
WARN_QUANTILES: Range = (0.005, 0.995)

# Decimals each warning limit is rounded to, outwards, so rounding never makes
# a value inside the percentiles warn. As many as labs commonly print.
WARN_DECIMALS: dict[str, int] = {
    "albumin": 0,
    "creatinine": 0,
    "glucose": 1,
    "c_reactive_protein": 2,
    "lymphocyte_percent": 1,
    "mean_cell_volume": 1,
    "red_cell_distribution_width": 1,
    "alkaline_phosphatase": 0,
    "white_blood_cell_count": 1,
}

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


def to_clock_units(table: pd.DataFrame) -> pd.DataFrame:
    """The ten clock inputs in the clock's units, plus crp_below_lod and the
    distractors in their published units.

    Each published unit goes through lab2clock's unit normaliser and conversion
    table, exactly as a printed unit on a report would.
    """
    if UNITS["age"] != BY_NAME["age"].unit:
        raise ValueError(f"age is in {UNITS['age']}, the clock takes years")
    clock = pd.DataFrame({"age": table["age"]}, index=table.index)
    for marker in MARKERS:
        unit = normalise_unit(UNITS[marker])
        clock[marker] = table[marker].map(lambda v, m=marker, u=unit: convert(m, v, u))
    clock["crp_below_lod"] = table["crp_below_lod"]
    clock[list(DISTRACTORS)] = table[list(DISTRACTORS)]
    return clock[[*FIELD_NAMES, "crp_below_lod", *DISTRACTORS]]


def check_si(table: pd.DataFrame, clock: pd.DataFrame) -> None:
    """Raise if any converted value disagrees with NHANES's own SI column."""
    for marker, si in SI_COLUMNS.items():
        diff = (clock[marker] - table[si]).abs()
        bad = diff > SI_ATOL + SI_RTOL * table[si].abs()
        if bad.any():
            seqn = diff[bad].idxmax()
            raise ValueError(
                f"{marker}: {bad.sum()} of {len(bad)} converted values disagree "
                f"with {si}; worst SEQN {seqn}: {table.at[seqn, marker]} "
                f"{UNITS[marker]} -> {clock.at[seqn, marker]}, NHANES says "
                f"{table.at[seqn, si]} {UNITS[si]}"
            )


def _round(value: float, decimals: int, rounder) -> float:
    scale = 10**decimals
    # The tolerance stops 12.0 * 10 = 119.99999 from flooring to 11.9.
    nudge = -1e-9 if rounder is math.ceil else 1e-9
    return round(rounder(value * scale + nudge) / scale, decimals)


def warning_limits(clock: pd.DataFrame) -> dict[str, Range]:
    """Per marker, the warning tier: the percentiles, rounded outwards."""
    limits = {}
    for marker in MARKERS:
        low, high = clock[marker].quantile(WARN_QUANTILES)
        decimals = WARN_DECIMALS[marker]
        limits[marker] = (
            _round(low, decimals, math.floor),
            _round(high, decimals, math.ceil),
        )
    return limits


def check_error_tier(clock: pd.DataFrame) -> None:
    """Raise if a measured value breaks clock_spec's error tier.

    The error tier means never measured in any patient, so a real respondent
    outside it proves the limit wrong.
    """
    for marker in MARKERS:
        low, high = BY_NAME[marker].error
        outside = clock[marker][(clock[marker] < low) | (clock[marker] > high)]
        if not outside.empty:
            raise ValueError(
                f"{marker}: SEQN {outside.index[0]} measured {outside.iloc[0]:g} "
                f"{BY_NAME[marker].unit}, outside the error tier {low:g} to {high:g}"
            )


def check_blood_floor(clock: pd.DataFrame) -> None:
    """Raise if the scorer would judge a real adult's value not blood."""
    from bench.score import BLOOD_FLOOR

    for marker, floor in BLOOD_FLOOR.items():
        if floor > clock[marker].min() / 2:
            raise ValueError(
                f"BLOOD_FLOOR[{marker!r}] = {floor:g} is above half the lowest "
                f"NHANES value, {clock[marker].min():g}"
            )


def check_warning_tier(clock: pd.DataFrame) -> None:
    """Raise unless clock_spec holds the warning limits computed from `clock`."""
    computed = warning_limits(clock)
    stale = {m: lim for m, lim in computed.items() if BY_NAME[m].warn != lim}
    if stale:
        raise ValueError(f"clock_spec's warning tier is out of date; use {stale}")


def main() -> None:
    table = load()
    clock = to_clock_units(table)
    check_si(table, clock)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        f.write(f"# NHANES 2017-2018 adults with all clock inputs; units: {UNITS}\n")
        table.to_csv(f)
    units = {name: BY_NAME[name].unit for name in FIELD_NAMES}
    with CLOCK_OUT.open("w") as f:
        f.write(f"# The same adults in clock units: {units}\n")
        clock.to_csv(f)
    print(f"wrote {len(table)} adults to {OUT} and {CLOCK_OUT}")
    check_error_tier(clock)
    check_warning_tier(clock)
    check_blood_floor(clock)
    print(
        "clock_spec's plausibility tiers and the scorer's blood floor agree with NHANES"
    )


if __name__ == "__main__":
    main()
