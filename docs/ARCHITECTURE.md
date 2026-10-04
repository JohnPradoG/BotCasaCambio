# Arquitectura

Basada en la estructura propuesta en SPEC §40, con algunos ajustes explicados al final.

```text
app/
├── main.py                     CLI (ver README)
├── logging_config.py           logs a consola y logs/bot.log (rotativo)
├── config/settings.py          toda la configuración desde .env (pydantic-settings)
├── models/                     modelos de dominio (sin dependencia de la BD)
│   ├── currency.py             normalización de códigos ISO / nombres en español
│   ├── quote.py                NormalizedQuote: el único formato que devuelve un scraper
│   ├── exchange_house.py       casa + sucursales físicas (dirección, horario, coordenadas)
│   └── opportunity.py          estados de oportunidad y niveles de confianza
├── scrapers/
│   ├── base.py                 timeout, reintentos, robots.txt, validación, aislamiento de errores
│   ├── normalization.py        parse de números chilenos + significado de compra/venta
│   ├── extractors.py           JSON embebido/API, tablas HTML, texto renderizado
│   ├── registry.py             registro automático de scrapers (@register)
│   ├── table_scraper.py        base para casas con tabla HTML estática (hora publicada, "sin comisiones")
│   └── exchanges/              un módulo por casa (manual_csv, gamaex, cambios_lyon, inmonex, afex)
├── services/
│   ├── quote_service.py        ejecuta scrapers, marca anomalías, guarda todo el historial
│   ├── anomaly_service.py      ANOMALOUS_QUOTE (SPEC §35)
│   ├── house_service.py        registro manual de casas, directorio y estadísticas (SPEC §44)
│   ├── arbitrage_engine.py     grafo, búsqueda de rutas, ganancia neta, find_best_routes() (ENGINE.md)
│   ├── route_optimizer.py      sucursales, tramos, transporte, horario y confianza por ruta
│   ├── distance_service.py     línea recta (Haversine) u OSRM; interfaz para otros proveedores
│   ├── schedule_service.py     ¿abierta al llegar? (solo con horario publicado)
│   ├── confidence_service.py   puntuación 0-100 con razones (no altera el ranking)
│   ├── opportunity_service.py  cotizaciones de la BD → motor → oportunidades guardadas
│   ├── cycle_service.py        un ciclo completo + decisión de alertas (SPEC §52)
│   ├── verification_service.py estados, razones, ejecuciones, expiración (SPEC §21, §45)
│   ├── history_service.py      estadísticas del historial (SPEC §29, §33)
│   └── report.py               texto del Top N (formato SPEC §46)
├── notifications/
│   ├── messages.py             alerta Telegram (SPEC §22) y mensajes de verificación (SPEC §20)
│   └── telegram.py             envío por Bot API (o al log si no está configurado)
├── api/
│   ├── routes.py               FastAPI: /api/top, quotes, houses, opportunities, stats
│   └── static/index.html       panel (Top, oportunidades, cotizaciones, casas con mapa, estadísticas)
└── database/
    ├── db.py                   engine/sesiones; SQLite ahora, PostgreSQL vía DATABASE_URL
    └── models.py               todas las tablas del SPEC §30 (+ branches)
data/
├── exchange_houses.json        registro manual de casas (solo datos con fuente)
└── manual_quotes.csv           cotizaciones manuales
deploy/                         unidades systemd (bot y panel)
scripts/geocode_branches.py     coordenadas desde OpenStreetMap Nominatim
```

## Ciclo (SPEC §52)

```text
scrapers (aislados) → validate() → detect_anomalies() → quotes (historial completo)
        ↓
quotes recientes → build_graph() → search_routes() → Top candidatas
        ↓
route_optimizer: sucursales, km, minutos, transporte, horario, confianza → re-ranking por ganancia neta
        ↓
opportunities (todas las del Top) → alerta Telegram si es nueva o mejoró → expiración de antiguas
```

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
8. **Margen de seguridad por tasa.** `SAFETY_MARGIN_PERCENT` empeora cada tasa usada, así
   que una ruta con más operaciones absorbe más margen (más pasos = más riesgo).
9. **Transporte dentro del ranking.** El costo de transporte se resta de la ganancia neta
   (SPEC §26), así que sí puede cambiar el orden; la distancia y el tiempo por sí mismos solo
   afectan la confianza.
10. **Fase 8 (ML) no implementada.** Necesita semanas de historial real (cotizaciones,
   verificaciones y ejecuciones). La base de datos ya guarda todo lo necesario.
