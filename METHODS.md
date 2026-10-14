# lab2clock: methods

Lab report in, clock inputs out.

`lab2clock` converts a blood-test report into the biomarker inputs required by the original PhenoAge clock (Levine 2018), as implemented in [pyaging](https://pyaging.readthedocs.io/).

This file documents every step in detail. For the results and what they mean, see the [README](README.md).

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

`lab2clock/phenoage.py` computes PhenoAge from the coefficients and constants published in Levine 2018, independently of pyaging, flooring CRP at 0.01 mg/dL before its log as pyaging does. On all 30 example rows it matches pyaging 0.5.7 within 0.03 years. Since the paper states the unit of every coefficient, this agreement confirms the units in the table above. The tool's output stops at the clock inputs; the command line adds an age from this formula only when asked with `--age-estimate`, labelled as an estimate. The test runs in CI against `tests/data/phenoage_reference.csv`, so pyaging does not need to be installed. To regenerate that file, run `uv run --group clock python -m bench.make_phenoage_reference`.

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

This writes `results/responses/oracle/1/R01.json` and so on, one stage-1 report each, with the prompt it was read with. The oracle reads without one, so it records none. The scorer reads every extractor's responses from `results/responses/<extractor>/<run>/`. The oracle never varies, so it has one run. The responses are committed so they can be scored on a fresh clone, and the tests fail if any of them differs from a fresh run. Run through the code stages and scored, the oracle must reach 100%, and it does, on every metric and every report. If it ever falls short, the bug is in the generator, the core or the scorer, and it has been found for free.

## Scoring

`bench/score.py` defines what counts as a correct reading, at two levels:

- **Stage 1** is scored against what was printed. A value or unit counts as correct if it matches the printed one after normalising typography only: spaces, a decimal comma (`5,6` is `5.6`, but `5,500` is not `5.500`), full-width characters, the two micro characters, superscript exponents and letter case. A trailing H or L flag is ignored, since most layouts print it in its own column. Renaming a unit is not a typography difference: `K/uL` for a printed `10^9/L` counts as wrong at this stage, even though the core reads both the same way.
- **End to end** is scored against the printed value converted to the clock's unit. A value within 0.5% counts as correct. The comparison is with the printed value, not the unrounded truth, because labs round: a CRP of 0.24 printed as 0.2 is 17% off the truth, and that gap is the lab's doing, not the pipeline's. The 0.5% covers floating-point noise and differences between published factors, while the smallest real slip, a factor of 10, is 900% off.

The scorer converts the printed value with lab2clock's own conversion table. That table is checked independently elsewhere, by its tests against the factors labs publish and by `bench.nhanes` against the SI columns NHANES computed itself, so the oracle run is free to look for wiring bugs instead.

Every marker that is not fully correct is blamed on the first stage that went wrong, in pipeline order, so each error points to the stage to fix:

| Stage | What went wrong |
| --- | --- |
| invalid | the response broke the stage-1 schema twice, so nothing was read |
| omitted | the printed row was not transcribed |
| value | its value was misread |
| unit | its unit was misread |
| mapping | its name did not map to its marker, or another row was mapped to it |
| conversion | it was read and mapped correctly, but parsed, normalised or converted wrongly |
| flag | the checks withheld a correct value, or let a planted one through |

To tell a misread name from a skipped row, the scorer lines up the transcribed rows with the printed ones without using the core's synonym dictionary. It matches by name and page first, then by value and unit for a row whose name was misread. A misread lymphocyte count makes the cross-check withhold a percent that was read correctly, so that error is blamed on the misread count, not on the check. A misread can also leave the clock input right, as when `10^9/L` is renamed `K/uL`, so a marker can carry a stage-1 error and still be correct end to end.

The tests inject one error of each kind into the oracle's output and check that it is blamed on its stage and on its marker alone. Run unchanged, the oracle scores every marker of every report correct.

The metrics, each with a Wilson 95% interval:

| Metric | Share of | Correct when |
| --- | --- | --- |
| Value accuracy | the nine markers of every report | the input is right, or correctly withheld |
| Stage-1 accuracy | printed marker rows | the value and unit are transcribed correctly |
| Report accuracy | reports | all nine markers are correct |
| Flag precision | printed markers the pipeline withheld | the marker had to be withheld |
| Flag recall | printed markers that had to be withheld | the pipeline withheld it |

Report accuracy is the number that matters most to a user, because one wrong input corrupts the clock. Stage-1 accuracy is the one that compares directly with the real-world set, which is scored on it and end to end against its labels. A marker has to be withheld when its printed value is a planted slip, or when a planted slip breaks its cross-check. A missing marker counts toward neither flag metric, since nothing was printed to flag. The intervals are Wilson intervals because, near 100% on a sample this small, the usual normal-approximation interval runs past 100%: at 19 of 20 its upper end is 104.6%, while Wilson's is 99.1%.

### Results

One command goes from the cached responses to the results:

```bash
uv run python -m bench.score
```

It scores every response in `results/responses/<extractor>/<run>/` and writes `results/results.csv`, with one row per marker per report per run. Each row holds the extractor, the prompt, the form the report was sent in, the run, the split, the report's conditions, the value as printed and as read, the expected and delivered clock input, whether it is correct, and the stage that went wrong. It then writes `results/summary.md`, the accuracy and errors-by-stage tables, computed from the CSV alone, so every accuracy figure in this README comes from that file and none is typed by hand. Both files are committed, and the tests fail if either differs from a fresh run. The test and development sets are reported separately, because the development set is used to tune the prompt.

`uv run python -m bench.figure` draws the README's figure from `results.csv` the same way, as `docs/results-light.svg` and `docs/results-dark.svg`, and the tests fail if either differs from a fresh run.

## Models

Two models read the reports at stage 1, giving two points on the cost-versus-accuracy curve: Claude Opus 5.5 (`claude-opus-5-5`, $4 / $20 per million input and output tokens) and Claude Haiku 5.5 (`claude-haiku-5-5`, $0.10 / $0.50), 40 times cheaper per token. Haiku writes more output tokens for the same report, so per report it is about 30 times cheaper: $0.0011 against $0.034 on the real set. A failure both make is one that no choice of model fixes.

Neither ID names a dated snapshot, so before a run `bench/models.py` asks the Models API for each model's record and writes it, with the date and the SDK version, to `results/models.json`. It fails if either model is not served, or cannot take a PDF or an image or answer in a fixed JSON schema. It needs `ANTHROPIC_API_KEY` in `.env`.

```bash
uv run python -m bench.models
```

## Prompt

The prompt that asks a model for the stage-1 transcription is a plain text file, [`prompts/extract_v1.txt`](prompts/extract_v1.txt). It asks for every current result exactly as printed, on every page and in printed order. The model must not convert, translate or rename anything, must copy units verbatim, and must leave out previous results, reference intervals and patient details. It describes lab reports in general, not the layouts of this generator, so it is not tuned to the reports it is scored on.

Results from different prompts are not comparable, so once a response has been recorded with a prompt, the file is never edited. A change is a new file, `extract_v2.txt`. Every saved response records the prompt's version and the SHA-256 of its text, and every row of `results.csv` records the version. The scorer refuses an extractor whose responses disagree on either, so a prompt edited in place cannot mix two prompts' results silently.

## Reading a report

`bench/extract.py` sends one report per call, with the prompt as the system message. The API's structured-output mode holds the answer to the stage-1 JSON schema from `lab2clock/stage1.py`, the same definition the core validates, so the model and the code cannot drift apart. The API cannot enforce every rule in that schema. It drops the length and range limits, such as a name of at least one character or a page from 1, and an answer that was refused or cut off at the token limit need not fit at all. So every answer is validated again against the full schema.

Each report is sent in its native form, as a real app would receive it. A digital report goes as its PDF, so the model can use the text layer. A photographed one goes as its photos, one JPEG per page, each after a line naming its page, since an app knows the order the photos were taken in. Every response records which form was sent and the files, and `results.csv` has a `form` column.

An answer that fails is retried once. Each failure is saved in the response, with what the model wrote, even when the retry succeeds. After a second failure the response has no report, and the scorer blames every printed marker in it on the `invalid` stage. A broken output is a failure mode worth counting, and retrying until the model complies would hide it.

Every response is saved where the scorer reads it, in `results/responses/<model>_<prompt>/<run>/`, and the saved responses are the cache. Each one holds a key, the SHA-256 of everything it was read from: every file sent, the model, the prompt version and text, the settings and the run number. A rerun skips every report whose saved key matches, so rescoring makes no API call, and spending is bounded to one call per report per run. The run number is part of the key, so repeated runs of one report are read separately rather than copied from the first. If a saved response was read from something else, such as a regenerated PDF or a changed setting, the run stops rather than mix old and new answers. Each response also records the tokens billed, over every attempt, for the cost comparison. Because the raw responses are committed, anyone can rescore them without an API key.

Neither model offers a setting that lowers randomness. Both reject `temperature` and `top_k` with a 400, and Opus 5.5 cannot turn thinking off. So every setting the API does take is pinned, the same for both models, so a changed default cannot change an answer between runs: medium effort, both models' default, and adaptive thinking, the only mode Opus 5.5 allows. Effort trades accuracy for cost rather than setting randomness, so it is kept at the default rather than tuned. Each report is then read three times, because repeats are the only way left to tell an error a model makes every time from one it makes by chance.

```bash
uv run python -m bench.extract cheap --split dev
```

This reads every development report three times with Claude Haiku 5.5, into `results/responses/claude-haiku-5-5_extract_v1/1/` to `3/`; `frontier` reads with Claude Opus 5.5. On a one-page PDF, Opus 5.5 used about 3,300 input and 650 output tokens ($0.026) and Haiku 5.5 about 3,300 and 960 ($0.0008), so three runs of the 20 test reports cost roughly $1.60 and $0.05.

## Real-world set

The synthetic reports show how stage 1 does when every condition is known. [MedRepBench](https://huggingface.co/datasets/MedRepBench/MedRepBench) ([arXiv 2508.16674](https://arxiv.org/abs/2508.16674)) shows how far that carries over to real ones: 1,925 de-identified Chinese medical report images, each labelled with the items printed on it (name, value, unit, reference range and abnormal flag). Those labels record what was printed, which is exactly stage 1's contract.

The dataset is licensed CC BY-NC 4.0, so none of it is committed: redistributing it inside this MIT repository would muddy the licensing, and a script is enough to reproduce it. `bench/medrepbench.py` fetches it into `bench/data/medrepbench/`, which git ignores, from one pinned revision of the dataset. The labels are checked against a pinned SHA-256, and each image against the SHA-256 Hugging Face publishes for it. The images total 2 GB, so only the ones scored are fetched.

At the pinned revision, 819 reports have item labels, but 387 of the images are empty files, 133 of them labelled ones. So 686 labelled reports have an image to read. Fetching an empty image fails rather than score a model on a blank page.

The scored set is every labelled report that prints at least three of the nine clock markers, matched by the core's synonym dictionary, and has an image. With fewer markers, a call yields too little clock-relevant data. Only 39 reports qualify: most labelled reports are other tests, such as urinalysis, coagulation or hormones, and most that print a marker print one or two. So all 39 are scored, and no seed is needed: the set follows from the labels, the dictionary and the revision alone. They print 146 marker values. The dictionary is not why there are so few. The names it leaves unmapped that look like markers are lookalikes it excludes on purpose, such as platelet distribution width (血小板分布宽度), RDW-SD, prealbumin (前白蛋白) and urine tests, or a lymphocyte row with no unit, which could be the count or the percent.

`bench/medrepbench.csv` fixes the set, committed: each report's ID (M01 to M39), image name, the image's SHA-256 and the markers it prints. Its labelled marker rows, 149 of them (some reports print two rows for one marker, such as CRP and hs-CRP), are committed in `bench/medrepbench_labels.csv`, so the real set can be scored, and rescored in CI, without the dataset.

```bash
uv run python -m bench.medrepbench select   # rebuild bench/medrepbench.csv from the labels
uv run python -m bench.medrepbench          # fetch the labels and the 39 images
```

### How often the labels are wrong

MedRepBench's labels were produced by OCR and an LLM; the authors report about 97% agreement in their own audit. Before a model is blamed for disagreeing with a label, the label itself has to be right. So 10 of the 39 reports, drawn with a fixed seed, were checked by hand against their images: every labelled row that maps to a clock marker, 44 in all, its name, value and unit.

The check was meant to be done by a person, not a model, because the models scored are Claude models and a misreading shared with the checker would pass unseen. `bench/audit.py` writes a local review page showing each image beside its rows, and the verdicts are committed in `bench/medrepbench_audit.csv`. That hand pass accepted all 44 rows. A second, independent pass by Claude then found four wrong ones, all units, and the person checking confirmed each against the image. So the hand check alone found none of the errors; the four below were found by a model and confirmed by a person.

```bash
uv run python -m bench.audit         # write the review page
uv run python -m bench.audit score   # the error rate from bench/medrepbench_audit.csv
```

4 of the 44 marker labels are wrong: 9.1%, with a Wilson 95% interval of 3.6% to 21.2%. No printed marker is missing from the labels. Every error is in the unit; no value or name is wrong:

- a unit the label supplies that the row does not print, where the reference range is blacked out and there is no units column;
- a unit the label leaves out, where the units column prints `%`;
- `mg/l` read as `mg/1`, twice, where the font draws a lowercase L like a 1.

So on these reports the labels can be trusted for values, but a unit disagreement between a model and a label may be the label's fault. The labels also treat a unit printed only inside the reference range inconsistently, taking it as the unit on some rows and leaving it out on others. Stage 1 on the real set is scored with both in mind.

### Scoring the real set

Each report is read three times by each model with the frozen prompt, behind the same lock as the synthetic test set, and sent as the one image it came as. The image type is taken from the file's bytes, since every one of the 39 is a PNG although 16 are named `.jpg` or `.jpeg`. The API refuses an image over 10 MB once base64-encoded, so the one image that exceeds it is re-encoded as a JPEG at the same size, as a real app would have to.

```bash
uv run python -m bench.extract cheap --split real --workers 8
uv run python -m bench.extract frontier --split real --workers 8
```

`--workers` reads that many reports side by side; each is still one call, saved on its own.

The labels say what was printed, not what the patient had, so the real set is scored twice.

**Stage 1**, against what was printed. Each labelled marker row is lined up with the item read from it as on the synthetic reports, by name first and then by value and unit. Because the labels' units are noisy, a last pass also matches by value alone, so a row read under another name, such as `ALB` for a label's `白蛋白` with `g/l` for `g/1`, is not counted as omitted. Each row is scored on its value as printed and its unit as labelled. A trailing `+` or `-`, which Chinese reports print as a flag, is not part of the value, just as `H`, `L`, `↑` and `↓` are not. The four labels the hand check found wrong are scored as what is printed. Since the labels were right on every value checked but wrong on 9% of units, the value rate is the one to trust, and the unit rate is a lower bound.

**End to end**, against what reached the clock. Every response is run through the code stages, and each labelled marker is put in one of these classes:

| Class | When |
| --- | --- |
| Right | the input delivered is the labelled value, converted to the clock's unit, within 0.5% |
| Wrong | it is not; or the label prints text for the marker, such as a urine test's `Negative`, so nothing should have been delivered |
| Missing | nothing was delivered for a labelled number |
| Limit | what was delivered was printed as a limit, such as `<0.5`: a bound on the value, not the value |
| Unverified | something was delivered, but the label has no unit, so it cannot be checked |

A wrong input is the error that matters, because it reaches the clock looking like any other value. A missing one only leaves the clock without it, and the output says so. Markers labelled only with text, and rightly not delivered, are counted apart and left out of the rates.

The reports are all Chinese and mostly in SI units, so this set does not test US units; the synthetic set covers that.

### What the real set shows

Copying is not the hard part. Both models copy about 95% of printed values exactly. Only 73% of labelled markers reached the clock, though, with the code as it was when the set was first scored:

| Claude Haiku 5.5, 39 reports, 3 runs | Right | Wrong | Missing |
| --- | --- | --- | --- |
| Before the fixes below | 319 / 438 (72.8%) | 2 | 111 |
| After them | 339 / 438 (77.4%) | 3 | 90 |

Claude Opus 5.5 is within two percentage points of Haiku in both rows (73.7% before, 79.2% after), at about 30 times the cost per report. `results/summary.md` holds the "after" rows; there, the 3 inputs delivered as a limit (M05's CRP `<0.5`) are counted apart, while the code before the fixes did not mark them, so the "before" row counts them as right. The "before" row is the same responses scored with the code as it was before the fixes, commit `42e99c2`:

```bash
git checkout 42e99c2 -- lab2clock        # the code before the fixes
uv run python -m bench.score             # rescore every response with it
git checkout HEAD -- lab2clock results   # back to the current code and results
```

What the errors show:

- **One wrong value reached the clock that the labels did not show.** On M18 a pen line covers the white cell count; both models guessed it, differently in each run. The label has no unit, so the score called those deliveries unverified rather than wrong, and only looking at the image showed it. The lymphocyte cross-check had caught the mismatch, but it withheld the percent and let the guessed count through. It now withholds both, since it cannot tell which of them was misread.
- **Every input scored wrong is a wrong label.** On M01 and M31 the label calls the RDW-SD row (printed in `%` on those reports) the RDW; the pipeline delivered the RDW-CV, which is the clock's RDW. Checked against both images.
- **The dataset blurs albumin's name.** MedRepBench's de-identification pixelates 白蛋白 on most reports that print it, presumably because 白 is a surname. The labels were made before the blurring. Haiku writes `[redacted]`; Opus leaves the row out. Neither guesses, so the marker goes missing rather than wrong.
- **Most of the rest of what goes missing is in the report.** Rows that print no unit are refused on purpose; others are cropped off, crossed out, or printed twice (CRP and hs-CRP), which the duplicate check withholds.
- **The code's own gaps were names and formats.** Names that put an abbreviation beside the Chinese name (`ALP 碱性磷酸酶`, `MCV红细胞平均体积`), a few standard Chinese variants, a `+` flag set after a value, and the unit `*10`9/L`. All are fixed (see below).

None of these is removed from the score. Only the four labels the random hand check found wrong are corrected. Correcting the labels wherever a model disagrees would check only the disagreements, never a wrong label a model happened to agree with, and so flatter the models.

### Held-out set

The fixes were found by looking at the 39 reports, so scoring them on the same reports would flatter them. They were tested on 142 other MedRepBench reports instead: every labelled report outside the 39 that prints at least one marker and has an image, IDs H001 onwards, fixed in `bench/medrepbench_heldout.csv` and `bench/medrepbench_heldout_labels.csv`. Nobody looked at them until the fixes were in. Claude Haiku 5.5 read each three times.

```bash
uv run python -m bench.medrepbench heldout   # rebuild the held-out set from the labels
uv run python -m bench.extract cheap --split heldout --workers 8
```

Haiku copied 94% of the printed numbers exactly, as on the 39. Of the labelled markers with a number, 66% reached the clock right (329 of 495 over three runs) and 31% went missing. About 40% of the missing ones are albumin with its name blurred, a quarter are rows with no unit printed or read, and most of the rest are values written in a form the code refuses or rows the model left out.

Many held-out reports are urine tests, which print results such as `Negative`, `3+` or `-` under the same names as blood markers (白细胞, 葡萄糖). They found two ways a wrong value got through:

- **H074**, in one run: a urine test's `-` copied as `0`, delivered as a blood glucose and white cell count of 0.
- **H118**, in every run: a urine `3+` read as the number 3 with a `+` flag, by the flag rule added after the 39 were scored, and delivered as 3 white cells per µL.

Both are fixed. A value of exactly 0 is now refused for markers a living person cannot have at 0, since a lab prints a detection limit such as `<0.1` instead; and `+` or `-` is a flag only when set apart from the number, so `3+` is not a number. The one input still scored wrong, H056's alkaline phosphatase, is a wrong label: the report prints 87.0, which is what was delivered, and the label took 14.3 from another column.

One gap remains: a urine white cell count printed as a plain number per µL, under the blood marker's name, would pass with only a warning. None of the held-out reports did that, but a specimen check would be needed to rule it out.

### Changes made after seeing results

Every change made after a set's responses were read, so a reader can judge how much each result was tuned:

| Seen | Changed | Kind |
| --- | --- | --- |
| first real responses | a trailing `+` or `-` is a flag when scoring stage 1; a real row can be matched by its value alone | scorer |
| the 39 real reports | end-to-end scoring of the real set | scorer |
| the 39 real reports | the cross-check withholds the white cell count too | code |
| the 39 real reports | compound names; five Chinese names; `+` and `-` flags in values; the unit `*10`9/L` | code |
| the held-out reports | a label that prints text counts as wrong when anything is delivered for it | scorer |
| the held-out reports | a 0 is refused for markers that cannot be 0; `+` and `-` are flags only when set apart | code |
| a review of the published results | a value printed as a limit keeps its direction: above a limit it is withheld, below one it warns and the age estimate is a range | code |
| a review of the published results | a delivered limit is scored as its own class, not as right | scorer |

The held-out rates above are with all of these in place. With the code as it was frozen before the held-out set was read, the same responses put 67% of labelled numbers on the clock right and 8 wrong over three runs: H056's wrong label in each run, and five real errors, H074's two zeros in one run and H118's `3+` in each. Parsed with that code's own rule, the label `3+` is the number 3 too, so a score with it counts H118 as right; that is why the scorer's text rule and the code's flag rule were changed together.

### License of the derived files

MedRepBench is licensed [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), by Xia, Shang et al. ([arXiv 2508.16674](https://arxiv.org/abs/2508.16674)). No image and not the label file are in this repository, but these files are derived from it and are under CC BY-NC 4.0, not the MIT license of the rest:

- `bench/medrepbench.csv`, `bench/medrepbench_labels.csv`, `bench/medrepbench_heldout.csv`, `bench/medrepbench_heldout_labels.csv` and `bench/medrepbench_audit.csv`;
- the responses to the real reports, `results/responses/*/*/M*.json` and `results/responses/*/*/H*.json`;
- the rows of `results/results.csv` whose split is `real` or `heldout`, and the real-world tables in `results/summary.md`.

## Usage

Read a report of your own, a PDF or one photo per page in page order, with `ANTHROPIC_API_KEY` in `.env`:

```bash
uv run lab2clock report.pdf --age 52
uv run lab2clock page1.jpg page2.jpg --age 52 --age-estimate
```

Claude Haiku 5.5 reads it with the frozen prompt, the same call the benchmark makes (`lab2clock/read.py`; `--model` picks another model), and the code stages turn what it read into clock inputs. Or skip the model and run the code stages on a stage-1 JSON file, which lists every row as printed (name, value, unit, page):

```bash
uv run lab2clock tests/data/stage1_example.json --age 52
```

The output gives each clock input in the clock's unit with the row it was read from, plus the missing fields, every issue found, and the rows that matched no marker. Age is not read from the report, so pass it with `--age`. An analyte with an error is withheld rather than guessed. `--age-estimate` adds the PhenoAge the inputs give, when all ten are present, with a note that it is a statistical estimate from one blood test, not a diagnosis. When an input was printed below a limit, such as CRP `<5.00 mg/L`, the true value lies anywhere from the clock's lowest possible value up to the limit, so it gives the range of ages those values allow; a value printed above a limit is withheld, since it could be any amount higher. The exit status is 0 when the report is ok, 1 when it has errors, and 2 when the report could not be read.

## Setup

Python 3.12 is required ([pyaging](https://pyaging.readthedocs.io/en/latest/installation.html) needs 3.11 or newer). Recreate the locked environment with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

pyaging and its PyTorch dependency sit in a separate `clock` group, so CI and the conversion code do not need them. Add them when you want to run the clock itself:

```bash
uv sync --group clock
```
