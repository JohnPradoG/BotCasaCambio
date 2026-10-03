"""Normalización de números y del significado de "compra"/"venta" (SPEC §8).

Regla de oro: ``buy_rate`` es lo que la casa PAGA por la divisa y ``sell_rate``
lo que la casa COBRA por ella. Algunos sitios escriben desde el punto de vista
del cliente ("Usted compra", "Tú vendes"); esas etiquetas se invierten aquí, en
un único lugar, para que ningún scraper tenga que razonarlo por su cuenta.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

RateSide = Literal["buy", "sell"]


class RateParseError(ValueError):
    pass


def _clean_label(label: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFD", label) if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s_]+", " ", text.lower()).strip(" :.-")


# Etiquetas escritas desde el punto de vista del CLIENTE: van primero porque
# contienen las mismas raíces ("compr", "vend") con el significado opuesto.
_CLIENT_BUYS = re.compile(r"\b(usted compra|tu compras|cliente compra|compras|compre|you buy)\b")
_CLIENT_SELLS = re.compile(r"\b(usted vende|tu vendes|cliente vende|vendes|venda|you sell)\b")
# Etiquetas desde el punto de vista de la CASA.
_HOUSE_BUYS = re.compile(r"\b(compra|compro|compramos|comprador|buy|bid|we buy)\b")
_HOUSE_SELLS = re.compile(r"\b(venta|vendo|vendemos|vendedor|sell|ask|offer|we sell)\b")


def classify_rate_label(label: str) -> RateSide | None:
    """Traduce una etiqueta publicada a ``"buy"`` o ``"sell"`` según la convención estándar.

    Devuelve None si la etiqueta es ambigua: es preferible no usar el dato a
    confundir compra con venta.
    """
    text = _clean_label(label)
    if not text:
        return None
    client_buys = bool(_CLIENT_BUYS.search(text))
    client_sells = bool(_CLIENT_SELLS.search(text))
    if client_buys != client_sells:
        # El cliente compra divisa => la casa la vende => sell_rate.
        return "sell" if client_buys else "buy"
    if client_buys and client_sells:
        return None
    house_buys = bool(_HOUSE_BUYS.search(text))
    house_sells = bool(_HOUSE_SELLS.search(text))
    if house_buys == house_sells:
        return None
    return "buy" if house_buys else "sell"


def parse_rate(raw: str | float | int | None, decimal_separator: str | None = None) -> float | None:
    """Convierte un precio publicado a float.

    Formatos chilenos habituales: ``"$ 1.030"`` (mil treinta), ``"950,50"``,
    ``"1.030,25"``. También ``"950.5"`` o ``"0.245"``.

    Si el formato de una casa es ambiguo, el scraper debe pasar
    ``decimal_separator`` explícitamente.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = raw.strip()
    if text in {"", "-", "—", "–", "N/A", "n/a", "s/i", "S/I"}:
        return None
    text = re.sub(r"[^\d.,\-]", "", text)
    if not re.search(r"\d", text):
        raise RateParseError(f"sin dígitos: {raw!r}")
    if text.startswith("-"):
        raise RateParseError(f"precio negativo: {raw!r}")

    if decimal_separator in {".", ","}:
        thousands = "," if decimal_separator == "." else "."
        text = text.replace(thousands, "").replace(decimal_separator, ".")
        return float(text)

    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        # El separador que aparece último es el decimal.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        parts = text.split(",")
        if len(parts) > 2 or (len(parts[1]) == 3 and parts[0] not in {"", "0"}):
            raise RateParseError(f"formato ambiguo (¿coma de miles?): {raw!r}; indicar decimal_separator")
        text = text.replace(",", ".")
    elif has_dot:
        parts = text.split(".")
        integer, *rest = parts
        # "1.030" o "1.030.500" => separador de miles (formato chileno).
        if integer not in {"", "0"} and all(len(p) == 3 for p in rest):
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError as exc:
        raise RateParseError(f"no se pudo interpretar {raw!r}") from exc
