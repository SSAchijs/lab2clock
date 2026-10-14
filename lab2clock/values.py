"""The value parser: turns a value string as printed into a number.

Stage 1 hands over values exactly as printed, so this is where 5,6 becomes 5.6.
Anything the parser cannot read with certainty raises ValueParseError rather
than guessing, because a refused value is visible and a wrong one is not.

Separator rules, in order:
- A comma and a dot together: whichever comes last is the decimal mark, so
  1,234.5 and 1.234,5 are both 1234.5.
- Several commas, several dots, or spaces: thousands separators, which must
  split the digits into groups of three.
- One comma: a decimal mark (5,6 is 5.6), except before exactly three digits
  with a nonzero integer part, where it is a thousands separator (12,345 is
  12345). Results printed to three decimals are rare; white-cell counts in
  cells/uL are not. A wrong guess is a factor of 1000, which the plausibility
  checks catch.
- One dot: a decimal mark.
"""

import re
import unicodedata
from dataclasses import dataclass


class ValueParseError(ValueError):
    """A printed value that cannot be read as one number."""


@dataclass(frozen=True)
class ParsedValue:
    """A number read from a printed value.

    value: the number. For a censored value, the detection limit.
    censored: True when printed as below or above a limit (<0.5, >1000). CRP
        is often below detection and PhenoAge takes its log, so zero would be
        unusable; the limit stands in, and this flag keeps that visible.
    flags: the abnormal-result flags printed after the number, in order.
    decimals: digits printed after the decimal mark. The printed value was
        rounded to them, which the cross-field checks need to know.
    """

    value: float
    censored: bool = False
    flags: tuple[str, ...] = ()
    decimals: int = 0


# Trailing flags. Letters may be wrapped in brackets, as in 1.2 (H).
_FLAG = re.compile(r"\s*(\((?:HH|LL|H|L)\)|HH|LL|H|L|[*!↑↓])$")
_COMPARATOR = re.compile(r"^(<=|>=|<|>|≤|≥)\s*")
_NUMBER = re.compile(r"^[+-]?\d[\d.,' ]*$")


def _grouped(digits: str, sep: str) -> bool:
    """Whether `sep` splits `digits` into thousands groups: 1,234,567."""
    return re.fullmatch(rf"\d{{1,3}}(?:{re.escape(sep)}\d{{3}})+", digits) is not None


def _to_float(number: str) -> tuple[float, int]:
    """The number and its count of decimals."""
    sign = "-" if number.startswith("-") else ""
    digits = number.lstrip("+-")

    integer, decimal_mark, fraction = digits, "", ""
    if "," in digits and "." in digits:
        decimal_mark = max((",", "."), key=digits.rfind)
    elif digits.count(",") == 1:
        head, tail = digits.split(",")
        if not (len(tail) == 3 and head.isdigit() and head.strip("0")):
            decimal_mark = ","
    elif digits.count(".") == 1:
        decimal_mark = "."

    if decimal_mark:
        integer, _, fraction = digits.rpartition(decimal_mark)
        if not fraction.isdigit():
            raise ValueParseError("nothing after the decimal mark")

    separators = set(re.sub(r"\d", "", integer))
    if len(separators) > 1:
        raise ValueParseError("mixed thousands separators")
    if separators and not _grouped(integer, separators.pop()):
        raise ValueParseError("thousands separators not in groups of three")

    value = float(f"{sign}{re.sub(r'\D', '', integer)}.{fraction or '0'}")
    return value, len(fraction)


def parse_value(printed: str) -> ParsedValue:
    """Read one printed value. Raises ValueParseError if it is not one number."""
    # NFKC turns full-width digits and signs into ASCII and odd spaces into
    # plain ones; the Unicode minus sign it leaves alone.
    text = unicodedata.normalize("NFKC", printed).replace("−", "-").strip()

    flags: list[str] = []
    while match := _FLAG.search(text):
        if match.start() == 0:
            break  # A flag with no number before it, such as a lone "H".
        flags.insert(0, match.group(1).strip("()"))
        text = text[: match.start()]

    censored = False
    if match := _COMPARATOR.match(text):
        censored = True
        text = text[match.end() :]

    if not _NUMBER.match(text):
        raise ValueParseError(f"not a number: {printed!r}")
    try:
        number, decimals = _to_float(text)
    except ValueParseError as error:
        raise ValueParseError(f"{error}: {printed!r}") from None
    return ParsedValue(number, censored, tuple(flags), decimals)
