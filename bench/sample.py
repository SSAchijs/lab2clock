"""The 25 patients behind the fake reports, sampled from NHANES with a fixed seed.

Each patient is one real respondent: age and the nine markers in clock units,
plus the distractor results printed beside them, from bench.nhanes. Five are for
prompt development and twenty for the scored test set, so the prompt is never
tuned on a report it is scored on.

A purely random sample rarely contains the large values that exercise different
paths: a random 20 has fewer than three CRPs above 10 mg/L about 65% of the
time, and fewer than three glucoses of 11.1 mmol/L or more 96% of the time. So
each split gets a forced minimum of each, and the rest are drawn at random.

Respondents recorded as 80 are left out: NHANES top-codes age, so their true
age is unknown.

    uv run python -m bench.sample

writes bench/patients.csv, which is committed: rerunning gives the same file.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bench.nhanes import CLOCK_OUT, DISTRACTORS
from lab2clock.clock_spec import FIELD_NAMES

OUT = Path(__file__).resolve().parent / "patients.csv"

SEED = 2017

# Ages sampled: adults below NHANES's top-code of 80.
AGES = (20, 79)

# 10 mg/L, the plan's threshold for a large CRP.
HIGH_CRP = 1.0  # mg/dL
# 200 mg/dL, the WHO threshold for diabetes on a random glucose (WHO 2006,
# Definition and diagnosis of diabetes mellitus and intermediate hyperglycaemia).
HIGH_GLUCOSE = 11.1  # mmol/L


@dataclass(frozen=True)
class Split:
    name: str
    size: int
    # Minimum number of patients with a high CRP, and with a high glucose.
    high_crp: int
    high_glucose: int


SPLITS: tuple[Split, ...] = (
    Split("dev", 5, high_crp=1, high_glucose=1),
    Split("test", 20, high_crp=3, high_glucose=3),
)


def high_crp(clock: pd.DataFrame) -> pd.Series:
    return clock["c_reactive_protein"] > HIGH_CRP


def high_glucose(clock: pd.DataFrame) -> pd.Series:
    return clock["glucose"] >= HIGH_GLUCOSE


def sample(clock: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """25 patients from `clock`, a table in clock units indexed by SEQN.

    Returns one row per patient, indexed by report id (R01 to R25; dev first),
    with split, SEQN, the reason it was drawn, and the ten clock inputs.
    """
    rng = np.random.default_rng(seed)
    pool = clock[clock["age"].between(*AGES)].sort_index()
    rows = []
    for split in SPLITS:
        chosen: list[tuple[int, str]] = []
        for reason, mask, n in (
            ("high_crp", high_crp(pool), split.high_crp),
            ("high_glucose", high_glucose(pool), split.high_glucose),
            ("random", pd.Series(True, index=pool.index), None),
        ):
            taken = {seqn for seqn, _ in chosen}
            candidates = pool.index[mask & ~pool.index.isin(taken)]
            # Count what earlier draws already supply, so a patient high in
            # both counts towards both minimums.
            have = int(mask.loc[list(taken)].sum()) if taken else 0
            want = split.size - len(chosen) if n is None else max(n - have, 0)
            picks = rng.choice(candidates, size=want, replace=False)
            chosen += [(int(seqn), reason) for seqn in picks]
        rng.shuffle(chosen)
        for seqn, reason in chosen:
            rows.append({"split": split.name, "SEQN": seqn, "reason": reason})
            pool = pool.drop(index=seqn)

    out = pd.DataFrame(rows)
    out.index = pd.Index([f"R{i:02d}" for i in range(1, len(out) + 1)], name="report")
    columns = [*FIELD_NAMES, *DISTRACTORS]
    values = clock.loc[out["SEQN"], columns].set_index(out.index)
    return pd.concat([out, values], axis=1)


def load(path: Path = OUT) -> pd.DataFrame:
    """The committed patients, with every float read back exactly.

    pandas' default float parser can be off in the last digit, and differently
    on Linux and macOS; round_trip reads back exactly what was written.
    """
    return pd.read_csv(path, index_col="report", float_precision="round_trip")


def main() -> None:
    clock = pd.read_csv(
        CLOCK_OUT, comment="#", index_col="SEQN", float_precision="round_trip"
    )
    patients = sample(clock)
    patients.to_csv(OUT)
    print(f"wrote {len(patients)} patients to {OUT}")


if __name__ == "__main__":
    main()
