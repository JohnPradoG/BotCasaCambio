# PROYECTO: BOT DE ARBITRAJE MULTIDIVISA ENTRE CASAS DE CAMBIO — SANTIAGO DE CHILE

Quiero desarrollar un sistema profesional en Python que detecte oportunidades de arbitraje entre casas de cambio físicas de Santiago de Chile.

## 1. OBJETIVO PRINCIPAL

El sistema debe comenzar con un capital configurable, por defecto:

**$1.000.000 CLP**

y buscar automáticamente las rutas de intercambio que permitan terminar con la mayor cantidad posible de pesos chilenos (CLP).

NO quiero que el sistema busque solamente USD.

NO quiero que el sistema busque solamente arbitraje directo.

NO quiero que el sistema favorezca una moneda determinada.

El objetivo es:

> **Encontrar la ruta legal y físicamente ejecutable que maximice el dinero final en CLP después de todos los costos, spreads, comisiones y costos estimados de desplazamiento.**

El algoritmo debe ser libre para utilizar cualquier moneda disponible en las casas de cambio.

---

# 2. EJEMPLO DEL CONCEPTO

Si comienzo con:

$1.000.000 CLP

el sistema podría encontrar:

### Ruta 1

CLP → USD → CLP

Resultado:

$1.025.000 CLP

Ganancia:

+$25.000

### Ruta 2

CLP → USD → EUR → CLP

Resultado:

$1.043.000 CLP

Ganancia:

+$43.000

### Ruta 3

CLP → USD → CLP → EUR → CLP

Resultado:

$1.068.000 CLP

Ganancia:

+$68.000

El sistema debe poder detectar que la Ruta 3 es mejor.

IMPORTANTE:

El hecho de volver a CLP NO debe considerarse automáticamente como el final de la operación.

CLP debe ser tratado como una moneda normal dentro del grafo.

Por ejemplo:

CLP → USD → CLP → EUR → CLP

puede ser una ruta válida si produce más dinero.

---

# 3. NO BUSCAR UNA MONEDA: BUSCAR DINERO

Esta es una regla fundamental del proyecto:

> El algoritmo no debe preguntarse "¿cuál es la mejor moneda?"

Debe preguntarse:

> "¿Cuál es la combinación de operaciones que me permite terminar con la mayor cantidad de CLP?"

Por lo tanto debe evaluar:

* USD
* EUR
* GBP
* CAD
* AUD
* CHF
* JPY
* BRL
* ARS
* PEN
* COP
* MXN
* y cualquier otra moneda que realmente ofrezcan las casas de cambio.

No limitar el sistema a una lista fija si los datos permiten detectar nuevas monedas.

---

# 4. LAS 3 MEJORES OPORTUNIDADES

El sistema debe buscar todas las rutas válidas y mostrar como resultado principal:

### 🥇 Primera mejor oportunidad

Mayor ganancia neta estimada.

### 🥈 Segunda mejor oportunidad

Segunda mayor ganancia neta.

### 🥉 Tercera mejor oportunidad

Tercera mayor ganancia neta.

El ranking debe hacerse principalmente por:

**CLP finales - CLP iniciales - costos**

NO por porcentaje.

NO por cantidad de operaciones.

NO por distancia.

NO por moneda.

---

# 5. LA DISTANCIA NO DEBE ELIMINAR UNA OPORTUNIDAD RENTABLE

Esto es MUY IMPORTANTE.

Si una ruta genera:

+$68.000

y otra:

+$47.000

pero la primera está más lejos, la primera debe seguir apareciendo como #1.

La distancia y el tiempo deben utilizarse para calcular:

* riesgo de ejecución
* tiempo de traslado
* posibilidad de cambio de cotización
* costo estimado de transporte
* confianza de la oportunidad

pero NO deben hacer que automáticamente desaparezca la oportunidad de mayor rentabilidad.

Ejemplo:

