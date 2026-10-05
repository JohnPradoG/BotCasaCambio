import pytest

from app.config.settings import Settings
from app.database.db import init_db, make_engine, session_scope


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        scraper_retries=1,
        scraper_backoff_seconds=0,
        respect_robots_txt=False,
        manual_quotes_file=str(tmp_path / "manual.csv"),
        houses_file=str(tmp_path / "houses.json"),
    )


@pytest.fixture
def engine():
    eng = make_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture
def session(engine):
    with session_scope(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def no_market_reference(monkeypatch):
    """Los tests no consultan Binance/Buda; el test de la referencia la prueba con sesiones falsas."""
    monkeypatch.setattr("app.services.cycle_service.get_reference", lambda settings: None)
