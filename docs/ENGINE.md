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
| Transporte | Fase 4 (por ahora 0) |

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

## Pendiente para fases siguientes

- Fase 3: cotizaciones antiguas (`MAX_QUOTE_AGE_MINUTES`), disponibilidad, montos mín/máx,
  casas cerradas, redondeo a billetes.
- Fase 4: distancia, tiempo, transporte y confianza.