| Ruta | Ganancia | Distancia | Tiempo |
| ---- | -------: | --------: | -----: |
| A    |  $68.000 |      8 km | 25 min |
| B    |  $54.000 |      2 km | 10 min |
| C    |  $47.000 |      1 km |  6 min |

El sistema debe mostrar:

🥇 A +$68.000
🥈 B +$54.000
🥉 C +$47.000

pero debe indicar que A tiene mayor riesgo de ejecución por distancia/tiempo.

---

# 6. DATOS QUE DEBE RECOPILAR

El sistema debe intentar encontrar casas de cambio físicas de Santiago de Chile mediante fuentes públicas de Internet.

Para cada casa de cambio almacenar:

* nombre
* dirección
* comuna
* teléfono
* WhatsApp si existe
* página web
* URL donde aparece la cotización
* horario
* coordenadas GPS si se pueden obtener legalmente de fuentes públicas
* monedas disponibles
* precio de compra
* precio de venta
* fecha/hora de actualización
* fecha/hora en que nuestro sistema obtuvo el dato
* fuente del dato
* estado de disponibilidad si está publicado
* restricciones de monto si están publicadas
* comisión si está publicada
* observaciones

No inventar ningún dato.

Si un dato no está disponible:

`NULL`

o equivalente.

---

# 7. OBTENCIÓN DE COTIZACIONES

Crear un sistema modular de scrapers.

Cada casa de cambio puede tener una estructura diferente.

Por eso NO quiero un scraper gigante.

Crear una arquitectura como:

scrapers/
base_scraper.py
casa_01.py
casa_02.py
casa_03.py
...

Cada scraper debe devolver un formato normalizado.

Ejemplo:

```python
{
    "exchange_house": "Nombre",
    "currency": "USD",
    "buy_rate": 950.0,
    "sell_rate": 970.0,
    "timestamp": "...",
    "source_url": "...",
    "availability": True
}
```

Si una página utiliza JavaScript:

usar Playwright cuando sea necesario.

Si existe API pública:

preferir API.

Si existe JSON embebido:

utilizarlo.

Si existe HTML:

utilizar requests/BeautifulSoup cuando sea suficiente.

Respetar robots.txt, términos de uso y límites razonables de consulta.

No intentar saltarse CAPTCHAs, bloqueos ni sistemas de autenticación.

---

# 8. NORMALIZACIÓN DE COMPRA Y VENTA

Este punto es crítico.

Cada casa puede presentar:

"Compra"

"Venta"

"Compro"

"Vendo"

etc.

El sistema debe normalizar el significado.

Definición estándar:

`buy_rate`:

precio al que la casa compra la moneda al cliente.

` sell_rate`:

precio al que la casa vende la moneda al cliente.

Ejemplo:

USD:

Compra: 940 CLP

Venta: 970 CLP

Si nosotros tenemos CLP y queremos USD:

utilizamos el precio de VENTA.

Si tenemos USD y queremos CLP:

utilizamos el precio de COMPRA.

No confundir nunca estas dos operaciones.

---

# 9. MODELO DE GRAFO

Representar el mercado como un grafo.

Los nodos representan monedas.

Ejemplo:

CLP
USD
EUR
GBP
JPY
BRL

Las operaciones representan aristas.

Ejemplo:

CLP → USD

significa comprar USD usando CLP.

USD → CLP

significa vender USD por CLP.

Cada casa de cambio puede generar sus propias aristas.

Por ejemplo:

Casa A:

CLP → USD

Casa B:

USD → CLP

Esto permite detectar arbitraje entre diferentes casas.

---

# 10. MULTIPLES CASAS DE CAMBIO

Una ruta puede utilizar diferentes casas.

Ejemplo:

Casa A:

CLP → USD

Casa B:

USD → EUR

Casa C:

EUR → CLP

El sistema debe poder detectar esta ruta.

También:

Casa A:

CLP → USD

Casa B:

USD → CLP

Casa C:

CLP → EUR

Casa D:

EUR → CLP

