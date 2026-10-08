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


OLD_PRICE_MINUTES = 24 * 60  # igual que MAX_QUOTE_USABLE_HOURS por defecto


def _ago(minutes: float) -> str:
    if minutes < 1:
        return "hace menos de 1 min"
    if minutes < 120:
        return f"hace {minutes:.0f} min"
    if minutes < 48 * 60:
        return f"hace {minutes / 60:.0f} h"
    return f"hace {minutes / 1440:.0f} días"


def _step_line(i: int, step, directory) -> str:
    name = _house_name(directory, step.house) + (f" ({step.branch_used})" if step.branch_used else "")
    if step.from_currency == "CLP":
        action = f"compra {step.to_currency} a {units(step.rate)} → {units(step.amount_out)} {step.to_currency}"
    elif step.to_currency == "CLP":
        action = f"vende {step.from_currency} a {units(step.rate)} → {clp(step.amount_out)}"
    else:
        action = (f"cambia {step.from_currency} a {step.to_currency} a {units(step.rate)} → "
                  f"{units(step.amount_out)} {step.to_currency}")
    return f"{i}) {name}: {action}"


def _houses(route: Route, directory) -> str:
    names: list[str] = []
    for step in route.route:
        name = _house_name(directory, step.house)
        if not names or names[-1] != name:
            names.append(name)
    return " → ".join(names)


def _price_currency(step) -> str:
    return step.from_currency if step.to_currency == "CLP" else step.to_currency


def format_alert_route(route: Route, directory: dict[str, ExchangeHouse], detailed: bool = True) -> str:
    """Una ruta en pocas líneas (John, 2026-10-08: la alerta era muy larga para Telegram)."""
    conf = CONF_ES.get(route.confidence or "", "sin calcular")
    if not detailed:
        medal = MEDALS.get(route.rank or 0, "•")
        return (f"{medal} {clp(route.net_profit_clp, sign=True)}: {_houses(route, directory)} "
                f"({' → '.join(route.currencies)}) · {conf}")

    lines = [_step_line(i, step, directory) for i, step in enumerate(route.route, 1)]
    costs = [(label, value) for label, value in (("comisiones", route.commissions_clp),
                                                  ("margen", route.safety_margin_clp),
                                                  ("transporte", route.transport_clp)) if value]
    if costs:
        lines.append(f"Bruto {clp(route.gross_profit_clp, sign=True)} · "
                     + " · ".join(f"{label} -{clp(value)}" for label, value in costs))
    if route.alt_transport:
        a = route.alt_transport
        lines.append(f"Si vas en {a['label']}: {clp(a['net_profit_clp'], sign=True)}")
    where = []
    if route.distance_km is not None:
        where.append(f"{route.distance_km:.1f} km".replace(".", ","))
    if route.estimated_minutes is not None:
        where.append(f"{route.estimated_minutes:.0f} min")
    if where:
        lines.append("📍 " + " · ".join(where))
    lines.append(f"Confianza: {conf}"
                 + (f" ({route.confidence_score:.0f}/100)" if route.confidence_score is not None else ""))
    for step in route.route:
        if step.quote_age_minutes > OLD_PRICE_MINUTES:
            lines.append(f"📅 {_house_name(directory, step.house)} publicó su precio de {_price_currency(step)} "
                         f"{_ago(step.quote_age_minutes)}: puede seguir igual, confírmalo.")
    if route.executable_now is False:
        lines.append("⏰ Alguna casa está cerrada ahora: es para más tarde.")
    if route.requires_verification:
        lines.append("🚩 Un precio parece error de publicación.")

    seen = set()
    for step in route.route:
        key = (step.house, step.branch_used)
        if key in seen:
            continue
        seen.add(key)
        address, phone, wa = _contact(directory, step.house, step.branch_used)
        known = [v for v in (phone if phone != "no publicado" else None,
                             f"WhatsApp {wa}" if wa != "no publicado" and wa != phone else None,
                             address if not address.startswith("no publicada") else None) if v]
        lines.append(f"📞 {_house_name(directory, step.house)}: "
                     + (" · ".join(known) if known else "sin teléfono ni dirección publicados"))
    lines.append("⚠️ Confirma precio y disponibilidad antes de ir.")
    return "\n".join(lines)


def format_alert(routes: list[Route], directory: dict[str, ExchangeHouse], initial_clp: float, market=None) -> str:
    if not routes:
        return "🔥 ARBITRAJE: sin rutas"
    parts = [f"🔥 ARBITRAJE: {clp(routes[0].net_profit_clp, sign=True)} con {clp(initial_clp)}",
             format_alert_route(routes[0], directory, detailed=True)]
    if len(routes) > 1:
        parts += ["", "Otras opciones:"] + [format_alert_route(r, directory, detailed=False) for r in routes[1:]]
    if market is not None:  # referencia del dólar digital; no cambia el cálculo de la ruta
        from app.services.market_reference import reference_line

        parts += ["", reference_line(market)]
    return "\n".join(parts)


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
