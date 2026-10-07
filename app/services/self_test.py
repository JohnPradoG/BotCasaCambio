"""``/prueba``: demuestra que el motor y las alertas funcionan, con casas y precios de ejemplo.

Las dos casas de ejemplo son ficticias ("Casa Ejemplo A/B"), sus precios no se guardan
en la base y el mensaje lo dice en la primera línea: nunca se mezcla con datos reales.
Después agrega el estado real: cuántas rutas con ganancia hay con los precios guardados
y qué tan cerca está la mejor divisa.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.models.quote import NormalizedQuote
from app.notifications.messages import format_alert
from app.services.arbitrage_engine import find_best_routes

EXAMPLE_URL = "ejemplo://prueba"  # no es una casa real


def example_quotes() -> list[NormalizedQuote]:
    """A vende el dólar a 960 y B lo compra a 980: una diferencia que sí deja ganancia."""
    return [
        NormalizedQuote(exchange_house="ejemplo_a", currency="USD", buy_rate=940, sell_rate=960,
                        source_url=EXAMPLE_URL, notes="ejemplo ficticio"),
        NormalizedQuote(exchange_house="ejemplo_b", currency="USD", buy_rate=980, sell_rate=1000,
                        source_url=EXAMPLE_URL, notes="ejemplo ficticio"),
    ]


def example_alert(settings: Settings) -> str:
    routes = find_best_routes(example_quotes(), initial_amount=settings.initial_capital_clp, settings=settings)
    if not routes:
        return "⚠️ PRUEBA: el motor no encontró la ruta de ejemplo. Avísale a Claude."
    text = format_alert(routes[:1], {}, settings.initial_capital_clp)
    text = text.replace("ejemplo_a", "Casa Ejemplo A").replace("ejemplo_b", "Casa Ejemplo B")
    return ("🧪 PRUEBA: casas y precios INVENTADOS, no son reales y no se guardan.\n"
            "Así se ve una alerta cuando aparece un arbitraje:\n\n" + text)


def real_status(routes_found: int, min_profit: float, margin: float, near_line: str | None) -> str:
    lines = ["", "📌 Con los precios REALES de ahora:"]
    lines.append(f"• Rutas con ganancia: {routes_found}" + (" (te llegaría alerta)" if routes_found else ""))
    lines.append(f"• Aviso desde: ${min_profit:,.0f} · margen de seguridad: {margin:g} %".replace(",", "."))
    if near_line:
        lines.append(f"• Lo más cerca: {near_line.lstrip('• ')}")
    if min_profit > 0 or margin > 0:
        lines.append("⚠️ El servidor todavía descuenta margen o pide un mínimo: falta pegar la línea de actualización.")
    return "\n".join(lines)
