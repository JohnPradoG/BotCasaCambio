"""Línea de comandos del bot.

    python -m app.main init-db              # crea tablas y registra casas (data/exchange_houses.json)
    python -m app.main scrape [--only afex] # ejecuta scrapers y guarda cotizaciones
    python -m app.main quotes               # últimas cotizaciones guardadas
    python -m app.main houses               # casas descubiertas / con cotización / sin datos
    python -m app.main scrapers             # scrapers disponibles y su estado
    python -m app.main price-requests       # enlaces de WhatsApp para pedir precios a casas sin web
    python -m app.main probe-all            # revisa todas las webs de casas (reporte para ajustar scrapers)
    python -m app.main probe afex           # diagnóstico de un sitio para ajustar su scraper
    python -m app.main analyze [--capital 5000000 --steps 4 --top 5 --save]
    python -m app.main run-once             # un ciclo completo: scrape + rutas + guardado + alerta
    python -m app.main loop                 # ciclo cada LOOP_INTERVAL_SECONDS (VPS)
    python -m app.main opportunities [--status DETECTED]
    python -m app.main show 125             # detalle + mensajes de verificación
    python -m app.main verify 125           # menú para cambiar el estado (SPEC §45)
    python -m app.main verify 125 --status FAILED --reason "No tenían USD"
    python -m app.main stats                # estadísticas del historial
    python -m app.main add-quote gamaex USD 970 990   # precio de pizarra/teléfono
    python -m app.main telegram-chat-id     # muestra el TELEGRAM_CHAT_ID (escríbele antes al bot)
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
from app.services.house_service import house_stats, sync_all_houses
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
        sync_all_houses(s, settings)
    print("Base de datos lista.")
    return 0


def cmd_scrape(args) -> int:
    settings = get_settings()
    init_db()
    slugs = args.only or settings.enabled_scraper_list
    with session_scope() as s:
        sync_all_houses(s, settings)
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


def cmd_probe_all(args) -> int:
    from app.scrapers.browser import playwright_available
    from app.services.probe_service import probe_all, summarize

    use_browser = not args.no_browser and playwright_available()
    if not args.no_browser and not use_browser:
        print("Playwright no está instalado: se revisa solo el HTML (pip install -r requirements-browser.txt "
              "&& python -m playwright install --with-deps chromium)")
    out = DATA_DIR / "probe"
    report = probe_all(get_settings(), out, use_browser)
    print(summarize(report))
    print(f"\nReporte completo: {out / 'report.json'} (envíalo para ajustar los scrapers)")
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


def _known_houses() -> dict[str, str]:
    from app.database.models import ExchangeHouseRow

    init_db()
    with session_scope() as s:
        settings = get_settings()
        sync_all_houses(s, settings)
        return {h.slug: h.name for h in s.query(ExchangeHouseRow).all()}


def _analysis_text(scrape_manual: bool, short: bool) -> str:
    """Carga los precios manuales (opcional) y devuelve el Top con lo guardado, sin alertar."""
    settings = get_settings()
    init_db()
    with session_scope() as s:
        if scrape_manual:
            collect_quotes(s, get_scrapers(["manual_csv"], settings=settings), settings)
        result = run_cycle(s, settings, scrape=False, save=False, alert=False)
    if not short:
        return format_top(result.routes, settings.initial_capital_clp)
    if not result.routes:
        return "Por ahora no hay rutas con ganancia neta positiva."
    best = result.routes[0]
    return (f"Mejor ruta ahora: {' → '.join(best.currencies)} ({' → '.join(best.houses)})\n"
            f"Ganancia neta: {clp(best.net_profit_clp, True)} CLP. Usa /top para el detalle.")


def make_command_poller():
    from app.notifications.telegram_commands import CommandHandlers, TelegramCommandPoller

    settings = get_settings()
    if not settings.telegram_enabled:
        return None
    handlers = CommandHandlers(
        known_houses=_known_houses,
        after_price=lambda: _analysis_text(scrape_manual=True, short=True),
        top=lambda: _analysis_text(scrape_manual=True, short=False),
    )
    return TelegramCommandPoller(settings, handlers)


def _price_request_text() -> str | None:
    from app.services.house_service import load_all_houses
    from app.services.opportunity_service import quotes_for_engine
    from app.services.price_requests import build_price_request

    settings = get_settings()
    init_db()
    with session_scope() as s:
        fresh = {q.exchange_house for q in quotes_for_engine(s, settings.max_quote_usable_hours * 60)}
    houses = load_all_houses(settings)
    return build_price_request(houses, fresh, settings)


def _maybe_send_price_request(notifier) -> None:
    """Envía el pedido diario una vez al día, a partir de PRICE_REQUEST_TIME (hora local)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    settings = get_settings()
    if not settings.price_request_time:
        return
    now = datetime.now(ZoneInfo(settings.timezone))
    marker = DATA_DIR / "price_request_sent.txt"
    try:
        last = marker.read_text().strip()
    except OSError:
        last = ""
    if last == now.date().isoformat() or now.strftime("%H:%M") < settings.price_request_time:
        return
    text = _price_request_text()
    if text and notifier.send(text):
        marker.write_text(now.date().isoformat())


