# lab2clock

Lab report in, clock inputs out.

`lab2clock` converts a blood-test report into the biomarker inputs required by the original PhenoAge clock (Levine 2018), as implemented in [pyaging](https://pyaging.readthedocs.io/).

This repository is under construction.

## Target clock

The target is the original PhenoAge clock (`phenoage` in pyaging), from:

> Levine ME, Lu AT, Quach A, et al. An epigenetic biomarker of aging for lifespan and healthspan. *Aging* 2018;10(4):573–591. [doi:10.18632/aging.101414](https://doi.org/10.18632/aging.101414)

It takes chronological age plus nine routine blood markers: albumin, creatinine, glucose, C-reactive protein, lymphocyte percent, mean cell volume, red cell distribution width, alkaline phosphatase and white blood cell count. All nine come from three standard tests (complete blood count, metabolic panel, hs-CRP), which makes this the clock most likely to be fed from a real lab report.

Not targeted:

- DNA-methylation clocks: their input is not a lab report.
- pyaging's newer PhenoAge refits, such as `phenoagesaopaulo`: they use different markers and units, so they need a different input contract.

### Input format

pyaging 0.5.7 expects these 10 features, by column name. Units come from `pyaging.utils.get_feature_ranges("phenoage")`, and the example ranges come from running the clock on pyaging's `blood_chemistry_example` data (30 NHANES 2007 adults).

| Feature | Unit | Transform inside pyaging | Example range |
| --- | --- | --- | --- |
| `albumin` | g/L | none | 35 to 48 |
| `creatinine` | umol/L | none | 46.0 to 120.2 |
| `glucose` | mmol/L | none | 4.44 to 15.65 |
| `c_reactive_protein` | mg/dL | floored at 0.01, then natural log | 0.01 to 2.00 |
| `lymphocyte_percent` | % | none | 15.1 to 46.6 |
| `mean_cell_volume` | fL | none | 70.1 to 94.6 |
| `red_cell_distribution_width` | % | none | 11.7 to 14.7 |
| `alkaline_phosphatase` | U/L | none | 37 to 126 |
| `white_blood_cell_count` | 10^3 cells/uL | none | 4.9 to 12.3 |
| `age` | years | none | 27 to 77 |

In code, this table lives in `lab2clock/clock_spec.py`. It is the single source of truth for names, units and transforms, and every other module imports from it.

Traps for anyone converting a lab report:

- **CRP goes in raw, in mg/dL.** pyaging 0.5.0 replaced the old pre-logged `log_crp` input with `c_reactive_protein` and moved the log into the clock. Most labs print hs-CRP in mg/L, so a printed value must be divided by 10. If it is left in mg/L, PhenoAge rises by about 2.4 years (ln 10 × 0.0954 / 0.090165), for every patient.
- **White cells need no rescaling.** 10^3 cells/uL equals 10^9/L, which is how most labs print it (for example 6.0).
- **The version matters.** pyaging 0.5.7 fixed a Gompertz constant that had inflated PhenoAge by about 9.6 years in earlier versions. The `clock` group requires 0.5.7 or newer.

### Cross-check against the paper

`bench/phenoage.py` computes PhenoAge from the coefficients and constants published in Levine 2018, independently of pyaging. On all 30 example rows it matches pyaging 0.5.7 within 0.03 years. Since the paper states the unit of every coefficient, this agreement confirms the units in the table above. It lives in `bench/`, not in the `lab2clock` package, because the tool stops at clock inputs and does not report an age. The test runs in CI against `tests/data/phenoage_reference.csv`, so pyaging does not need to be installed. To regenerate that file, run `uv run --group clock python -m bench.make_phenoage_reference`.

## Setup

Python 3.12 is required ([pyaging](https://pyaging.readthedocs.io/en/latest/installation.html) needs 3.11 or newer). Recreate the locked environment with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

pyaging and its PyTorch dependency sit in a separate `clock` group, so CI and the conversion code do not need them. Add them when you want to run the clock itself:

```bash
uv sync --group clock
```