Debe ser válida.

---

# 11. CLP PUEDE SER UN NODO INTERMEDIO

NO imponer:

"una vez que llego a CLP, la ruta termina."

Eso sería incorrecto.

CLP debe ser un nodo normal.

Ejemplo válido:

CLP → USD → CLP → EUR → CLP

Si esta ruta produce más CLP que cualquier otra ruta válida, debe aparecer como la mejor.

---

# 12. EVITAR CICLOS INFINITOS

El sistema debe evitar rutas absurdas como:

CLP → USD → CLP → USD → CLP → USD...

Implementar límites configurables.

Por defecto:

`MAX_STEPS = 5`

También controlar:

* estados repetidos
* misma moneda + misma casa
* rutas idénticas
* operaciones que no generan beneficio
* ciclos con pérdidas
* rutas que solamente repiten operaciones

El sistema debe explorar suficientemente el espacio de búsqueda sin entrar en ciclos infinitos.

---

# 13. PROFUNDIDAD DE BÚSQUEDA

Inicialmente probar:

1 operación
2 operaciones
3 operaciones
4 operaciones
5 operaciones

Por defecto:

`MAX_STEPS = 5`

Debe ser configurable.

Posteriormente quiero poder probar 6, 7 o más si el rendimiento del servidor lo permite.

---

# 14. CAPITAL INICIAL

Configurable.

Por defecto:

`1_000_000 CLP`

Pero quiero poder cambiarlo:

500.000
1.000.000
2.000.000
5.000.000
10.000.000

El motor debe recalcular automáticamente las rutas.

---

# 15. RESTRICCIONES DE DISPONIBILIDAD

Una oportunidad no debe considerarse completamente ejecutable solamente porque exista una cotización.

Debe revisar, cuando sea posible:

* disponibilidad de la moneda
* stock
* monto máximo
* monto mínimo
* restricciones
* horario
* si la casa está abierta
* si el precio aplica al monto completo

Si la casa publica que una tasa es solamente para montos pequeños, el sistema debe considerarlo.

---

# 16. COMISIONES

El cálculo debe incorporar:

* comisión fija
* comisión porcentual
* comisión por operación
* costos adicionales conocidos

Si no existe comisión publicada:

marcar:

`commission_unknown = True`

y no inventarla.

El sistema debe permitir configurar una comisión estimada manualmente.

---

# 17. COSTO DE TRANSPORTE

La distancia debe convertirse en un costo estimado.

Crear configuración:

```text
TRANSPORT_COST_PER_KM
```

y permitir diferentes métodos:

* caminar
* transporte público
* vehículo
* taxi/Uber

Inicialmente puede utilizarse una estimación configurable.

El costo de transporte debe restarse de la ganancia neta cuando corresponda.

---

# 18. DISTANCIA ENTRE CASAS

Para rutas físicas:

Casa A → Casa B → Casa C

calcular:

A → B

B → C

y:

distancia total.

También estimar:

tiempo total.

Guardar:

```text
distance_km
estimated_minutes
```

Si no existe un servicio de mapas disponible, crear una interfaz preparada para integrar posteriormente:

Google Maps
OpenStreetMap
OSRM
u otro proveedor.

Preferir inicialmente soluciones gratuitas o de bajo costo.

---

# 19. TIEMPO Y RIESGO DE CAMBIO DE COTIZACIÓN

Una cotización puede cambiar mientras el usuario se desplaza.

Por eso cada oportunidad debe mostrar:

* edad de cada cotización
* distancia
* tiempo estimado
* cantidad de operaciones
* nivel de confianza

Ejemplo:

```text
Cotización USD: actualizada hace 1 min
Cotización EUR: actualizada hace 3 min
Tiempo estimado: 18 min

Confianza: MEDIA
```

NO afirmar que una oportunidad está garantizada.

---

# 20. CONFIRMACIÓN TELEFÓNICA / WHATSAPP

El bot NO debe ejecutar compras automáticamente.

