Los archivos de esta carpeta son **fixtures sintéticos para tests**: los precios
son inventados y no corresponden a ninguna casa de cambio real. Solo reproducen
estructuras posibles de página para probar los extractores.

Excepción: `gamaex.html`, `cambios_lyon.html`, `inmonex.html`, `brollano_*.html` y `cambio_costero.html` reproducen la
estructura y los valores que esas casas publicaban el 2026-10-03, reconstruidos a
partir de una lectura en texto de sus páginas (no son el HTML original). Sirven para
probar los formatos de número y las etiquetas de cada sitio; no son cotizaciones vigentes.

`cambio_costero_wcps.html` sí es HTML original: recorte de https://www.ccostero.cl/
descargado desde el VPS el 2026-10-03 (solo los dos carruseles de precios).
