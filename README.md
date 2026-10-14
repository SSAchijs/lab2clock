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

`bench/sample.py` draws the 25 patients behind the fake reports from that table with a fixed seed, so rerunning it gives the same file, `bench/patients.csv`, which is committed. It reads the table from `bench/data/`, so on a fresh clone run `bench.nhanes` first. Five are for developing the prompt and twenty for the scored test set, so the prompt is never tuned on a report it is scored on.

```bash
uv run python -m bench.sample
```

A purely random draw rarely contains large values: twenty random adults have fewer than three CRPs above 10 mg/L about 65% of the time, and fewer than three glucoses of 11.1 mmol/L (200 mg/dL) or more 96% of the time. So the test set is forced to hold at least three of each, and the development set one of each; the rest are random. Each row records why it was drawn. Ages run from 20 to 79, because NHANES records everyone 80 or older as 80 and their true age is unknown.

### Truth and render spec

Each report has two files. `bench/truth/R07.json` holds what is true about the patient: age and the nine markers in clock units, unrounded. `bench/render_spec/R07.json` holds what the report prints: its conditions (layout, language, unit system), a fake identity for its header, and every row as printed, in the same shape stage 1 returns. Stage 1 is scored against the rows, because a reader can only be asked to copy what was printed. The truth is needed where the printout cannot say what the patient really has: what a planted wrong value or a missing marker should have been, and how far the lab's rounding alone moves the clock. The conditions let errors be sliced by condition.

```bash
uv run python -m bench.spec
```

A printed value is the truth converted into the display unit by lab2clock's own conversion table and rounded half up to the display decimals, as a lab rounds. The tests feed every render spec's rows through the whole pipeline, as a perfect reader would, and require each value to come back to the truth within half a printed step, in every layout, language and unit system. Each report's conditions come from the variation matrix, `bench/matrix.csv`, one row per report. Across the twenty test reports every condition appears at least three times, so each gets a failure rate rather than an anecdote:

| Condition | Test reports | Development reports |
| --- | --- | --- |
| Units: US / SI / mixed | 7 / 7 / 6 | 2 / 2 / 1 |
| Layout: table / two-column / multi-page | 7 / 7 / 6 | 2 / 2 / 1 |
| Chinese (always SI) | 3 | 1 |
| Photo-degraded | 5 | 1 |
| Planted implausible value | 3 | 1 |
| Missing marker | 3 | 1 |
| Previous-results column | 4 | 1 |

A planted value is a real kind of slip that lands outside the error tier, so the expected outcome is an error on that marker: an MCV with its decimal point moved (89.3 printed 8.93), a lymphocyte percent times ten, or a white-cell count printed per µL under a 10^9/L unit. A white-cell slip also breaks the lymphocyte cross-check, which cannot tell which of the two is wrong, so the correctly printed percent is withheld too. Planted and missing conditions never touch the marker a patient was drawn for. A previous result is within 10% of the current one, rounded the same way, and dated 90 to 365 days earlier. The tests check the counts, and that a perfect reader of every report gets every marker back to the truth except those its conditions break, which must fail as errors.

Each report prints a full blood count and metabolic panel, not only the nine markers: twelve more results, such as haemoglobin, platelets, sodium and ALT, all from the same NHANES respondent, so the whole page is one real person. They are distractors a reader must skip, except the absolute lymphocyte count, which the cross-check compares with the printed percent. All 7,523 NHANES blood counts pass that cross-check at the printed rounding.

