from pathlib import Path

from app.scrapers.exchanges.afex import extract_rates_from_html
from app.scrapers.extractors import find_inline_rates, find_rate_records, parse_html_rate_table

FIX = Path(__file__).parent / "fixtures"


def as_map(rates):
    return {r.currency: (r.buy_rate, r.sell_rate) for r in rates}


def test_json_records():
    rates, method = extract_rates_from_html((FIX / "next_data.html").read_text())
    assert method == "next_data_json"
    assert as_map(rates) == {"USD": (940.0, 970.0), "EUR": (1010.0, 1060.0), "BRL": (160.5, 178.0)}


def test_table_with_client_perspective_labels_is_inverted():
    # "Usted vende" = la casa compra => buy_rate; "Usted compra" => sell_rate.
    assert as_map(parse_html_rate_table((FIX / "table.html").read_text())) == {
        "USD": (940.0, 970.0),
        "EUR": (1010.0, 1060.0),
    }


def test_inline_rendered_text():
    rates, method = extract_rates_from_html((FIX / "rendered_inline.html").read_text())
    assert method == "inline_text"
    assert as_map(rates) == {"USD": (940.0, 970.0)}


def test_inline_needs_a_currency():
    assert find_inline_rates("Compra 940 · Venta 970") == []


def test_inline_order_independent():
    assert as_map(find_inline_rates("Euro: Venta 1.060 / Compra 1.010")) == {"EUR": (1010.0, 1060.0)}


def test_placeholder_page_yields_nothing():
    html = "<p>Dólar hoy en AFEX</p><p>Compra — · Venta —</p><p>actualizando…</p>"
    assert extract_rates_from_html(html) == ([], "none")


def test_json_ignores_objects_without_currency():
    assert find_rate_records({"compra": 1, "venta": 2}) == []