Su función es:

1. detectar
2. calcular
3. alertar
4. facilitar la verificación humana

Para cada casa mostrar:

* teléfono
* WhatsApp
* dirección

si están disponibles públicamente.

También generar automáticamente un mensaje de verificación.

Ejemplo:

"Hola, quisiera cambiar aproximadamente $1.000.000 CLP a USD en efectivo. ¿Me pueden confirmar el tipo de cambio actual, el monto final que recibiría y si tienen disponibilidad para realizar la operación hoy?"

Para una ruta posterior:

"¿Mantienen esta tasa para un monto aproximado de USD X?"

---

# 21. ESTADOS DE UNA OPORTUNIDAD

Cada oportunidad debe tener estados:

`DETECTED`

`PENDING_VERIFICATION`

`VERIFIED`

`EXPIRED`

`EXECUTED`

`FAILED`

`PARTIALLY_EXECUTED`

Esto permitirá estudiar posteriormente qué oportunidades eran reales.

---

# 22. ALERTAS TELEGRAM

Crear integración con Telegram.

Cuando encuentre una oportunidad importante enviar algo parecido a:

```text
🔥 ARBITRAJE DETECTADO

Capital inicial:
$1.000.000 CLP

🥇 OPCIÓN #1

Ganancia estimada:
+$68.000 CLP

Capital final:
$1.068.000 CLP

Ruta:

Casa A
CLP → USD
USD comprado: 1.030

↓

Casa B
USD → EUR
EUR recibido: 950

↓

Casa C
EUR → CLP
CLP final: $1.068.000

Distancia total:
8,2 km

Tiempo estimado:
25 min

Cotizaciones:
Actualizadas hace 1-3 min

Confianza:
🟡 MEDIA

⚠️ Confirmar precios y disponibilidad antes de desplazarse.

Casa A:
Dirección:
Teléfono:
WhatsApp:

Casa B:
Dirección:
Teléfono:
WhatsApp:

Casa C:
Dirección:
Teléfono:
WhatsApp:
```

Después:

```text
🥈 OPCIÓN #2
Ganancia: +$54.000
Distancia: 2 km
Tiempo: 10 min

🥉 OPCIÓN #3
Ganancia: +$47.000
Distancia: 1 km
Tiempo: 6 min
```

---

# 23. SOLO ALERTAR OPORTUNIDADES SIGNIFICATIVAS

Configurar:

`MIN_NET_PROFIT_CLP`

Ejemplo inicial:

$10.000

Si una oportunidad genera solamente:

+$2.000

no enviar alerta.

Pero sí almacenarla en la base de datos para análisis.

---

# 24. MOTOR DE OPTIMIZACIÓN

Crear un módulo independiente:

`arbitrage_engine.py`

Debe:

1. recibir cotizaciones normalizadas
2. crear el grafo
3. generar rutas
4. calcular cada conversión
5. aplicar spreads
6. aplicar comisiones
7. aplicar costos de transporte
8. verificar restricciones
9. calcular CLP final
10. calcular ganancia
11. calcular porcentaje
12. calcular distancia
13. calcular tiempo
14. calcular confianza
15. eliminar rutas inválidas
16. ordenar por CLP final
17. devolver las 3 mejores

---

# 25. FUNCIÓN PRINCIPAL

Crear algo conceptualmente similar a:

```python
find_best_routes(
    initial_currency="CLP",
    initial_amount=1_000_000,
    max_steps=5,
    top_n=3
)
```

Resultado:

```python
[
    route_1,
    route_2,
    route_3
]
```

Cada ruta debe contener:

```python
{
    "rank": 1,
    "initial_clp": 1000000,
    "final_clp": 1068000,
    "gross_profit_clp": 68000,
    "net_profit_clp": 65000,
    "profit_percent": 6.5,
    "steps": 4,
    "distance_km": 8.2,
    "estimated_minutes": 25,
    "confidence": "MEDIUM",
    "route": [...],
    "quotes": [...],
    "houses": [...]
}
```

