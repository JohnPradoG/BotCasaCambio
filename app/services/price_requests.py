"""Pedido diario de precios a las casas que no los publican en internet.

El bot **no** escribe a las casas: arma, para cada casa sin precio reciente, un enlace de
WhatsApp con la pregunta ya escrita (o el teléfono para llamar) y te lo manda por
Telegram. Tú decides a quién enviarlo y cargas la respuesta con ``/precio``.

Se usa el WhatsApp publicado por la casa o la sucursal; si solo hay un teléfono móvil
(+56 9), se ofrece igual, indicando que puede no tener WhatsApp.
"""

from __future__ import annotations

import re
from datetime import date

from app.config.settings import Settings
from app.models.exchange_house import ExchangeHouse
from app.notifications.messages import whatsapp_link


def _is_mobile(number: str | None) -> bool:
    digits = re.sub(r"\D", "", number or "")
    return digits.startswith("569") and len(digits) == 11


def question(currencies: list[str]) -> str:
    return (f"Hola, ¿a cuánto están comprando y vendiendo hoy {', '.join(currencies)}? "
            "Es para cambiar en efectivo. Gracias.")


def build_price_request(houses: list[ExchangeHouse], fresh_slugs: set[str], settings: Settings) -> str | None:
    """Mensaje con un enlace por casa sin precio reciente. None si no hay a quién preguntar."""
    currencies = [c.strip().upper() for c in settings.price_request_currencies.split(",") if c.strip()]
    text = question(currencies)
    lines: list[str] = []
    for house in sorted(houses, key=lambda h: h.name.lower()):
        if house.slug in fresh_slugs:
            continue
        contacts = [(b.name, b.whatsapp, b.phone) for b in house.branches] or [(None, house.whatsapp, house.phone)]
        for branch_name, wa, phone in contacts:
            wa = wa or house.whatsapp
            phone = phone or house.phone
            where = f"{house.name}" + (f" · {branch_name}" if branch_name and len(house.branches) > 1 else "")
            if wa:
                lines.append(f"• {where}: {whatsapp_link(wa, text)}")
            elif _is_mobile(phone):
                lines.append(f"• {where}: {whatsapp_link(phone, text)} (móvil; puede no tener WhatsApp)")
            elif phone:
                lines.append(f"• {where}: llamar al {phone}")
            else:
                continue
            break  # una sucursal por casa basta para preguntar
    if not lines:
        return None
    header = (f"📋 Precios de hoy ({date.today():%d-%m})\n"
              f"Estas casas no publican precios en internet. Toca un enlace, envía la pregunta y "
              f"carga la respuesta con /precio <casa> <divisa> <compra> <venta>.\n")
    return header + "\n" + "\n".join(lines)