The identity is made by [Faker](https://faker.readthedocs.io/) from a seed, in the report's language: a patient name, patient and specimen numbers, dates, a physician and a facility. It is distractor text, as on a real report, and involves no real person. The date of birth is drawn so the patient is exactly the truth's age on the collection date, and no identity text maps to a clock marker.

## Reports

`bench/render.py` lays each render spec out as an HTML report with [Jinja2](https://jinja.palletsprojects.com/) templates in `bench/templates/`, one per layout:

- **Table**: both panels as tables, with a flag column and reference intervals.
- **Two-column**: the panels side by side as lists, with the flag printed in the result cell (`146 H`), so a perfect reader's value includes it.
- **Multi-page**: one panel per page with the header repeated, as a cumulative report prints it.

The table and multi-page layouts add a previous-results column when the report has one. Every printed string comes from the render spec, including each row's reference interval and its H/L flag, so the templates only arrange it. The intervals are illustrative adult intervals of the kind large labs print, not clinical guidance; they set the flags and agree between unit systems. Every report says in its footer that it is synthetic.

```bash
uv run python -m bench.render
```

This writes `bench/data/reports/R01.html` and so on. Each results row carries `data-row`, its index in the spec, and the tests check that every row prints its own name, value, unit, interval, flag and previous result, not merely somewhere on the page.

Chinese reports use the same layouts with Chinese labels, ISO dates and A4 paper. They are printed in Noto Sans SC, which `bench/fonts.py` downloads from a pinned [noto-cjk](https://github.com/notofonts/noto-cjk) release (SIL Open Font License), checks against a SHA-256 and caches in `bench/data/fonts/`. The HTML loads it through `@font-face`, so Chinese never prints as empty boxes or in whatever font the machine happens to have.

`bench/pdf.py` prints every report to PDF with [Playwright](https://playwright.dev/python/)'s headless Chromium, the same browser engine that lays out the HTML:

```bash
uv run playwright install chromium   # once
uv run python -m bench.pdf
```

This renders the HTML and writes `bench/data/reports/R01.pdf` and so on, each at its report's page size (Letter or A4). Before printing, every font a report declares must load, or the run stops rather than printing in a fallback font.

The run ends with `bench/selfcheck.py`, which reads each PDF's text layer back with PyMuPDF and fails unless every row of the render spec is printed as its own line on its own page: name, value, flag, previous result, unit and reference interval, in column order, with the interval on the next line in the two-column layout. Finding each value somewhere on the page would not be enough, since a value like 4.2 appears in many places; a value printed in the wrong row must fail, and the tests prove it does by swapping values, flags, intervals and pages in a spec. It also runs on its own: `uv run python -m bench.selfcheck`.

`bench/raster.py` turns each PDF into one PNG per page with [PyMuPDF](https://pymupdf.readthedocs.io/), the starting point for the photo-degraded reports:

```bash
uv run python -m bench.raster
```

This writes `bench/data/images/R01-1.png`, `R03-1.png`, `R03-2.png` and so on: 32 pages from 25 reports. Pages are rendered at 200 DPI, where the smallest printed text (7.5pt) is about 21 pixels tall, on white without transparency, and the same PDF always gives the same bytes.

`bench/degrade.py` turns the page images of the six photo reports (one development, five test) into phone photos with [OpenCV](https://opencv.org/), in the order a real photo happens: the page lies on a desk, the camera sees it turned up to 3° and slanted, the room lights it unevenly and warmly, the lens blurs it, the sensor adds noise, and the phone saves a JPEG at quality 55 to 80:

```bash
uv run python -m bench.degrade
```

This writes `bench/data/photos/R05-1.jpg` and so on, and `steps.json` with the steps drawn for each page. Every step comes from the degradation seed in the report's render spec and the page number, so a photo regenerates byte for byte, and each page of a multi-page report is photographed differently. The ranges keep every value legible; the tests check that ink still stands well clear of paper at the harshest end of every range at once. Augraphy was not used: it draws from global random state, which makes exact regeneration harder to guarantee.

## Oracle

Before any paid model reads a report, `bench/oracle.py` reads it perfectly. The oracle is a stage-1 extractor that takes each render spec and returns exactly what a flawless reader would copy from the page: every row's name, value, unit and page, in printed order, and nothing else. In the two-column layout it includes the flag, as in `146 H`. The self-check has already proved that every PDF prints its spec row by row, so the spec is a faithful record of the page.

```bash
uv run python -m bench.oracle
```

This writes `results/responses/oracle/R01.json` and so on, one stage-1 report each. The scorer will read every extractor's responses from that same folder. The responses are committed so they can be scored on a fresh clone, and the tests fail if any of them differs from a fresh run. The oracle, run through the code stages and scored, must reach 100%. If it falls short, the bug is in the generator, the core or the scorer, and it has been found for free.

## Scoring

`bench/score.py` defines what counts as a correct reading, at two levels:

- **Stage 1** is scored against what was printed. A value or unit counts as correct if it matches the printed one after normalising typography only: spaces, a decimal comma (`5,6` is `5.6`, but `5,500` is not `5.500`), full-width characters, the two micro characters, superscript exponents and letter case. A trailing H or L flag is ignored, since most layouts print it in its own column. Renaming a unit is not a typography difference: `K/uL` for a printed `10^9/L` counts as wrong at this stage, even though the core reads both the same way.
- **End to end** is scored against the printed value converted to the clock's unit. A value within 0.5% counts as correct. The comparison is with the printed value, not the unrounded truth, because labs round: a CRP of 0.24 printed as 0.2 is 17% off the truth, and that gap is the lab's doing, not the pipeline's. The 0.5% covers floating-point noise and differences between published factors, while the smallest real slip, a factor of 10, is 900% off.

The scorer converts the printed value with lab2clock's own conversion table. That table is checked independently elsewhere, by its tests against the factors labs publish and by `bench.nhanes` against the SI columns NHANES computed itself, so the oracle run is free to look for wiring bugs instead.

Every marker that is not fully correct is blamed on the first stage that went wrong, in pipeline order, so each error points to the stage to fix:

| Stage | What went wrong |
| --- | --- |
| omitted | the printed row was not transcribed |
| value | its value was misread |
| unit | its unit was misread |
| mapping | its name did not map to its marker, or another row was mapped to it |
| conversion | it was read and mapped correctly, but parsed, normalised or converted wrongly |
| flag | the checks withheld a correct value, or let a planted one through |

To tell a misread name from a skipped row, the scorer lines up the transcribed rows with the printed ones without using the core's synonym dictionary. It matches by name and page first, then by value and unit for a row whose name was misread. A misread lymphocyte count makes the cross-check withhold a percent that was read correctly, so that error is blamed on the misread count, not on the check. A misread can also leave the clock input right, as when `10^9/L` is renamed `K/uL`, so a marker can carry a stage-1 error and still be correct end to end.

The tests inject one error of each kind into the oracle's output and check that it is blamed on its stage and on its marker alone. Run unchanged, the oracle scores every marker of every report correct.

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
