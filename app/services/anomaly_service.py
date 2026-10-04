"""Detección de cotizaciones sospechosas (SPEC §35).

Una cotización se marca ``ANOMALOUS_QUOTE`` cuando su precio medio se aleja más
de ``ANOMALY_THRESHOLD_PERCENT`` de la mediana de las OTRAS casas para la misma
divisa. Con menos de ``ANOMALY_MIN_PEERS`` casas para comparar no se marca nada:
no hay base para decidir. La cotización se guarda igual; solo queda señalada
para que el motor la trate con baja confianza y se pida verificación.
"""

from __future__ import annotations

from statistics import median
from typing import Iterable

from app.models.quote import NormalizedQuote, QuoteFlag


def detect_anomalies(
    quotes: Iterable[NormalizedQuote],
    peer_mids: dict[str, dict[str, float]] | None = None,
    threshold_percent: float = 15.0,
    min_peers: int = 3,
) -> list[NormalizedQuote]:
    """Marca las cotizaciones anómalas en el lugar y devuelve las marcadas.

    ``peer_mids``: precios medios recientes ya conocidos, ``{divisa: {casa: mid}}``;
    se combinan con los del lote actual (el lote actual tiene prioridad).
    """
    quotes = list(quotes)
    mids: dict[str, dict[str, float]] = {c: dict(h) for c, h in (peer_mids or {}).items()}
    for q in quotes:
        if q.mid_rate is not None:
            mids.setdefault(q.currency, {})[q.exchange_house] = q.mid_rate

    flagged: list[NormalizedQuote] = []
    for q in quotes:
        if q.mid_rate is None:
            continue
        others = [m for house, m in mids.get(q.currency, {}).items() if house != q.exchange_house]
        if len(others) < min_peers:
            continue
        ref = median(others)
        if ref <= 0:
            continue
        deviation = abs(q.mid_rate / ref - 1) * 100
        if deviation > threshold_percent:
            q.flags.add(QuoteFlag.ANOMALOUS_QUOTE)
            note = f"desvío {deviation:.1f}% vs mediana {ref:.4g} de {len(others)} casas"
            q.notes = f"{q.notes}; {note}" if q.notes else note
            flagged.append(q)
    return flagged