---

# 26. IMPORTANTE: GANANCIA BRUTA VS GANANCIA NETA

Mostrar ambas.

Ejemplo:

Ganancia bruta:

+$72.000

Transporte:

-$5.000

Comisiones:

-$2.000

Margen de seguridad:

-$0

Ganancia neta estimada:

**+$65.000**

El ranking debe utilizar:

**GANANCIA NETA**

---

# 27. MARGEN DE SEGURIDAD

Crear una configuración:

`SAFETY_MARGIN_PERCENT`

Ejemplo:

1%

Si la ruta parece producir:

$1.050.000

el sistema puede simular un pequeño deterioro de las cotizaciones antes de considerarla una oportunidad fuerte.

No asumir que la tasa permanecerá igual.

---

# 28. SIMULACIÓN DE CAMBIO DE COTIZACIÓN

Quiero posteriormente poder simular:

¿Qué pasa si cada tasa cambia 0,2%?

¿Qué pasa si cambia 0,5%?

¿Qué pasa si cambia 1%?

El sistema debe poder mostrar:

```text
Ganancia con cotización actual: +$68.000
Ganancia con -0,5%: +$52.000
Ganancia con -1%: +$34.000
```

Esto ayuda a medir qué tan resistente es la oportunidad.

---

# 29. HISTORIAL

Guardar TODAS las cotizaciones recopiladas.

No solamente las oportunidades.

Necesito histórico para estudiar:

* qué casa suele tener mejores precios
* qué monedas presentan más oportunidades
* horarios donde aparecen oportunidades
* cuánto duran
* qué casas publican cotizaciones desactualizadas
* qué oportunidades fueron verificadas
* cuáles realmente pudieron ejecutarse
* cuáles desaparecieron
* cuáles fueron falsas señales

---

# 30. BASE DE DATOS

Inicialmente usar:

SQLite

para mantener el sistema barato y sencillo.

Diseñar el código de forma que posteriormente pueda migrarse a:

PostgreSQL

Tablas sugeridas:

```text
exchange_houses
currencies
quotes
routes
route_steps
opportunities
verifications
executions
transport_costs
scraper_runs
```

---

# 31. HISTORIAL DE COTIZACIONES

Tabla `quotes`:

```text
id
exchange_house_id
currency
buy_rate
sell_rate
timestamp_source
timestamp_collected
source_url
availability
min_amount
max_amount
commission
```

---

# 32. HISTORIAL DE OPORTUNIDADES

Guardar:

* fecha
* hora
* capital inicial
* ruta
* casas
* monedas
* tasas utilizadas
* CLP final estimado
* ganancia
* distancia
* tiempo
* confianza
* estado
* resultado de verificación

---

# 33. APRENDIZAJE HISTÓRICO

NO necesito comenzar con inteligencia artificial.

Primero quiero construir una base de datos sólida.

Posteriormente el sistema podrá analizar:

* qué casas suelen cumplir sus cotizaciones
* qué fuentes son más confiables
* qué horarios generan oportunidades
* qué monedas generan oportunidades reales
* qué rutas suelen fallar
* cuánto tiempo duran las oportunidades
* qué porcentaje de oportunidades publicadas son realmente ejecutables

Posteriormente se puede agregar Machine Learning.

---

# 34. SISTEMA DE PUNTUACIÓN

IMPORTANTE:

No utilizar una puntuación para reemplazar el ranking de rentabilidad.

El ranking principal debe seguir siendo:

**mayor ganancia neta en CLP.**

La puntuación puede utilizarse solamente como indicador de confianza.

Ejemplo:

```text
Profit:
+$68.000

Confidence:
72/100
```

No hacer:

"esta tiene 90 puntos y por eso es #1".

La posición #1 debe corresponder a la mayor ganancia neta.

---

# 35. DETECCIÓN DE DATOS SOSPECHOSOS

Si una casa publica:

