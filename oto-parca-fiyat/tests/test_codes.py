import pytest

from parcabul.codes import format_price, normalize_code, parse_price


@pytest.mark.parametrize("raw", ["8200 768 913", "8200-768-913", "8200.768.913", " 8200768913 "])
def test_normalize_code_same_part(raw):
    assert normalize_code(raw) == "8200768913"


def test_normalize_code_turkish_letters():
    assert normalize_code("şğı-ü1") == "SGIU1"


@pytest.mark.parametrize("text,kurus", [
    ("1.234,56 TL", 123456), ("₺899,90", 89990), ("1234.5", 123450), ("1,234.56", 123456),
    ("2.500", 250000), ("2,500", 250000), ("365,00", 36500), (412.5, 41250), ("abc", None), (None, None),
])
def test_parse_price(text, kurus):
    assert parse_price(text) == kurus


def test_format_price():
    assert format_price(123456) == "1.234,56 TL"
    assert format_price(5) == "0,05 TL"
