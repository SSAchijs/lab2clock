import pandas as pd
import pytest

from bench.nhanes import DISTRACTORS
from bench.sample import (
    AGES,
    OUT,
    SPLITS,
    high_crp,
    high_glucose,
    sample,
)
from lab2clock.clock_spec import BY_NAME, FIELD_NAMES, MARKERS


def pool(n: int = 300, n_high_crp: int = 10, n_high_glucose: int = 10):
    """A clock-unit table indexed by SEQN, with a few high values of each."""
    rows = {}
    for i in range(n):
        rows[1000 + i] = {
            **{name: 1.0 for name in (*FIELD_NAMES, *DISTRACTORS)},
            "age": 20 + i % 61,  # 20 to 80
            "glucose": 12.0 if i < n_high_glucose else 5.0,
            "c_reactive_protein": 2.0 if n - i <= n_high_crp else 0.2,
        }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("SEQN")


@pytest.fixture(scope="module")
def committed():
    return pd.read_csv(OUT, index_col="report")


# The committed sample.


def test_committed_sample_has_25_reports_dev_first(committed):
    assert list(committed.index) == [f"R{i:02d}" for i in range(1, 26)]
    expected = [s.name for s in SPLITS for _ in range(s.size)]
    assert list(committed["split"]) == expected


def test_committed_sample_has_25_different_people(committed):
    assert committed["SEQN"].is_unique


def test_committed_sample_ages_are_known(committed):
    assert committed["age"].between(*AGES).all()


@pytest.mark.parametrize("split", SPLITS, ids=lambda s: s.name)
def test_committed_sample_meets_each_minimum(committed, split):
    rows = committed[committed["split"] == split.name]
    assert high_crp(rows).sum() >= split.high_crp
    assert high_glucose(rows).sum() >= split.high_glucose


def test_committed_reasons_are_true(committed):
    assert high_crp(committed[committed["reason"] == "high_crp"]).all()
    assert high_glucose(committed[committed["reason"] == "high_glucose"]).all()


def test_committed_sample_has_every_distractor(committed):
    assert not committed[list(DISTRACTORS)].isna().any().any()


def test_committed_values_are_clock_inputs_within_the_error_tier(committed):
    for marker in MARKERS:
        low, high = BY_NAME[marker].error
        assert committed[marker].between(low, high).all(), marker


# The sampler.


def test_same_seed_same_patients():
    assert sample(pool(), seed=1).equals(sample(pool(), seed=1))


def test_different_seed_different_patients():
    assert not sample(pool(), seed=1)["SEQN"].equals(sample(pool(), seed=2)["SEQN"])


def test_forces_the_minimums_when_high_values_are_rare():
    patients = sample(pool(), seed=1)
    for split in SPLITS:
        rows = patients[patients["split"] == split.name]
        assert len(rows) == split.size
        assert high_crp(rows).sum() >= split.high_crp
        assert high_glucose(rows).sum() >= split.high_glucose


def test_leaves_out_top_coded_ages():
    patients = sample(pool(), seed=1)
    assert (patients["age"] < 80).all()


def test_a_patient_high_in_both_counts_towards_both():
    # Every high glucose also has a high CRP, so the CRP draws can cover both.
    both = pool()
    both.loc[both["glucose"] > 5, "c_reactive_protein"] = 2.0
    both.loc[both["glucose"] <= 5, "c_reactive_protein"] = 0.2
    patients = sample(both, seed=1)
    for split in SPLITS:
        rows = patients[patients["split"] == split.name]
        forced = rows["reason"] != "random"
        assert forced.sum() == max(split.high_crp, split.high_glucose)


def test_too_few_high_values_fails_loudly():
    with pytest.raises(ValueError):
        sample(pool(n_high_crp=2), seed=1)
