"""Normalización de códigos de divisa.

No limitamos el sistema a una lista fija (SPEC §3): cualquier código ISO 4217 de
3 letras es aceptado. La tabla de alias solo traduce los nombres en español que
suelen publicar las casas de cambio.
"""

from __future__ import annotations

import re
import unicodedata

BASE_CURRENCY = "CLP"

# Nombres frecuentes en sitios chilenos -> código ISO 4217.
_ALIASES: dict[str, str] = {
    "dolar": "USD",
    "dolar americano": "USD",
    "dolar estadounidense": "USD",
    "dolar usa": "USD",
    "dolares": "USD",
    "us dollar": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "libra": "GBP",
    "libra esterlina": "GBP",
    "dolar canadiense": "CAD",
    "dolar australiano": "AUD",
    "dolar neozelandes": "NZD",
    "franco suizo": "CHF",
    "yen": "JPY",
    "yen japones": "JPY",
    "real": "BRL",
    "real brasileno": "BRL",
    "reales": "BRL",
    "peso argentino": "ARS",
    "sol": "PEN",
    "sol peruano": "PEN",
    "nuevo sol": "PEN",
    "peso colombiano": "COP",
    "peso mexicano": "MXN",
    "peso uruguayo": "UYU",
    "boliviano": "BOB",
    "yuan": "CNY",
    "yuan chino": "CNY",
    "renminbi": "CNY",
    "won": "KRW",
    "won coreano": "KRW",
    "corona sueca": "SEK",
    "corona noruega": "NOK",
    "corona danesa": "DKK",
    "peso chileno": "CLP",
    "pesos chilenos": "CLP",
}

_ISO_RE = re.compile(r"^[A-Z]{3}$")

KNOWN_CODES = set(_ALIASES.values()) | {"HKD", "SGD", "ILS", "INR", "TRY", "ZAR", "PYG", "VES", "RUB", "THB", "AED"}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize_currency_code(raw: str | None) -> str | None:
    """Devuelve el código ISO de 3 letras, o None si no se puede determinar con certeza."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    key = re.sub(r"\s+", " ", _strip_accents(text).lower()).strip(" .:")
    if key in _ALIASES:  # antes que el código: "Sol" es PEN, no "SOL"
        return _ALIASES[key]
    upper = text.upper()
    # Códigos conocidos en cualquier capitalización; códigos nuevos solo si vienen
    # en mayúsculas (evita que palabras como "Hoy" se lean como divisa).
    if _ISO_RE.match(upper) and (upper in KNOWN_CODES or text == upper):
        return upper
    # "USD - Dólar", "Dólar (USD)", etc.
    match = re.search(r"\b([A-Z]{3})\b", text)
    if match and match.group(1) in KNOWN_CODES:
        return match.group(1)
    return None
