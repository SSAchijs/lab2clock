"""The input contract of the target clock: original PhenoAge (Levine 2018) in pyaging.

This is the single source of truth for field names, target units and transforms.
Every other module takes them from here, so a wrong unit is fixed in one place.

Units were derived from running pyaging 0.5.7 and confirmed against the paper's
coefficients (see bench/phenoage.py). Unit strings are ASCII ("u", not the micro
sign or Greek mu), so the unit normaliser has one canonical spelling to map to.
"""

from dataclasses import dataclass

Range = tuple[float, float]


@dataclass(frozen=True)
class Field:
    """One clock input.

    name: pyaging's column name.
    unit: the unit the clock expects, in canonical spelling.
    transform: what the clock applies to the value itself, or None. lab2clock
        never applies it; it delivers the raw value in `unit`.
    warn: (low, high) outside which a value is unusual but possible: the 0.5th
        and 99.5th NHANES adult percentiles. None until computed.
    error: (low, high) outside which a value is physiologically implausible,
        hand-set with a cited source. None until set.
    """

    name: str
    unit: str
    transform: str | None = None
    warn: Range | None = None
    error: Range | None = None


# In pyaging's feature order.
FIELDS: tuple[Field, ...] = (
    Field("albumin", "g/L"),
    Field("creatinine", "umol/L"),
    Field("glucose", "mmol/L"),
    # Raw CRP in mg/dL, not the mg/L most labs print. pyaging floors it at 0.01
    # and takes the natural log inside the clock.
    Field("c_reactive_protein", "mg/dL", transform="ln, floored at 0.01"),
    Field("lymphocyte_percent", "%"),
    Field("mean_cell_volume", "fL"),
    Field("red_cell_distribution_width", "%"),
    Field("alkaline_phosphatase", "U/L"),
    # 10^3 cells/uL equals the 10^9/L labs print, so no rescaling.
    Field("white_blood_cell_count", "10^3/uL"),
    Field("age", "years"),
)

FIELD_NAMES: tuple[str, ...] = tuple(field.name for field in FIELDS)

# The nine blood markers read from the report; age comes from elsewhere.
MARKERS: tuple[str, ...] = tuple(name for name in FIELD_NAMES if name != "age")

BY_NAME: dict[str, Field] = {field.name: field for field in FIELDS}
