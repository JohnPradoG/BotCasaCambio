import pytest

from app.models.currency import normalize_currency_code
from app.scrapers.normalization import RateParseError, classify_rate_label, parse_rate


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$ 1.030", 1030.0),
        ("1.030.500", 1030500.0),
        ("950,50", 950.5),
        ("1.030,25", 1030.25),
        ("1,030.25", 1030.25),
        ("950.5", 950.5),
        ("0.245", 0.245),
        ("0,245", 0.245),
        ("6,51", 6.51),
        (970, 970.0),
        ("—", None),
        ("", None),
    ],
)
def test_parse_rate(raw, expected):
    assert parse_rate(raw) == expected


def test_parse_rate_explicit_separator():
    assert parse_rate("950.500", decimal_separator=".") == 950.5
    assert parse_rate("1,030", decimal_separator=".") == 1030.0


def test_parse_rate_ambiguous_comma_raises():
    with pytest.raises(RateParseError):
        parse_rate("1,030")


@pytest.mark.parametrize(
    "label, side",
    [
        # Punto de vista de la casa
        ("Compra", "buy"),
        ("COMPRAMOS", "buy"),
        ("Compro", "buy"),
        ("Venta", "sell"),
        ("Vendo", "sell"),
        ("Vendemos", "sell"),
        ("buy_rate", "buy"),
        ("sell", "sell"),
        # Punto de vista del cliente: se invierte
        ("Usted compra", "sell"),
        ("Tú compras", "sell"),
        ("Usted vende", "buy"),
        ("Tú vendes", "buy"),
        # Ambiguo => None (mejor no usar el dato que confundirlo)
        ("Compra/Venta", None),
        ("Precio", None),
    ],
)
def test_classify_rate_label(label, side):
    assert classify_rate_label(label) == side


@pytest.mark.parametrize(
    "raw, code",
    [
        ("USD", "USD"),
        ("usd", "USD"),
        ("Dólar", "USD"),
        ("Dólar Americano", "USD"),
        ("Euro", "EUR"),
        ("Real Brasileño", "BRL"),
        ("Sol", "PEN"),
        ("Dólar (USD)", "USD"),
        ("XAU", "XAU"),  # divisa nueva en mayúsculas: se acepta (SPEC §3)
        ("Hoy", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_currency_code(raw, code):
    assert normalize_currency_code(raw) == code
