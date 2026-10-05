"""Textos de alerta (SPEC §22) y de verificación por teléfono/WhatsApp (SPEC §20)."""

from __future__ import annotations

import re
from urllib.parse import quote as urlquote

from app.models.exchange_house import Branch, ExchangeHouse
from app.services.arbitrage_engine import Route
from app.services.report import clp, units

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
CONF_ES = {"HIGH": "🟢 ALTA", "MEDIUM": "🟡 MEDIA", "LOW": "🔴 BAJA"}


def _branch(directory: dict[str, ExchangeHouse], slug: str, branch_name: str | None) -> Branch | None:
    house = directory.get(slug)
    if not house:
        return None
    for b in house.branches:
        if b.name == branch_name:
            return b
    return house.branches[0] if house.branches else None


def _house_name(directory, slug: str) -> str:
    house = directory.get(slug)
    return house.name if house else slug


def _contact(directory, slug: str, branch_name: str | None) -> tuple[str, str, str]:
    house = directory.get(slug)
    b = _branch(directory, slug, branch_name)
    address = (b.address if b and b.address else None) or "no publicada"
    if b and b.comuna:
        address += f", {b.comuna}"
    phone = (b.phone if b and b.phone else None) or (house.phone if house else None) or "no publicado"
    wa = (b.whatsapp if b and b.whatsapp else None) or (house.whatsapp if house else None) or "no publicado"
    return address, phone, wa


def whatsapp_link(number: str | None, text: str) -> str | None:
    digits = re.sub(r"\D", "", number or "")
    return f"https://wa.me/{digits}?text={urlquote(text)}" if digits else None


def verification_messages(route: Route, directory: dict[str, ExchangeHouse]) -> list[dict]:
    """Un mensaje por operación para confirmar tasa, monto y disponibilidad antes de salir."""
    messages = []
    for step in route.route:
        if step.from_currency == "CLP":
            text = (
                f"Hola, quisiera cambiar aproximadamente {clp(step.amount_in)} CLP a {step.to_currency} en efectivo. "
                "¿Me pueden confirmar el tipo de cambio actual, el monto final que recibiría y si tienen "
                "disponibilidad para realizar la operación hoy?"
            )
        else:
            text = (
                f"Hola, ¿mantienen la tasa de {units(step.rate)} para un monto aproximado de "
                f"{step.from_currency} {units(step.amount_in)} a {step.to_currency}? "
                "¿Tienen disponibilidad para realizar la operación hoy?"
            )
        _, phone, wa = _contact(directory, step.house, step.branch_used)
        messages.append({
            "step": step.position,
            "house": _house_name(directory, step.house),
            "text": text,
            "phone": None if phone == "no publicado" else phone,
            "whatsapp_link": whatsapp_link(None if wa == "no publicado" else wa, text),
        })
    return messages


def _ago(minutes: float) -> str:
    return "hace menos de 1 min" if minutes < 1 else f"hace {minutes:.0f} min"


