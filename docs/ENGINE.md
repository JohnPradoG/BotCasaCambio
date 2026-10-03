# Motor de arbitraje (Fase 2)

Código: `app/services/arbitrage_engine.py`. Función principal:

```python
find_best_routes(quotes, initial_currency="CLP", initial_amount=1_000_000, max_steps=5, top_n=3)
```

## Grafo

- Nodos: divisas. CLP es un nodo más (puede ser intermedio).
- Aristas: cada cotización `(casa, X, compra b, venta s)` en CLP crea dos operaciones propias de esa casa:
  - `CLP → X` con la **venta** de la casa: `X = CLP / s`
  - `X → CLP` con la **compra** de la casa: `CLP = X · b`
- Una cotización cruzada (EUR cotizado en USD) crea aristas `USD ↔ EUR` con la misma regla.

## Costos por paso

| Costo | De dónde sale |
|-------|---------------|
| Comisión % | `commission_percent` publicada; si no hay, `DEFAULT_COMMISSION_PERCENT` (marcada `COMMISSION_ESTIMATED`); si tampoco, 0 y la ruta queda con `COMMISSION_UNKNOWN` |
| Comisión fija | igual, con `commission_fixed` / `DEFAULT_COMMISSION_FIXED_CLP`, descontada del lado CLP |
| Margen de seguridad | cada tasa se empeora `SAFETY_MARGIN_PERCENT` % antes de calcular (SPEC §27) |
| Transporte | `TRANSPORT_COST_PER_KM` × km + `TRANSPORT_FIXED_COST_PER_TRIP_CLP` por traslado (ver abajo) |

`ganancia neta = CLP final con comisiones y margen − transporte − capital inicial`.
La búsqueda y el ranking usan esta misma cantidad. El ranking es **solo** por ganancia neta.

## Búsqueda y ciclos

Búsqueda por capas de 1 a `MAX_STEPS` pasos. En cada paso se guardan los
`SEARCH_BEAM_WIDTH` mejores estados por divisa (más dinero en la misma divisa y paso
siempre domina). Un test compara el resultado con una búsqueda sin límite.

Reglas contra ciclos (SPEC §12):

1. Máximo `MAX_STEPS` operaciones.
2. Una misma operación (casa + sucursal + origen + destino) no se repite en una ruta.
3. Volver a una divisa ya visitada exige tener **más** que la vez anterior: un ciclo con
   pérdida se corta y no puede ser tramo de una ruta mayor.
4. Rutas con las mismas operaciones en distinto orden cuentan como una sola.
5. Solo se devuelven rutas que vuelven a la moneda inicial con ganancia neta > 0.

Con 2 y 3 la búsqueda termina siempre, aunque `MAX_STEPS` sea grande.

## Cotizaciones sospechosas

Las rutas que usan una cotización `ANOMALOUS_QUOTE` o `INVERTED_SPREAD` se mantienen en el
ranking (el ranking no se altera), pero quedan marcadas `requires_verification` y se guardan
con estado `PENDING_VERIFICATION`.

## Sensibilidad (SPEC §28)

`sensitivity(route, (0.002, 0.005, 0.01))` devuelve la ganancia si cada tasa empeora 0,2%,
0,5% y 1%. `python -m app.main analyze` la muestra para cada ruta.

## Disponibilidad y montos (Fase 3)

- `availability = false` publicada: la operación no entra al grafo.
- `min_amount` / `max_amount` (en unidades de la divisa): si el monto de la ruta queda fuera,
  esa operación no se usa (la tasa no aplica al monto completo).
- Cotizaciones con más de `MAX_QUOTE_AGE_MINUTES`: se usan, con bandera `STALE_QUOTE` y menos
  confianza (nunca ALTA). Más antiguas que `MAX_QUOTE_USABLE_HOURS`: no se usan.
- La antigüedad se mide desde el dato más antiguo entre la hora publicada por la casa
  (`timestamp_source`, p. ej. "Última actualización 02 de Octubre, 10:00") y la hora de
  captura: un precio publicado ayer y leído hace un minuto sigue siendo de ayer. Esto solo
  baja la confianza; el filtro de `MAX_QUOTE_USABLE_HOURS` usa la hora de captura.

## Recorrido físico (Fase 4, `route_optimizer.py`)

1. Pasos consecutivos en la misma casa = una visita.
2. Se elige la sucursal de cada visita que minimiza la distancia total (programación dinámica).
3. Distancia: OSRM si `OSRM_URL` está configurado; si no, línea recta × `ROUTE_DISTANCE_FACTOR`.
   Tiempo = traslado (velocidad del modo) + `MINUTES_PER_OPERATION` por operación.
4. Transporte se descuenta de la ganancia neta y luego se reordena el Top. Se cobra un viaje
   por cada cambio de casa y, con `TRANSPORT_FROM_HOME=true`, la ida desde el origen y la vuelta
   (también sin coordenadas: el número de viajes se conoce aunque los km no).
   `TRANSPORT_ALT_COST_PER_TRIP_CLP` muestra cuánto quedaría con otro medio (p. ej. taxi), sin
   cambiar el ranking.
5. Horario: si alguna casa está cerrada al llegar, `executable_now = false` (bandera
   `HOUSE_CLOSED`); si no hay horario publicado, `null` (`HOURS_UNKNOWN`).
6. Sin coordenadas: `DISTANCE_UNKNOWN`, transporte 0 y menos confianza.

## Confianza (`confidence_service.py`)

Parte en 100 y descuenta: cotizaciones antiguas, minutos de traslado, número de pasos,
comisión o disponibilidad no publicada, casa cerrada u horario desconocido, cotización
sospechosa y rutas que dejan de ser rentables si las tasas empeoran 0,5%. ALTA ≥ 75,
MEDIA ≥ 50, BAJA < 50. Cada descuento queda en `warnings`. **No cambia el ranking.**

## Pendiente

- Redondeo a billetes (las casas entregan efectivo en denominaciones).
- Fase 8: modelos sobre el historial (probabilidad de ejecución, duración).
