"""Texto del Top N con el formato del SPEC §46."""

from __future__ import annotations

from app.services.arbitrage_engine import Route, sensitivity

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
_CONFIDENCE_ES = {"HIGH": "ALTA", "MEDIUM": "MEDIA", "LOW": "BAJA"}


def clp(value: float, sign: bool = False) -> str:
    text = f"{abs(value):,.0f}".replace(",", ".")
    prefix = ("+" if value >= 0 else "-") if sign else ("-" if value < 0 else "")
    return f"{prefix}${text}"


def units(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_route(route: Route, detailed: bool = True) -> str:
    medal = MEDALS.get(route.rank or 0, "•")
    lines = [
        f"{medal} #{route.rank}",
        f"Ganancia neta: {clp(route.net_profit_clp, sign=True)}",
        f"CLP final (neto): {clp(route.net_final_clp)}",
        f"Ruta: {' → '.join(route.currencies)}",
        f"Casas: {' → '.join(route.houses)}",
        f"Pasos: {route.steps}",
    ]
    dist = "desconocida (faltan coordenadas)" if route.distance_km is None else f"{route.distance_km:.1f} km".replace(".", ",")
    lines.append(f"Distancia: {dist}")
    lines.append(f"Tiempo: {'desconocido' if route.estimated_minutes is None else f'{route.estimated_minutes:.0f} min'}")
    conf = _CONFIDENCE_ES.get(route.confidence or "", "sin calcular")
    score = f" ({route.confidence_score:.0f}/100)" if route.confidence_score is not None else ""
    lines.append(f"Confianza: {conf}{score}")
    if route.executable_now is False:
        lines.append("⏰ Alguna casa está cerrada ahora (oportunidad para más tarde).")
    if detailed:
        lines += [
            "",
            f"Ganancia bruta: {clp(route.gross_profit_clp, sign=True)}",
            f"Comisiones: {'-' + clp(route.commissions_clp)}",
            f"Margen de seguridad: {'-' + clp(route.safety_margin_clp)}",
            f"Transporte: {'-' + clp(route.transport_clp)}" + (f" ({route.trips} viajes)" if route.trips else ""),
        ]
        if route.alt_transport:
            a = route.alt_transport
            lines.append(f"Si vas en {a['label']} ({clp(a['cost_per_trip'])} por viaje): "
                         f"{clp(a['net_profit_clp'], sign=True)} neto")
        lines += [""]
        for s in route.route:
            label = "compra" if s.rate_used == "buy_rate" else "venta"
            lines.append(
                f"  {s.position}. {s.house}{f' ({s.branch})' if s.branch else ''}: {s.from_currency} → {s.to_currency} "
                f"a {units(s.rate)} ({label}) · {units(s.amount_in)} {s.from_currency} → {units(s.amount_out)} {s.to_currency}"
            )
        if route.edges:  # las rutas leídas de la BD no guardan aristas
            sens = sensitivity(route)
            lines.append("")
            lines.append("Si las tasas empeoran: " + ", ".join(
                f"-{pct * 100:.1f}%: {clp(v, sign=True)}".replace(".", ",", 1) for pct, v in sens.items()
            ))
    if route.flags:
        lines.append(f"⚠️ Banderas: {', '.join(route.flags)}")
    if detailed and route.warnings:
        lines.append("Riesgos: " + "; ".join(w.split(": ", 1)[-1] for w in route.warnings))
    if route.requires_verification:
        lines.append("⚠️ Usa una cotización sospechosa: verificar antes de considerarla real.")
    return "\n".join(lines)


def format_top(routes: list[Route], initial_clp: float) -> str:
    header = f"CAPITAL INICIAL\n{clp(initial_clp)} CLP\n\nTOP {len(routes)} ARBITRAJES\n"
    if not routes:
        return header + "\nNo se encontraron rutas con ganancia neta positiva."
    body = "\n\n".join(format_route(r) for r in routes)
    return f"{header}\n{body}\n\n⚠️ Confirmar precios y disponibilidad antes de desplazarse. Nada está garantizado."
