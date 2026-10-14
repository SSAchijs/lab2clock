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

## Ground truth from NHANES

The fake reports are built from real biomarker combinations, so every patient is physiologically coherent. `bench/nhanes.py` downloads four NHANES 2017–2018 files (demographics, complete blood count, standard biochemistry and hs-CRP), checks each against a SHA-256, and joins them into one table: age plus the nine markers for every adult (20 or older) with all ten present. That is 4,894 adults.

```bash
uv run python -m bench.nhanes
```

The table keeps the units NHANES publishes, as its codebooks state them. The script then converts every value into clock units with lab2clock's own unit normaliser and conversion table, the same path a printed report takes. That makes NHANES the first real test of the conversion table: NHANES also publishes albumin, creatinine and glucose in SI units, and every converted value must agree with them, or the script fails. All 4,894 agree to within 0.01 plus 0.02%. The small gap comes from NHANES's rounded factors (88.4 and 0.0555, against our 88.40 and 0.05551 from molar masses), while a unit slip would be off by a factor of 10 or more. The run writes both tables to `bench/data/`: `nhanes_adults.csv` as published and `nhanes_clock.csv` in clock units.

The same table sets the plausibility tiers in `lab2clock/clock_spec.py`. The warning tier for each marker is the 0.5th to 99.5th percentile of these adults, rounded outwards; a value outside it is unusual but real, such as a diabetic's glucose of 20 mmol/L, so it warns without failing. The error tier was set by hand from published extremes, and since every NHANES value was measured in a real person, none may break it. The script fails if `clock_spec.py` disagrees with either. That check has already caught one limit: an MCV of 35.4 fL in NHANES, below the 44.5 fL found in the literature, so the error floor is now 30 fL.

The warning tier does not catch every unit slip. Glucose left in mg/dL (95 read as 95 mmol/L) warns. CRP left in mg/L usually does not: 2 mg/L read as 2 mg/dL is inside both tiers, so only the unit handling stops it.

Two codebook facts to know:

- **hs-CRP is in mg/L** (LBXHSCRP), not the mg/dL the clock takes. Results below the 0.15 mg/L detection limit are filled with 0.15/√2 and kept with `crp_below_lod`.
- **Age is top-coded**: everyone 80 or older is recorded as 80.

`bench/data/` is ignored by git. NHANES data is public domain, but the script regenerates the downloads and both tables exactly.

### The 25 patients

`bench/sample.py` draws the 25 patients behind the fake reports from that table with a fixed seed, so rerunning it gives the same file, `bench/patients.csv`, which is committed. Five are for developing the prompt and twenty for the scored test set, so the prompt is never tuned on a report it is scored on.

```bash
uv run python -m bench.sample
```

A purely random draw rarely contains large values: twenty random adults have fewer than three CRPs above 10 mg/L about 65% of the time, and fewer than three glucoses of 11.1 mmol/L (200 mg/dL) or more 96% of the time. So the test set is forced to hold at least three of each, and the development set one of each; the rest are random. Each row records why it was drawn. Ages run from 20 to 79, because NHANES records everyone 80 or older as 80 and their true age is unknown.

## Usage

Run the code stages on a stage-1 JSON file, which lists every row as printed (name, value, unit, page):

```bash
uv run python -m lab2clock tests/data/stage1_example.json --age 52
```

The output gives each clock input in the clock's unit with the row it was read from, plus the missing fields, every issue found, and the rows that matched no marker. Age is not read from the report, so pass it with `--age`. An analyte with an error is withheld rather than guessed. The exit status is 0 when the report is ok, 1 when it has errors, and 2 when the input is not a valid stage-1 file.

## Setup

Python 3.12 is required ([pyaging](https://pyaging.readthedocs.io/en/latest/installation.html) needs 3.11 or newer). Recreate the locked environment with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

pyaging and its PyTorch dependency sit in a separate `clock` group, so CI and the conversion code do not need them. Add them when you want to run the clock itself:

```bash
uv sync --group clock
```
