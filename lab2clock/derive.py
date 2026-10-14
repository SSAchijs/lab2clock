"""Clock inputs computed from other printed values, when the input is not printed.

Some reports print only the absolute lymphocyte count, not the percent. The
percent is then count / white cells x 100. The arithmetic is exact, but the
value was not printed, so it carries derived=True and the fields it came from.
"""

from dataclasses import dataclass

from lab2clock.synonyms import LYMPHOCYTE_COUNT


class DerivationError(ValueError):
    """Inputs that cannot give a meaningful derived value."""


@dataclass(frozen=True)
class DerivedValue:
    """A clock input computed rather than printed.

    value: the number, in the clock's unit.
    sources: the analytes it was computed from.
    derived: always True; it is what the output shows.
    """

    value: float
    sources: tuple[str, ...]
    derived: bool = True


def lymphocyte_percent(count: float, white_cells: float) -> DerivedValue:
    """Lymphocyte percent from the absolute count and the white-cell count.

    Both values already converted by the conversion table, which puts them in
    the same unit, so their ratio needs no rescaling. Callers derive only
    from uncensored values: a detection limit in a ratio is not a number.

    Raises DerivationError when white cells are not positive, the count is
    negative, or the count exceeds white cells. A share above 100% means a
    misread, so it fails here instead of reaching the clock.
    """
    if white_cells <= 0:
        raise DerivationError(f"white cells must be positive, got {white_cells}")
    if count < 0:
        raise DerivationError(f"lymphocyte count is negative: {count}")
    if count > white_cells:
        raise DerivationError(
            f"lymphocyte count {count} exceeds white cells {white_cells}"
        )
    return DerivedValue(
        count / white_cells * 100,
        sources=(LYMPHOCYTE_COUNT, "white_blood_cell_count"),
    )
