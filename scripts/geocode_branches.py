"""Completa latitud/longitud de sucursales en data/exchange_houses.json usando OpenStreetMap Nominatim.

Uso (en tu VPS o computador, con Internet):

    python scripts/geocode_branches.py            # muestra lo que encontraría
    python scripts/geocode_branches.py --write    # guarda las coordenadas en el JSON

Respeta la política de uso de Nominatim: 1 consulta por segundo y User-Agent
identificable. Solo completa sucursales SIN coordenadas y deja una nota con la
fuente; un humano debe revisar el resultado (``verified`` sigue en false).
Datos © OpenStreetMap contributors (ODbL).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "data" / "exchange_houses.json"
URL = "https://nominatim.openstreetmap.org/search"
UA = "BotCasaCambio/0.1 (geocodificacion de sucursales; uso personal)"


def geocode(address: str, comuna: str | None) -> tuple[float, float, str] | None:
    query = ", ".join(p for p in (address, comuna, "Región Metropolitana", "Chile") if p)
    resp = requests.get(URL, params={"q": query, "format": "json", "limit": 1, "countrycodes": "cl"},
                        headers={"User-Agent": UA}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    doc = json.loads(FILE.read_text(encoding="utf-8"))
    changed = 0
    for house in doc.get("exchange_houses", []):
        for b in house.get("branches", []):
            if b.get("latitude") is not None or not b.get("address"):
                continue
            result = geocode(b["address"], b.get("comuna"))
            time.sleep(1.1)
            if result is None:
                print(f"✗ {house['name']} · {b['name']}: sin resultado para {b['address']!r}")
                continue
            lat, lon, label = result
            print(f"✓ {house['name']} · {b['name']}: {lat:.6f}, {lon:.6f}  ({label})")
            b["latitude"], b["longitude"] = lat, lon
            note = "coordenadas: OpenStreetMap Nominatim (revisar)"
            b["notes"] = f"{b['notes']}; {note}" if b.get("notes") else note
            changed += 1
    if args.write and changed:
        FILE.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{changed} sucursales actualizadas en {FILE}")
    elif changed:
        print("Ejecuta con --write para guardar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
