import pytest

from lab2clock.values import ParsedValue, ValueParseError, parse_value


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        # Plain numbers.
        ("5.6", ParsedValue(5.6)),
        ("42", ParsedValue(42.0)),
        ("  6.0 ", ParsedValue(6.0)),
        ("0.04", ParsedValue(0.04)),
        # Decimal commas.
        ("5,6", ParsedValue(5.6)),
        ("0,123", ParsedValue(0.123)),
        ("12,3456", ParsedValue(12.3456)),
        # Thousands separators.
        ("12,345", ParsedValue(12345.0)),
        ("1,234,567", ParsedValue(1234567.0)),
        ("1.234.567", ParsedValue(1234567.0)),
        ("1,234.5", ParsedValue(1234.5)),
        ("1.234,5", ParsedValue(1234.5)),
        ("1 234", ParsedValue(1234.0)),
        ("1 234,5", ParsedValue(1234.5)),
        ("1'234", ParsedValue(1234.0)),
        # Flags.
        ("1.2 H", ParsedValue(1.2, flags=("H",))),
        ("1.2H", ParsedValue(1.2, flags=("H",))),
        ("3,1 L", ParsedValue(3.1, flags=("L",))),
        ("250 HH", ParsedValue(250.0, flags=("HH",))),
        ("6.0*", ParsedValue(6.0, flags=("*",))),
        ("12.3 (H)", ParsedValue(12.3, flags=("H",))),
        ("12.3 H*", ParsedValue(12.3, flags=("H", "*"))),
        ("8.9↑", ParsedValue(8.9, flags=("↑",))),
        ("2.1 ↓", ParsedValue(2.1, flags=("↓",))),
        # Censored values.
        ("<0.5", ParsedValue(0.5, censored=True)),
        ("< 0,5", ParsedValue(0.5, censored=True)),
        ("<=0.2", ParsedValue(0.2, censored=True)),
        ("≤0.2", ParsedValue(0.2, censored=True)),
        (">1000", ParsedValue(1000.0, censored=True)),
        (">1,000 H", ParsedValue(1000.0, censored=True, flags=("H",))),
        # Full-width characters, as on Chinese reports.
        ("５．６", ParsedValue(5.6)),
        ("＜０．５", ParsedValue(0.5, censored=True)),
        # Signs: parsed, so the plausibility checks can reject them visibly.
        ("-1.5", ParsedValue(-1.5)),
        ("−1.5", ParsedValue(-1.5)),
        ("+2", ParsedValue(2.0)),
    ],
)
def test_parses(printed, expected):
    assert parse_value(printed) == expected


@pytest.mark.parametrize(
    "printed",
    [
        "",
        "   ",
        "H",
        "positive",
        "see note",
        "--",
        "5.6.7",
        "1,23,456",
        "1,234,5",
        "1 23",
        "5.",
        ".5",
        "5-6",
        "+-5",
        "<",
        "1.2 X",
        "1'234 567",
        "5.6 mmol/L",
    ],
)
def test_refuses(printed):
    with pytest.raises(ValueParseError):
        parse_value(printed)


def test_error_message_quotes_the_printed_value():
    with pytest.raises(ValueParseError, match="'5.6.7'"):
        parse_value("5.6.7")
