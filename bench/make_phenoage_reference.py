"""Regenerate tests/data/phenoage_reference.csv from pyaging.

Runs pyaging's PhenoAge on its blood_chemistry_example data (30 NHANES 2007
adults) and saves the 10 inputs with pyaging's output, so CI can check
bench.phenoage against pyaging without installing it.

Needs the clock group and network access to Hugging Face:

    uv run --group clock python -m bench.make_phenoage_reference
"""

import tempfile
from importlib.metadata import version
from pathlib import Path

import pandas as pd
import pyaging as pya

from lab2clock.clock_spec import FIELD_NAMES

OUT = Path(__file__).resolve().parents[1] / "tests" / "data" / "phenoage_reference.csv"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = pya.data.download_example_data(
            "blood_chemistry_example", dir=tmp, verbose=False
        )
        df = pd.read_pickle(path)
        adata = pya.pp.df_to_adata(df, verbose=False)
        pya.pred.predict_age(adata, ["phenoage"], dir=tmp, verbose=False)

    out = df[list(FIELD_NAMES)].copy()
    out["phenoage_pyaging"] = adata.obs["phenoage"].to_numpy()
    out.index.name = "sample"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        f.write(f"# pyaging {version('pyaging')}, blood_chemistry_example\n")
        out.to_csv(f)
    print(f"wrote {len(out)} rows to {OUT}")


if __name__ == "__main__":
    main()