def format_alert_route(route: Route, directory: dict[str, ExchangeHouse], detailed: bool = True) -> str:
    medal = MEDALS.get(route.rank or 0, "•")
    if not detailed:
        lines = [
            f"{medal} OPCIÓN #{route.rank}",
            f"Ganancia: {clp(route.net_profit_clp, sign=True)}",
            f"Ruta: {' → '.join(route.currencies)}",
            f"Distancia: {'desconocida' if route.distance_km is None else f'{route.distance_km:.1f} km'.replace('.', ',')}",
            f"Tiempo: {'desconocido' if route.estimated_minutes is None else f'{route.estimated_minutes:.0f} min'}",
            f"Confianza: {CONF_ES.get(route.confidence or '', 'sin calcular')}",
        ]
        return "\n".join(lines)

    lines = [
        f"{medal} OPCIÓN #{route.rank}",
        "",
        "Ganancia estimada:",
        f"{clp(route.net_profit_clp, sign=True)} CLP",
        "",
        "Capital final:",
        f"{clp(route.net_final_clp)} CLP",
        "",
        "Ruta:",
    ]
    for i, step in enumerate(route.route):
        if i:
            lines += ["", "↓", ""]
        name = _house_name(directory, step.house) + (f" ({step.branch_used})" if step.branch_used else "")
        received = (f"CLP final: {clp(step.amount_out)}" if step.to_currency == "CLP"
                    else f"{step.to_currency} recibido: {units(step.amount_out)}")
        lines += [name, f"{step.from_currency} → {step.to_currency} a {units(step.rate)}", received]

    ages = [s.quote_age_minutes for s in route.route]
    lines += [
        "",
        f"Ganancia bruta: {clp(route.gross_profit_clp, sign=True)} · Comisiones: -{clp(route.commissions_clp)} · "
        f"Margen: -{clp(route.safety_margin_clp)} · Transporte: -{clp(route.transport_clp)}",
    ]
    if route.alt_transport:
        a = route.alt_transport
        lines.append(f"Si vas en {a['label']}: {clp(a['net_profit_clp'], sign=True)} CLP")
    lines += [
        "",
        "Distancia total:",
        "desconocida (faltan coordenadas)" if route.distance_km is None else f"{route.distance_km:.1f} km".replace(".", ","),
        "",
        "Tiempo estimado:",
        "desconocido" if route.estimated_minutes is None else f"{route.estimated_minutes:.0f} min",
        "",
        "Cotizaciones:",
        f"Actualizadas {_ago(min(ages))} a {_ago(max(ages))}" if ages else "sin datos",
        "",
        "Confianza:",
        f"{CONF_ES.get(route.confidence or '', 'sin calcular')}"
        + (f" ({route.confidence_score:.0f}/100)" if route.confidence_score is not None else ""),
    ]
    if route.executable_now is False:
        lines += ["", "⏰ Alguna casa está cerrada ahora: oportunidad para más tarde."]
    if route.requires_verification:
        lines += ["", "🚩 Usa una cotización sospechosa (posible error de publicación)."]
    lines += ["", "⚠️ Confirmar precios y disponibilidad antes de desplazarse."]

    seen = set()
    for step in route.route:
        key = (step.house, step.branch_used)
        if key in seen:
            continue
        seen.add(key)
        address, phone, wa = _contact(directory, step.house, step.branch_used)
        lines += ["", f"{_house_name(directory, step.house)}:", f"Dirección: {address}", f"Teléfono: {phone}",
                  f"WhatsApp: {wa}"]

    lines += ["", "Mensajes para verificar:"]
    for m in verification_messages(route, directory):
        lines.append(f"{m['step']}. {m['house']}: \"{m['text']}\"")
        if m["whatsapp_link"]:
            lines.append(f"   {m['whatsapp_link']}")
    return "\n".join(lines)


def format_alert(routes: list[Route], directory: dict[str, ExchangeHouse], initial_clp: float, market=None) -> str:
    parts = ["🔥 ARBITRAJE DETECTADO", "", "Capital inicial:", f"{clp(initial_clp)} CLP", ""]
    for i, route in enumerate(routes):
        parts.append(format_alert_route(route, directory, detailed=(i == 0)))
        parts.append("")
    if market is not None:  # referencia del dólar digital; no cambia el cálculo de la ruta
        from app.services.market_reference import reference_line

        parts.append(reference_line(market))
    return "\n".join(parts).rstrip()


def format_drop_alert(route_text: str, houses: str, notified_profit: float, current: Route | None,
                      notified_at_local: str, drop_percent: float) -> str:
    """Aviso de que una ruta ya alertada perdió ganancia (o dejó de existir)."""
    lines = ["⚠️ BAJÓ LA GANANCIA", "", f"Ruta: {route_text}", f"Casas: {houses}",
             f"Avisada: {clp(notified_profit, sign=True)} CLP ({notified_at_local})"]
    if current is None:
        lines.append("Ahora: una de las cotizaciones ya no está publicada o no aplica al monto.")
    elif current.net_profit_clp <= 0:
        lines.append(f"Ahora: {clp(current.net_profit_clp, sign=True)} CLP, ya no es rentable.")
    else:
        lines.append(f"Ahora: {clp(current.net_profit_clp, sign=True)} CLP (-{drop_percent:.0f}%)")
    lines += ["", "Revisa antes de desplazarte."]
    return "\n".join(lines)
