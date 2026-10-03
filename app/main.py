"""Línea de comandos del bot.

    python -m app.main init-db              # crea tablas y registra casas (data/exchange_houses.json)
    python -m app.main scrape [--only afex] # ejecuta scrapers y guarda cotizaciones
    python -m app.main quotes               # últimas cotizaciones guardadas
    python -m app.main houses               # casas descubiertas / con cotización / sin datos
    python -m app.main scrapers             # scrapers disponibles y su estado
    python -m app.main probe afex           # diagnóstico de un sitio para ajustar su scraper
    python -m app.main analyze [--capital 5000000 --steps 4 --top 5 --save]
    python -m app.main run-once             # un ciclo completo: scrape + rutas + guardado + alerta
    python -m app.main loop                 # ciclo cada LOOP_INTERVAL_SECONDS (VPS)
    python -m app.main opportunities [--status DETECTED]
    python -m app.main show 125             # detalle + mensajes de verificación
    python -m app.main verify 125           # menú para cambiar el estado (SPEC §45)
    python -m app.main verify 125 --status FAILED --reason "No tenían USD"
    python -m app.main stats                # estadísticas del historial
    python -m app.main telegram-test        # envía un mensaje de prueba
    python -m app.main dashboard            # panel web (FastAPI)
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
from app.database.models import OpportunityRow
from app.logging_config import setup_logging
from app.models.opportunity import OpportunityStatus
from app.scrapers.registry import available_scrapers, get_scrapers
from app.services.cycle_service import make_notifier, run_cycle
from app.services.house_service import house_stats, sync_houses
from app.services.quote_service import collect_quotes, latest_quotes
from app.services.report import clp, format_top

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
    init_db()
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
    init_db()
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


def _cycle(args, scrape: bool, save: bool, alert: bool) -> int:
    settings = get_settings()
    init_db()
    capital = getattr(args, "capital", None)
    with session_scope() as s:
        result = run_cycle(s, settings, scrape=scrape, capital=capital, top_n=getattr(args, "top", None),
                           max_steps=getattr(args, "steps", None), save=save, alert=alert)
    print(format_top(result.routes, capital if capital is not None else settings.initial_capital_clp))
    print(f"\n({result.quotes_used} cotizaciones, {result.stats.candidate_routes} rutas generadas, "
          f"{result.stats.valid_routes} rutas válidas, alertas enviadas: {'sí' if result.alerted else 'no'})")
    return 0


def cmd_analyze(args) -> int:
    return _cycle(args, scrape=False, save=args.save, alert=False)


def cmd_run_once(args) -> int:
    return _cycle(args, scrape=True, save=True, alert=not args.no_alert)


def cmd_loop(args) -> int:
    interval = args.interval or get_settings().loop_interval_seconds
    while True:
        try:
            _cycle(argparse.Namespace(), scrape=True, save=True, alert=True)
        except Exception:  # noqa: BLE001 - el bucle no debe morir
            logger.exception("Error en el ciclo")
        time.sleep(interval)


def cmd_opportunities(args) -> int:
    from app.services.verification_service import list_opportunities

    init_db()
    with session_scope() as s:
        rows = list_opportunities(s, args.status, args.limit)
        print(f"{'id':>5s}  {'detectada (UTC)':19s}  {'estado':20s} {'neta':>11s}  {'conf':6s} ruta")
        for o in rows:
            route = " → ".join((o.details or {}).get("currencies", []))
            print(f"{o.id:>5d}  {o.detected_at:%Y-%m-%d %H:%M:%S}  {o.status:20s} {clp(o.net_profit_clp, True):>11s}  "
                  f"{(o.confidence or '-'):6s} {route}")
    return 0


def cmd_show(args) -> int:
    from app.notifications.messages import verification_messages
    from app.services.house_service import house_directory
    from app.services.opportunity_service import route_from_row

    init_db()
    with session_scope() as s:
        opp = s.get(OpportunityRow, args.id)
        if opp is None:
            print(f"No existe la oportunidad #{args.id}")
            return 1
        route = route_from_row(opp)
        print(f"Oportunidad #{opp.id} · {opp.status} · detectada {opp.detected_at:%Y-%m-%d %H:%M} UTC")
        print(format_top([route], opp.initial_clp))
        print("\nMensajes de verificación:")
        for m in verification_messages(route, house_directory(s)):
            print(f"  {m['step']}. {m['house']}: {m['text']}")
            if m["whatsapp_link"]:
                print(f"     {m['whatsapp_link']}")
    return 0


def cmd_verify(args) -> int:
    from app.services.verification_service import MENU, InvalidTransition, change_status

    init_db()
    status, reason = args.status, args.reason
    if status is None:
        print(f"Opportunity #{args.id}\n")
        for key, st in MENU.items():
            print(f"[{key}] {st.value}")
        choice = input("\nOpción: ").strip()
        if choice not in MENU:
            print("Opción inválida")
            return 1
        status = MENU[choice].value
        reason = reason or input("Razón (opcional salvo FAILED): ").strip() or None
    final_clp = args.final_clp
    if status in ("EXECUTED", "PARTIALLY_EXECUTED") and final_clp is None and args.status is None:
        raw = input("CLP final obtenido (enter si no sabe): ").strip().replace(".", "")
        final_clp = float(raw) if raw else None
    try:
        with session_scope() as s:
            opp = change_status(s, args.id, status, reason, args.channel, final_clp)
            print(f"Oportunidad #{opp.id} → {opp.status}")
    except (KeyError, InvalidTransition, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    return 0


def cmd_stats(args) -> int:
    from app.services.history_service import full_report

    init_db()
    with session_scope() as s:
        report = full_report(s, get_settings().timezone, args.days)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_telegram_test(_args) -> int:
    settings = get_settings()
    if not settings.telegram_enabled:
        print("Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env")
        return 1
    ok = make_notifier(settings).send("✅ BotCasaCambio: prueba de conexión con Telegram.")
    print("Enviado" if ok else "No se pudo enviar (ver logs)")
    return 0 if ok else 1


def cmd_dashboard(args) -> int:
    import uvicorn

    settings = get_settings()
    init_db()
    uvicorn.run("app.api.routes:app", host=args.host or settings.dashboard_host, port=args.port or settings.dashboard_port)
    return 0


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

    for name, func, help_text in (("analyze", cmd_analyze, "Top N con las cotizaciones guardadas"),
                                  ("run-once", cmd_run_once, "un ciclo completo")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--capital", type=float, default=None, help="capital inicial en CLP (INITIAL_CAPITAL_CLP)")
        p.add_argument("--steps", type=int, default=None, help="máximo de operaciones (MAX_STEPS)")
        p.add_argument("--top", type=int, default=None, help="rutas a mostrar (TOP_ROUTES)")
        if name == "analyze":
            p.add_argument("--save", action="store_true", help="guardar las rutas como oportunidades")
        else:
            p.add_argument("--no-alert", action="store_true", help="no enviar Telegram")
        p.set_defaults(func=func)

    p = sub.add_parser("loop")
    p.add_argument("--interval", type=int, default=None, help="segundos entre ciclos (LOOP_INTERVAL_SECONDS)")
    p.set_defaults(func=cmd_loop)

    p = sub.add_parser("opportunities")
    p.add_argument("--status", choices=[s.value for s in OpportunityStatus])
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_opportunities)
    p = sub.add_parser("show")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("verify")
    p.add_argument("id", type=int)
    p.add_argument("--status", choices=[s.value for s in OpportunityStatus])
    p.add_argument("--reason")
    p.add_argument("--channel", choices=["phone", "whatsapp", "in_person", "web"])
    p.add_argument("--final-clp", type=float, default=None, help="CLP final real (si se ejecutó)")
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser("stats")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_stats)
    sub.add_parser("telegram-test").set_defaults(func=cmd_telegram_test)
    p = sub.add_parser("dashboard")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_dashboard)
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
