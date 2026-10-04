"""Búsqueda de casas en Google Maps (Places API) con respuestas simuladas."""

import json

from app.models.exchange_house import ExchangeHouse
from app.services.house_service import load_all_houses
from app.services.maps_discovery import (
    MapsReport, Place, PlacesClient, brand_name, comuna_from_address, discover, grid, group_places,
)


def _api_place(pid, name, lat=-33.44, lon=-70.65, website=None, status="OPERATIONAL", address=None):
    return {"id": pid, "displayName": {"text": name}, "location": {"latitude": lat, "longitude": lon},
            "formattedAddress": address or f"Calle {pid} 100, 8320000 Santiago, Región Metropolitana, Chile",
            "websiteUri": website, "internationalPhoneNumber": "+56 2 2222 0000",
            "googleMapsUri": f"https://maps.google.com/?cid={pid}", "businessStatus": status}


class _Resp:
    def __init__(self, data):
        self.status_code, self._data, self.text = 200, data, json.dumps(data)

    def json(self):
        return self._data


class _FakeApi:
    """Devuelve lugares según el rectángulo pedido; ``dense`` llena la primera celda (60) para forzar división."""

    def __init__(self, places, dense=False):
        self.places, self.dense, self.calls = places, dense, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(json)
        rect = json["locationRestriction"]["rectangle"]
        inside = [p for p in self.places
                  if rect["low"]["latitude"] <= p["location"]["latitude"] < rect["high"]["latitude"]
                  and rect["low"]["longitude"] <= p["location"]["longitude"] < rect["high"]["longitude"]]
        if self.dense and len(self.calls) <= 3:  # primera celda: 3 páginas llenas
            page = [_api_place(f"fill{len(self.calls)}_{i}", f"Cambios Relleno {i}") for i in range(20)]
            return _Resp({"places": page, "nextPageToken": "t" if len(self.calls) < 3 else None})
        return _Resp({"places": inside})


def _settings(settings, tmp_path, **extra):
    return settings.model_copy(update={"google_maps_api_key": "k", "maps_queries": "casas de cambio", "maps_bbox": "-33.50,-70.70,-33.40,-70.60",
                                       "maps_cell_degrees": 0.05, **extra})


def test_helpers():
    assert brand_name("AFEX - Mall Plaza Vespucio") == "AFEX"
    assert brand_name("Cambios Andes (Ahumada)") == "Cambios Andes"
    assert comuna_from_address("Av. Providencia 2133, 7510000 Providencia, Región Metropolitana, Chile") == "Providencia"
    assert comuna_from_address("Sin región") is None
    assert len(grid((-33.5, -70.7, -33.4, -70.6), 0.05)) == 4


def test_group_places_creates_new_houses_and_enriches_existing():
    existing = [ExchangeHouse(slug="afex", name="AFEX", website="https://www.afex.cl/"),
                ExchangeHouse(slug="cambios_lyon", name="Cambios Lyon")]
    places = [
        Place("1", "AFEX - Mall Plaza Vespucio", website="https://afex.cl/sucursales"),
        Place("2", "Cambios Lyon", website="https://www.cambioslyon.cl/", phone="+56 2 1"),
        Place("3", "Cambios Andes - Ahumada", website="https://cambiosandes.cl", latitude=-33.44, longitude=-70.65,
              address="Ahumada 1, 8320000 Santiago, Región Metropolitana, Chile"),
        Place("4", "Cambios Andes - Huérfanos", website="https://www.cambiosandes.cl/"),
        Place("5", "Banco de Chile - Cambio de Divisas"),  # banco: fuera
        Place("6", "Taller Cambio de Aceite Express"),  # no es casa de cambio
        Place("7", "Cambios Cerrada", status="CLOSED_PERMANENTLY"),
        Place("8", "Money Plus"),  # sin web: casa nueva igual
    ]
    report = MapsReport()
    houses = {h.slug: h for h in group_places(places, existing, report)}
    assert "afex" not in houses  # ya registrada y con web: nada que completar
    assert houses["cambios_lyon"].website == "https://www.cambioslyon.cl/" and not houses["cambios_lyon"].branches
    andes = houses["cambios_andes"]
    assert [b.name for b in andes.branches] == ["Cambios Andes - Ahumada", "Cambios Andes - Huérfanos"]
    assert andes.branches[0].comuna == "Santiago" and andes.branches[0].latitude == -33.44
    assert andes.branches[0].notes == "google_place_id=3"
    assert "money_plus" in houses and houses["money_plus"].website is None
    assert not {"banco_de_chile", "taller_cambio_de_aceite_express", "cambios_cerrada"} & set(houses)
    assert (report.exchange_places, report.new_houses, report.new_with_website) == (5, 2, 1)
    assert report.enriched == ["cambios_lyon"]