def cmd_price_requests(args) -> int:
    text = _price_request_text()
    if not text:
        print("Todas las casas con contacto tienen precio reciente.")
        return 0
    print(text)
    if args.send:
        ok = make_notifier(get_settings()).send(text)
        print("Enviado por Telegram" if ok else "No se pudo enviar")
    return 0


def cmd_discover_maps(_args) -> int:
    from app.services.house_service import load_houses_file
    from app.services.maps_discovery import discover, summary_text

    settings = get_settings()
    if not settings.google_maps_api_key:
        print("Falta GOOGLE_MAPS_API_KEY en .env (ver README, sección Google Maps)")
        return 1
    existing = load_houses_file(settings.houses_file) if Path(settings.houses_file).exists() else []
    try:
        report = discover(settings, existing)
    except RuntimeError as exc:
        print(exc)
        return 1
    print(summary_text(report))
    print(f"{report.requests} consultas a la API · resultado en {settings.maps_houses_path}")
    return 0


def _maybe_discover_maps(notifier) -> None:
    """Repite la búsqueda en Google Maps cada MAPS_DISCOVERY_DAYS (si hay clave)."""
    from app.services.house_service import load_houses_file
    from app.services.maps_discovery import discover, summary_text

    settings = get_settings()
    if not settings.google_maps_api_key or not settings.maps_discovery_days:
        return
    path = Path(settings.maps_houses_path)
    if path.exists() and time.time() - path.stat().st_mtime < settings.maps_discovery_days * 86400:
        return
    existing = load_houses_file(settings.houses_file) if Path(settings.houses_file).exists() else []
    report = discover(settings, existing)
    notifier.send(summary_text(report))


def cmd_loop(args) -> int:
    interval = args.interval or get_settings().loop_interval_seconds
    poller = make_command_poller()  # con Telegram configurado, atiende /precio mientras espera
    while True:
        try:
            _cycle(argparse.Namespace(), scrape=True, save=True, alert=True)
        except Exception:  # noqa: BLE001 - el bucle no debe morir
            logger.exception("Error en el ciclo")
        try:
            _maybe_discover_maps(make_notifier(get_settings()))
        except Exception:  # noqa: BLE001
            logger.exception("Error buscando casas en Google Maps")
        try:
            _maybe_send_price_request(make_notifier(get_settings()))
        except Exception:  # noqa: BLE001
            logger.exception("Error enviando el pedido diario de precios")
        if poller is None:
            time.sleep(interval)
        else:
            try:
                poller.wait(interval)
            except Exception:  # noqa: BLE001
                logger.exception("Error atendiendo Telegram")
                time.sleep(interval)


def cmd_add_quote(args) -> int:
    from app.services.manual_entry import ManualEntryError, parse_price_command, save_manual_price

    settings = get_settings()
    try:
        price = parse_price_command(" ".join([*args.house, args.currency, args.buy, args.sell]), _known_houses())
    except ManualEntryError as exc:
        print(exc)
        return 1
    price.branch = args.branch
    save_manual_price(settings.manual_quotes_file, price, source=args.source, notes=args.notes)
    print(f"Guardado en {settings.manual_quotes_file}: {price.house} {price.currency} "
          f"compra={price.buy_rate} venta={price.sell_rate}")
    print(_analysis_text(scrape_manual=True, short=True))
    return 0


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


def cmd_telegram_chat_id(_args) -> int:
    from app.notifications.telegram import find_chat_ids

    settings = get_settings()
    if not settings.telegram_bot_token:
        print("Falta TELEGRAM_BOT_TOKEN en .env")
        return 1
    chats = find_chat_ids(settings.telegram_bot_token)
    if not chats:
        print("No hay mensajes: abre tu bot en Telegram, envíale /start y vuelve a ejecutar este comando.")
        return 1
    for chat in chats:
        print(f"TELEGRAM_CHAT_ID={chat['id']}    ({chat['type']}: {chat['name']})")
    return 0


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
    p = sub.add_parser("price-requests", help="enlaces de WhatsApp para pedir precios a casas sin web")
    p.add_argument("--send", action="store_true", help="enviar también por Telegram")
    p.set_defaults(func=cmd_price_requests)
    sub.add_parser("discover-maps", help="busca casas de cambio en Google Maps (GOOGLE_MAPS_API_KEY)").set_defaults(
        func=cmd_discover_maps)
    p = sub.add_parser("probe-all", help="revisa todas las webs de casas y deja data/probe/report.json")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_probe_all)
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
    p = sub.add_parser("add-quote", help="guarda un precio visto en pizarra o por teléfono")
    p.add_argument("house", nargs="+", help="casa (slug o nombre)")
    p.add_argument("currency")
    p.add_argument("buy", help="compra: lo que la casa paga por 1 unidad (- si no se sabe)")
    p.add_argument("sell", help="venta: lo que la casa cobra por 1 unidad (- si no se sabe)")
    p.add_argument("--branch")
    p.add_argument("--source", default="manual:pizarra", help="p. ej. tel:+56..., manual:pizarra")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_add_quote)
    sub.add_parser("telegram-chat-id").set_defaults(func=cmd_telegram_chat_id)
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
