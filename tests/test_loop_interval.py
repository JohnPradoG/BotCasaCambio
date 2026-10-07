from datetime import datetime

from app.config.settings import Settings
from app.main import loop_interval


def _at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 10, 8, h, m)


def test_fast_window_at_opening():
    s = Settings(_env_file=None)
    assert [loop_interval(s, _at(t)) for t in ("08:59", "09:00", "10:29", "10:30", "15:00")] == [180, 60, 60, 180, 180]


def test_window_disabled_or_custom():
    assert loop_interval(Settings(_env_file=None, fast_loop_window=""), _at("09:30")) == 180
    s = Settings(_env_file=None, fast_loop_window="13:00 - 14:00", fast_loop_interval_seconds=90)
    assert loop_interval(s, _at("13:30")) == 90 and loop_interval(s, _at("09:30")) == 180