USD compra = 1.500 CLP

cuando todas las demás están cerca de 900-1.000 CLP,

NO asumir automáticamente que existe arbitraje.

Marcar:

`ANOMALOUS_QUOTE`

y solicitar verificación.

Esto es fundamental para evitar falsos arbitrajes por errores de publicación.

---

# 36. COTIZACIONES DESACTUALIZADAS

Configurar:

```text
MAX_QUOTE_AGE_MINUTES
```

Por ejemplo:

10 minutos.

Una cotización con más de 10 minutos puede:

* seguir almacenándose
* utilizarse para análisis histórico
* pero reducir la confianza
* y no considerarse una oportunidad de alta confianza

Configurable.

---

# 37. CASA CERRADA

Si conocemos horario de funcionamiento:

si está cerrada, no marcar la ruta como inmediatamente ejecutable.

Puede almacenarse como oportunidad futura.

---

# 38. SEGURIDAD

No realizar automáticamente:

* compras
* ventas
* transferencias
* pagos
* reservas

El sistema es exclusivamente:

**detección + análisis + alerta + seguimiento.**

Todas las operaciones físicas serán realizadas y confirmadas por el usuario.

---

# 39. PANEL WEB

Crear opcionalmente un pequeño dashboard usando:

FastAPI

y una interfaz sencilla.

Debe mostrar:

### Dashboard

* oportunidades actuales
* top 3
* cotizaciones
* casas
* mapa posteriormente
* historial
* oportunidades verificadas
* oportunidades ejecutadas
* estadísticas

No quiero una interfaz exageradamente compleja al principio.

Primero funcionalidad.

---

# 40. ARQUITECTURA

Organizar el proyecto aproximadamente así:

```text
currency_arbitrage/
│
├── app/
│   ├── main.py
│   │
│   ├── config/
│   │   └── settings.py
│   │
│   ├── scrapers/
│   │   ├── base.py
│   │   ├── registry.py
│   │   └── exchanges/
│   │
│   ├── models/
│   │   ├── currency.py
│   │   ├── quote.py
│   │   ├── exchange_house.py
│   │   └── opportunity.py
│   │
│   ├── services/
│   │   ├── quote_service.py
│   │   ├── arbitrage_engine.py
│   │   ├── route_optimizer.py
│   │   ├── distance_service.py
│   │   ├── confidence_service.py
│   │   ├── verification_service.py
│   │   └── history_service.py
│   │
│   ├── notifications/
│   │   └── telegram.py
│   │
│   ├── database/
│   │   ├── db.py
│   │   └── models.py
│   │
│   └── api/
│       └── routes.py
│
├── tests/
│
├── scripts/
│
├── data/
│
├── logs/
│
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

Puedes mejorar esta estructura si encuentras una arquitectura mejor.

---

# 41. CONFIGURACIÓN

Toda configuración importante debe estar fuera del código.

Usar `.env`.

Ejemplo:

```text
INITIAL_CAPITAL_CLP=1000000
MAX_STEPS=5
TOP_ROUTES=3
MIN_NET_PROFIT_CLP=10000
MAX_QUOTE_AGE_MINUTES=10
SAFETY_MARGIN_PERCENT=0.5
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DATABASE_URL=
TRANSPORT_MODE=
TRANSPORT_COST_PER_KM=
```

---

# 42. LOGGING

Crear logs claros.

Ejemplo:

```text
[INFO] Scraping Casa A
[INFO] USD buy=950 sell=970
[INFO] Scraping Casa B
[INFO] EUR buy=1030 sell=1060
[INFO] 342 rutas generadas
[INFO] 37 rutas válidas
[INFO] Top 3 calculado
[INFO] Telegram enviado
```

Registrar errores de scraper individualmente.

Si una casa deja de funcionar, NO debe caerse todo el sistema.

---

# 43. SCRAPERS RESISTENTES

Cada scraper debe tener:

* timeout
* retry
* logging
* manejo de errores
* validación de datos
* timestamp
* detección de cambios de estructura

Un scraper roto no debe detener los demás.

---

# 44. DESCUBRIMIENTO DE CASAS

Crear inicialmente un módulo que permita registrar casas manualmente.

Posteriormente crear descubrimiento automático mediante búsquedas públicas.

No asumir que "todas las casas" se pueden detectar perfectamente.

El sistema debe indicar:

```text
Houses discovered:
XX

