from app.config.settings import Settings
from app.models.quote import NormalizedQuote
from app.services.arbitrage_engine import find_best_routes
from app.services.report import clp, format_top


def test_clp_format():
    assert clp(1068000) == "$1.068.000"
    assert clp(65000, sign=True) == "+$65.000"
    assert clp(-2000, sign=True) == "-$2.000"


def test_format_top_spec_46():
    quotes = [
        NormalizedQuote("a", "USD", 930.0, 950.0, "test://").validate(),
        NormalizedQuote("b", "USD", 980.0, 1000.0, "test://").validate(),
    ]
    routes = find_best_routes(quotes, initial_amount=1_000_000, settings=Settings(_env_file=None, safety_margin_percent=0))
    text = format_top(routes, 1_000_000)
    assert "CAPITAL INICIAL\n$1.000.000 CLP" in text
    assert "🥇 #1" in text and "Ruta: CLP → USD → CLP" in text and "Casas: a → b" in text
    assert "Ganancia neta: +$31.579" in text


def test_format_top_empty():
    assert "No se encontraron rutas" in format_top([], 1_000_000)
