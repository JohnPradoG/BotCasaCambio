"""Confianza de ejecución (SPEC §19, §34, §36).

La puntuación (0-100) es SOLO un indicador: nunca cambia el orden del Top N, que
siempre es por ganancia neta. Cada descuento queda explicado en ``reasons``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config.settings import Settings

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"


@dataclass
class Confidence:
    score: float
    level: str
    reasons: list[str] = field(default_factory=list)


def assess(route, settings: Settings) -> Confidence:
    from app.services.arbitrage_engine import sensitivity

    score = 100.0
    reasons: list[str] = []
    cap = 100.0

    def penalty(points: float, why: str) -> None:
        nonlocal score
        if points > 0:
            score -= points
            reasons.append(f"-{points:.0f}: {why}")

    # Antigüedad de cada cotización.
    stale = [s for s in route.route if s.quote_age_minutes > settings.max_quote_age_minutes]
    if stale:
        oldest = max(s.quote_age_minutes for s in stale)
        penalty(min(40, 12 * len(stale)), f"{len(stale)} cotización(es) con más de {settings.max_quote_age_minutes} min "
                                          f"(la más antigua {oldest:.0f} min)")
        cap = min(cap, 74)  # una cotización antigua nunca es confianza ALTA
    old = [s for s in route.route if s.quote_age_minutes > settings.max_quote_usable_hours * 60]
    if old:  # precio publicado hace días: puede seguir igual, pero hay que confirmarlo
        reasons.append(f"{len(old)} precio(s) publicados hace más de {settings.max_quote_usable_hours:g} h")
        cap = min(cap, 49)

    # Distancia / tiempo: más tiempo, más riesgo de que cambie la cotización.
    if route.estimated_minutes is None:
        penalty(10, "distancia/tiempo desconocidos (faltan coordenadas)")
    elif route.estimated_minutes > 10:
        penalty(min(25, (route.estimated_minutes - 10) / 2), f"{route.estimated_minutes:.0f} min de traslado y atención")

    if route.steps > 2:
        penalty(3 * (route.steps - 2), f"{route.steps} operaciones")

    if "COMMISSION_UNKNOWN" in route.flags:
        penalty(10, "comisión no publicada")
    if "AVAILABILITY_UNKNOWN" in route.flags:
        penalty(5, "disponibilidad no publicada")

    if route.executable_now is False:
        penalty(20, "alguna casa está cerrada ahora")
    elif route.executable_now is None:
        penalty(5, "horario desconocido")

    if "ANOMALOUS_QUOTE" in route.flags or "INVERTED_SPREAD" in route.flags:
        penalty(40, "usa una cotización sospechosa (ANOMALOUS_QUOTE / INVERTED_SPREAD)")
        cap = min(cap, 49)
    if "AUTO_DISCOVERED" in route.flags:
        penalty(20, "usa precios leídos automáticamente de una web sin scraper revisado")
        cap = min(cap, 74)

    if sensitivity(route, (0.005,))[0.005] <= 0:
        penalty(10, "deja de ser rentable si las tasas empeoran 0,5%")

    score = max(0.0, min(score, cap))
    level = HIGH if score >= 75 else MEDIUM if score >= 50 else LOW
    return Confidence(score=round(score, 1), level=level, reasons=reasons)