Houses with active quotes:
XX

Houses unavailable:
XX
```

---

# 45. VERIFICACIÓN DE OPORTUNIDADES

Crear una pantalla/comando para cambiar el estado.

Ejemplo:

```text
Opportunity #125

[1] Verified
[2] Failed
[3] Executed
[4] Expired
```

Guardar la razón.

Ejemplo:

```text
FAILED

Reason:
"Casa no tenía suficiente USD al precio publicado."
```

Esto será importantísimo para el aprendizaje futuro.

---

# 46. RESULTADO FINAL DEL ALGORITMO

El sistema debe responder algo como:

```text
CAPITAL INICIAL
$1.000.000 CLP

TOP 3 ARBITRAJES

🥇 #1
Ganancia neta: +$68.000
CLP final: $1.068.000
Ruta: CLP → USD → EUR → CLP
Casas: A → B → C
Distancia: 8,2 km
Tiempo: 25 min
Confianza: MEDIA

🥈 #2
Ganancia neta: +$54.000
CLP final: $1.054.000
Ruta: CLP → GBP → CLP
Casas: A → D
Distancia: 2 km
Tiempo: 10 min
Confianza: ALTA

🥉 #3
Ganancia neta: +$47.000
CLP final: $1.047.000
Ruta: CLP → USD → CLP
Casas: C → B
Distancia: 1 km
Tiempo: 6 min
Confianza: ALTA
```

---

# 47. REGLA FUNDAMENTAL DEL PROYECTO

Quiero que tengas presente esta regla durante TODO el desarrollo:

> **El bot no debe buscar la ruta más corta.**
>
> **No debe buscar la ruta con menos operaciones.**
>
> **No debe buscar solamente USD.**
>
> **No debe evitar volver a CLP.**
>
> **No debe favorecer una casa de cambio.**
>
> **Debe buscar la ruta que produzca la mayor cantidad de CLP netos posible, siempre que sea una operación físicamente y legalmente ejecutable.**

La distancia, tiempo, antigüedad de la cotización, disponibilidad y costos se utilizan para determinar la calidad/riesgo de ejecución, no para ocultar una oportunidad de mayor rentabilidad.

---

# 48. PRIORIDAD DE DESARROLLO

NO intentes construir todo de golpe.

Desarrollar por fases.

## FASE 1

Crear:

* arquitectura
* configuración
* base de datos
* modelos
* sistema de cotizaciones
* scraper base
* primer scraper real
* normalización

## FASE 2

Crear:

* grafo
* motor de conversiones
* rutas de 1-5 pasos
* CLP como nodo intermedio
* prevención de ciclos
* cálculo de ganancia

## FASE 3

Crear:

* múltiples casas
* múltiples monedas
* top 3
* comisiones
* disponibilidad
* cotizaciones antiguas

## FASE 4

Crear:

* distancias
* tiempos
* transporte
* confianza
* riesgo

## FASE 5

Crear:

* Telegram
* mensajes
* teléfonos
* WhatsApp
* direcciones
* instrucciones de verificación

## FASE 6

Crear:

* histórico
* seguimiento
* verificación
* ejecutadas
* fallidas
* análisis estadístico

## FASE 7

Crear:

* dashboard
* mapas
* estadísticas
* aprendizaje histórico

## FASE 8

Posteriormente:

* Machine Learning
* predicción de duración de oportunidades
* detección automática de cotizaciones sospechosas
* estimación de probabilidad de ejecución

---

# 49. TESTING

Crear tests unitarios.

Probar especialmente:

### Test 1

CLP → USD → CLP con pérdida.

Debe descartarse.

### Test 2

CLP → USD → CLP con ganancia.

Debe detectarse.

### Test 3

CLP → USD → EUR → CLP.

Debe calcularse correctamente.

### Test 4

CLP → USD → CLP → EUR → CLP.

Debe permitirse.

### Test 5

Ruta con mayor ganancia pero mayor distancia.

Debe aparecer #1 por ganancia.

### Test 6

Ruta con cotización antigua.

Debe reducir confianza.

### Test 7

Casa cerrada.

No debe marcarse como ejecutable inmediatamente.

### Test 8

Comisión.

Debe descontarse.

### Test 9

Transporte.

Debe descontarse de la ganancia neta.

### Test 10

Dos rutas con ganancias similares.

Ambas deben poder aparecer en el Top 3.

### Test 11

Ciclo infinito.

Debe bloquearse.

### Test 12

Cotización anormal.

Debe marcarse como sospechosa.

---

# 50. LO QUE NECESITO DE TI COMO DESARROLLADOR

No quiero solamente una explicación.

Quiero que construyas el proyecto.

Primero analiza todo este requerimiento.

Después:

1. Propón la arquitectura final.
2. Explica cualquier modificación importante que recomiendes.
3. Crea la estructura de carpetas.
4. Crea los archivos.
5. Implementa el código.
6. Implementa tests.
7. Crea `.env.example`.
8. Crea `requirements.txt`.
9. Crea `README.md`.
10. Explica cómo instalarlo en Linux.
11. Explica cómo ejecutarlo.
12. Explica cómo configurar Telegram.
13. Explica cómo agregar una nueva casa de cambio.
14. Explica cómo cambiar el capital inicial.
15. Explica cómo cambiar el número de oportunidades mostradas.
16. Explica cómo cambiar el número máximo de pasos.
17. Explica cómo cambiar el costo de transporte.

NO inventes datos de casas de cambio.

Cuando necesites información actual de casas de cambio de Santiago, utiliza fuentes públicas y oficiales cuando estén disponibles.

Si no puedes verificar un dato, indícalo.

---

# 51. IMPORTANTE SOBRE EL DESARROLLO

No sacrifiques la calidad del motor de arbitraje por hacer una interfaz bonita.

La prioridad es:

1. Datos correctos
2. Conversión correcta
3. Rutas correctas
4. Cálculo correcto
5. Rentabilidad neta
6. Distancia/tiempo
7. Verificación
8. Historial
9. Alertas
10. Interfaz

---

# 52. RESULTADO QUE QUIERO AL FINAL

Quiero tener un bot funcionando en un VPS Linux económico.

El bot debe ejecutarse automáticamente.

Ejemplo:

Cada 1-5 minutos:

1. consulta las casas
2. actualiza cotizaciones
3. detecta oportunidades
4. calcula todas las rutas
5. elimina rutas inválidas
6. calcula ganancias
7. calcula distancia/tiempo
8. calcula confianza
9. obtiene Top 3
10. compara con oportunidades anteriores
11. si aparece una oportunidad nueva o significativamente mejor:
    envía Telegram
12. guarda todo en la base de datos.

El sistema debe ser modular para poder agregar posteriormente más casas, monedas, mapas, fuentes de datos y modelos de aprendizaje.

---

# 53. REGLA FINAL

La métrica principal del proyecto es:

**¿Cuántos CLP puedo tener al final comenzando con $1.000.000 CLP?**

No:

"¿Cuántas operaciones hice?"

No:

"¿Cuál moneda tuvo mayor movimiento?"

No:

"¿Cuál casa tiene el mejor dólar?"

No:

"¿Cuál ruta es más corta?"

Sino:

> **¿Cuál ruta de intercambio disponible actualmente produce el mayor CLP final neto y puede ser razonablemente ejecutada?**

Construye el sistema alrededor de esta regla.
