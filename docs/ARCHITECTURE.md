# Arquitectura

Basada en la estructura propuesta en SPEC §40, con algunos ajustes explicados al final.

```text
app/
├── main.py                    CLI: init-db, scrape, quotes, houses, scrapers, probe, loop
├── logging_config.py          logs a consola y logs/bot.log (rotativo)
├── config/settings.py         toda la configuración desde .env (pydantic-settings)
├── models/                    modelos de dominio (sin dependencia de la BD)
│   ├── currency.py            normalización de códigos ISO / nombres en español
│   ├── quote.py               NormalizedQuote: el único formato que devuelve un scraper
│   ├── exchange_house.py      casa + sucursales físicas
│   └── opportunity.py         estados de oportunidad y niveles de confianza
├── scrapers/
│   ├── base.py                timeout, reintentos, robots.txt, validación, aislamiento de errores
│   ├── normalization.py       parse de números chilenos + significado de compra/venta
│   ├── extractors.py          JSON embebido/API, tablas HTML, texto renderizado
│   ├── registry.py            registro automático de scrapers (@register)
│   └── exchanges/
│       ├── manual_csv.py      cotizaciones ingresadas a mano (teléfono, pizarra)
│       └── afex.py            primer scraper de un sitio real
├── services/
│   ├── quote_service.py       ejecuta scrapers, marca anomalías, guarda todo el historial
│   ├── anomaly_service.py     ANOMALOUS_QUOTE (SPEC §35)
│   └── house_service.py       registro manual de casas y estadísticas (SPEC §44)
└── database/
    ├── db.py                  engine/sesiones; SQLite ahora, PostgreSQL vía DATABASE_URL
    └── models.py              todas las tablas del SPEC §30 (+ branches)
data/
├── exchange_houses.json       registro manual de casas (solo datos con fuente)
└── manual_quotes.csv          cotizaciones manuales
docs/SPEC.md                   especificación completa
```

## Flujo de la Fase 1

```text
scrapers (aislados) ──► NormalizedQuote.validate() ──► detect_anomalies() ──► quotes (historial)
                                                                       └──► scraper_runs (auditoría)
```

## Fases siguientes (dónde encaja cada pieza)

| Fase | Módulos nuevos |
|------|----------------|
| 2 | `services/arbitrage_engine.py` (grafo de aristas por casa, rutas 1..MAX_STEPS, CLP intermedio, ciclos), `find_best_routes()` |
| 3 | comisiones (publicadas o `DEFAULT_COMMISSION_*`), disponibilidad, montos mín/máx, cotizaciones antiguas, Top N |
| 4 | `services/distance_service.py` (interfaz con implementación Haversine y OSRM), transporte, `confidence_service.py` |
| 5 | `notifications/telegram.py`, mensajes de verificación por WhatsApp/teléfono |
| 6 | `verification_service.py`, `history_service.py`, comando para cambiar estados |
| 7 | `api/` FastAPI + dashboard |

## Ajustes respecto del SPEC §40 (y por qué)

1. **Tabla `branches` además de `exchange_houses`.** Una casa (p. ej. AFEX) publica una
   cotización pero tiene varias sucursales físicas. La distancia, el horario y el
   teléfono dependen de la sucursal, así que el motor (Fase 4) elegirá sucursal por
   paso. Sin esto habría que duplicar casas.
2. **`NormalizedQuote` con convención fija.** `buy_rate`/`sell_rate` siempre desde el
   punto de vista de la casa, en CLP por 1 unidad. La traducción de etiquetas
   ("Usted compra", "Compramos", "Vendo"...) vive solo en `normalization.py`;
   ningún scraper razona compra/venta por su cuenta. Una etiqueta ambigua se
   descarta en vez de adivinarse.
3. **Las rarezas se marcan, no se corrigen.** `INVERTED_SPREAD` (compra > venta) y
   `ANOMALOUS_QUOTE` quedan guardadas con su bandera para que el motor les baje la
   confianza y pida verificación; nunca se intercambian ni se borran.
4. **`commission_unknown` derivado.** Si la casa no publica comisión, ambos campos son
   NULL y `commission_unknown=True`; la comisión estimada manual vendrá de `.env`.
5. **Todas las tablas desde la Fase 1.** Así el historial de cotizaciones y
   ejecuciones de scrapers es completo desde el primer día.
6. **Scraper manual por CSV.** Además de servir para el registro manual (SPEC §44),
   permite cargar precios confirmados por teléfono antes de tener scrapers para
   todas las casas.
7. **Comando `probe`.** Para sitios que cargan precios con JavaScript, guarda el HTML
   estático, el renderizado y las respuestas JSON del navegador, para encontrar la
   API pública (preferida según SPEC §7) sin adivinar.
