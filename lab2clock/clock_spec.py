"""The input contract of the target clock: original PhenoAge (Levine 2018) in pyaging.

This is the single source of truth for field names, target units and transforms.
Every other module takes them from here, so a wrong unit is fixed in one place.

Units were derived from running pyaging 0.5.7 and confirmed against the paper's
coefficients (see bench/phenoage.py). Unit strings are ASCII ("u", not the micro
sign or Greek mu), so the unit normaliser has one canonical spelling to map to.
"""

from dataclasses import dataclass
from math import inf

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
    error: (low, high) outside which a value has never been measured in any
        patient. Each high limit sits just above the most extreme published value
        found, rounded up; the source is cited beside it. A low of 0 means the
        marker can be near zero in real patients, so only a negative value fails.
        inf means no published extreme was found, so there is no high limit.
        None (age only) means no check.

    The error tier catches impossible values, not every unit slip. CRP left in
    mg/L, or glucose left in mg/dL, stays within these limits; the warning tier
    and the unit handling have to catch those.
    """

    name: str
    unit: str
    transform: str | None = None
    warn: Range | None = None
    error: Range | None = None


# In pyaging's feature order.
FIELDS: tuple[Field, ...] = (
    # High: no published extreme found. Above 50 g/L is usually dehydration.
    # Low: congenital analbuminemia gives < 1 g/L (Minchiotti 2019,
    # doi:10.3389/fgene.2019.00336).
    Field("albumin", "g/L", error=(0, inf)),
    # 73.8 mg/dL = 6525 umol/L (Persaud 2021, doi:10.1155/2021/6048919).
    Field("creatinine", "umol/L", error=(0, 7000)),
    # 148.46 mmol/L, Guinness World Records, highest blood sugar level (female),
    # Louisville, 21 August 2024.
    Field("glucose", "mmol/L", error=(0, 150)),
    # Raw CRP in mg/dL, not the mg/L most labs print. pyaging floors it at 0.01
    # and takes the natural log inside the clock.
    # 772 mg/L = 77.2 mg/dL, highest of 168 values >= 500 mg/L in 106,758 tests
    # (Hajek 2011, doi:10.1016/j.revmed.2011.04.001).
    Field(
        "c_reactive_protein",
        "mg/dL",
        transform="ln, floored at 0.01",
        error=(0, 80),
    ),
    # A share of white cells, so bounded by definition.
    Field("lymphocyte_percent", "%", error=(0, 100)),
    # Low: 44.5 fL in HbE/beta-thalassemia with iron deficiency (Goretti 2022,
    # doi:10.1016/j.amsu.2022.103826). High: 136.9 fL in pernicious anemia
    # (Akinola 2026, doi:10.7759/cureus.101860).
    Field("mean_cell_volume", "fL", error=(40, 150)),
    # High: no published extreme found.
    Field("red_cell_distribution_width", "%", error=(0, inf)),
    # 11,900 U/L in benign transient hyperphosphatasemia of infancy (Eymann
    # 2010, doi:10.1515/jpem.2010.148).
    Field("alkaline_phosphatase", "U/L", error=(0, 12000)),
    # 10^3 cells/uL equals the 10^9/L labs print, so no rescaling.
    # 1360 x 10^9/L in CLL with leukostasis (Atwal 2017,
    # doi:10.4103/ajm.AJM_171_16).
    Field("white_blood_cell_count", "10^3/uL", error=(0, 1500)),
    Field("age", "years"),
)

FIELD_NAMES: tuple[str, ...] = tuple(field.name for field in FIELDS)

# The nine blood markers read from the report; age comes from elsewhere.
MARKERS: tuple[str, ...] = tuple(name for name in FIELD_NAMES if name != "age")

BY_NAME: dict[str, Field] = {field.name: field for field in FIELDS}
