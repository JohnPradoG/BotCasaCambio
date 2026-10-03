"""Línea de comandos del bot.

    python -m app.main init-db          # crea tablas y registra casas desde data/exchange_houses.json
    python -m app.main scrape           # ejecuta los scrapers activos y guarda cotizaciones
    python -m app.main scrape --only afex
    python -m app.main quotes           # últimas cotizaciones guardadas
    python -m app.main houses           # resumen de casas (descubiertas / con cotización / sin datos)
    python -m app.main scrapers         # scrapers disponibles y su estado de verificación
    python -m app.main probe afex       # diagnóstico de un sitio para ajustar su scraper
    python -m app.main analyze          # Top N rutas con las últimas cotizaciones
    python -m app.main analyze --capital 5000000 --steps 4 --top 5
    python -m app.main loop --interval 180   # scrape + análisis periódico (VPS)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from app.config.settings import DATA_DIR, get_settings
from app.database.db import init_db, session_scope
from app.logging_config import setup_logging
from app.scrapers.registry import available_scrapers, get_scrapers
from app.services.house_service import house_stats, sync_houses
from app.services.arbitrage_engine import SearchStats, find_best_routes
from app.services.opportunity_service import quotes_for_engine, save_routes
from app.services.quote_service import collect_quotes, latest_quotes
from app.services.report import format_top

logger = logging.getLogger("app")


def _fmt(value: float | None) -> str:
    if value is None:
        return "NULL"
    decimals = 0 if value >= 100 and value == int(value) else 2
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def cmd_init_db(_args) -> int:
    settings = get_settings()
    init_db()
    with session_scope() as s:
        if Path(settings.houses_file).exists():
            sync_houses(s, settings.houses_file)
    print("Base de datos lista.")
    return 0


def cmd_scrape(args) -> int:
    settings = get_settings()
    init_db()
    slugs = args.only or settings.enabled_scraper_list
    with session_scope() as s:
        if Path(settings.houses_file).exists():
            sync_houses(s, settings.houses_file)
        report = collect_quotes(s, get_scrapers(slugs))
    for r in report.results:
        print(f"{r.scraper:15s} {r.status.value:18s} cotizaciones={len(r.quotes)} {r.error or ''}")
    return 0 if not report.failed else 2


def cmd_quotes(args) -> int:
    with session_scope() as s:
        rows = latest_quotes(s, args.max_age)
        print(f"{'casa':12s} {'div':4s} {'compra':>12s} {'venta':>12s}  {'obtenida (UTC)':20s} flags")
        for q in sorted(rows, key=lambda r: (r.currency, r.house.slug)):
            print(
                f"{q.house.slug:12s} {q.currency:4s} {_fmt(q.buy_rate):>12s} {_fmt(q.sell_rate):>12s}  "
                f"{q.timestamp_collected:%Y-%m-%d %H:%M:%S}  {','.join(q.flags or [])}"
            )
    return 0


def cmd_houses(_args) -> int:
    settings = get_settings()
    with session_scope() as s:
        stats = house_stats(s, settings.max_quote_age_minutes)
    print(f"Houses discovered: {stats.discovered}")
    print(f"Houses with active quotes: {stats.with_active_quotes}")
    print(f"Houses unavailable: {stats.unavailable}")
    return 0


def cmd_scrapers(_args) -> int:
    enabled = set(get_settings().enabled_scraper_list)
    for slug, cls in sorted(available_scrapers().items()):
        state = "verificado" if cls.verified else "SIN VERIFICAR"
        print(f"{slug:15s} {'activo' if slug in enabled else 'inactivo':9s} {state:14s} {cls.source_url}")
    return 0


def cmd_probe(args) -> int:
    scraper = get_scrapers([args.slug])[0]
    if not hasattr(scraper, "probe"):
        print(f"{args.slug} no implementa probe()")
        return 1
    out = DATA_DIR / "probe" / args.slug
    report = scraper.probe(out)
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"Archivos guardados en {out}")
    return 0


def cmd_analyze(args) -> int:
    settings = get_settings()
    init_db()
    capital = args.capital if args.capital is not None else settings.initial_capital_clp
    with session_scope() as s:
        quotes = quotes_for_engine(s, args.max_age)
        stats = SearchStats()
        routes = find_best_routes(quotes, initial_amount=capital, max_steps=args.steps, top_n=args.top, stats=stats)
        if args.save:
            save_routes(s, routes)
    print(format_top(routes, capital))
    print(f"\n({len(quotes)} cotizaciones, {stats.candidate_routes} rutas generadas, {stats.valid_routes} rutas válidas)")
    return 0


def cmd_loop(args) -> int:
    while True:
        try:
            cmd_scrape(argparse.Namespace(only=args.only))
            cmd_analyze(argparse.Namespace(capital=None, steps=None, top=None, max_age=None, save=True))
        except Exception:  # noqa: BLE001 - el bucle no debe morir
            logger.exception("Error en el ciclo de scraping")
        time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.main", description="Bot de arbitraje entre casas de cambio")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    p = sub.add_parser("scrape")
    p.add_argument("--only", nargs="+", help="slugs de scrapers a ejecutar")
    p.set_defaults(func=cmd_scrape)
    p = sub.add_parser("quotes")
    p.add_argument("--max-age", type=int, default=None, help="solo cotizaciones de los últimos N minutos")
    p.set_defaults(func=cmd_quotes)
    sub.add_parser("houses").set_defaults(func=cmd_houses)
    sub.add_parser("scrapers").set_defaults(func=cmd_scrapers)
    p = sub.add_parser("probe")
    p.add_argument("slug")
    p.set_defaults(func=cmd_probe)
    p = sub.add_parser("analyze")
    p.add_argument("--capital", type=float, default=None, help="capital inicial en CLP (por defecto INITIAL_CAPITAL_CLP)")
    p.add_argument("--steps", type=int, default=None, help="máximo de operaciones (por defecto MAX_STEPS)")
    p.add_argument("--top", type=int, default=None, help="rutas a mostrar (por defecto TOP_ROUTES)")
    p.add_argument("--max-age", type=int, default=None, help="ignorar cotizaciones de más de N minutos")
    p.add_argument("--save", action="store_true", help="guardar las rutas como oportunidades")
    p.set_defaults(func=cmd_analyze)
    p = sub.add_parser("loop")
    p.add_argument("--interval", type=int, default=180, help="segundos entre ciclos (60-300 recomendado)")
    p.add_argument("--only", nargs="+")
    p.set_defaults(func=cmd_loop)
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
