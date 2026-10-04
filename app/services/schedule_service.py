"""Horarios de atención (SPEC §15, §37).

Solo se usa el horario estructurado (``Branch.schedule``) que se haya cargado a
partir de una fuente. Si un día no está informado el resultado es ``None``
(desconocido), nunca se asume que la casa está abierta o cerrada.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _parse(value: str) -> time:
    hour, minute = value.strip().split(":")
    return time(int(hour), int(minute))


def is_open(schedule: dict | None, when: datetime, tz: str = "America/Santiago") -> bool | None:
    """True/False si el horario del día es conocido; None si no hay información."""
    if not schedule:
        return None
    local = when.astimezone(ZoneInfo(tz))
    day = DAYS[local.weekday()]
    if day not in schedule:
        return None
    hours = schedule[day]
    if hours is None:
        return False
    # Admite un tramo ["09:00","18:00"] o varios [["09:00","13:00"],["15:00","19:00"]].
    spans = [hours] if hours and isinstance(hours[0], str) else hours
    now_t = local.time()
    return any(_parse(a) <= now_t < _parse(b) for a, b in spans)


def open_during(schedule: dict | None, start: datetime, minutes: float, tz: str = "America/Santiago") -> bool | None:
    """¿Está abierta al llegar y al terminar la operación? None si se desconoce."""
    a = is_open(schedule, start, tz)
    b = is_open(schedule, start + timedelta(minutes=minutes), tz)
    if a is None or b is None:
        return None
    return a and b