def test_discover_writes_file_and_registry_merges_it(settings, tmp_path):
    s = _settings(settings, tmp_path)
    (tmp_path / "houses.json").write_text(json.dumps({"exchange_houses": [
        {"slug": "cambios_lyon", "name": "Cambios Lyon", "phone": "+56 2 9"}]}), encoding="utf-8")
    api = _FakeApi([_api_place("a", "Cambios Andes - Ahumada", -33.45, -70.66, "https://cambiosandes.cl"),
                    _api_place("b", "Cambios Lyon", -33.42, -70.61, "https://cambioslyon.cl")])
    report = discover(s, [ExchangeHouse(slug="cambios_lyon", name="Cambios Lyon", phone="+56 2 9")],
                      PlacesClient(s, session=api))
    assert report.requests == 4 and report.new_houses == 1  # 4 celdas, 1 página cada una
    assert api.calls[0]["textQuery"] == "casas de cambio"

    houses = {h.slug: h for h in load_all_houses(s)}
    assert houses["cambios_lyon"].website == "https://cambioslyon.cl" and houses["cambios_lyon"].phone == "+56 2 9"
    assert houses["cambios_andes"].branches[0].source_url == "https://maps.google.com/?cid=a"


def test_full_cell_is_split_and_budget_is_respected(settings, tmp_path):
    s = _settings(settings, tmp_path, maps_bbox="-33.50,-70.70,-33.45,-70.65")
    api = _FakeApi([], dense=True)
    report = discover(s, [], PlacesClient(s, session=api))
    assert report.requests == 3 + 4 and not report.truncated  # 3 páginas llenas + 4 subceldas
    assert report.places == 60 and report.new_houses == 20  # "Cambios Relleno 0..19", 3 veces cada uno

    tight = _settings(settings, tmp_path, maps_bbox="-33.50,-70.70,-33.45,-70.65", maps_max_requests=2)
    report = discover(tight, [], PlacesClient(tight, session=_FakeApi([], dense=True)))
    assert report.truncated and report.requests == 2


def test_web_discovery_skips_social_links(settings, tmp_path):
    from app.scrapers.exchanges.web_discovery import WebDiscoveryScraper, is_social

    assert is_social("https://www.instagram.com/cambios") and is_social("wa.me/56911112222")
    assert not is_social("https://cambiosandes.cl")
    s = _settings(settings, tmp_path)
    (tmp_path / "maps_houses.json").write_text(json.dumps({"exchange_houses": [
        {"slug": "a", "name": "A", "website": "https://instagram.com/a"},
        {"slug": "b", "name": "B", "website": "https://b.cl"}]}), encoding="utf-8")
    assert [h.slug for h in WebDiscoveryScraper(s).candidates()] == ["b"]


def test_default_queries_search_like_google_maps(settings):
    assert settings.maps_queries.split(";")[0] == "casas de cambio"


def test_masked_key_gives_clear_error(settings, tmp_path):
    import pytest

    s = _settings(settings, tmp_path, google_maps_api_key="AIzaSy\u2022\u2022\u2022")
    with pytest.raises(RuntimeError, match="caracteres inválidos"):
        discover(s, [], PlacesClient(s, session=_FakeApi([])))
