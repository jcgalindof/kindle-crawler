# Kindle+ México 2.0

El crawler recorre las 26 categorías temáticas inmediatas de Kindle+ definidas
en `data/amazon_main_categories.json`. Mezcla por ASIN, conserva metadatos
válidos y mantiene categorías múltiples. El catálogo general se conserva como
parte del historial de las corridas previas. La página de referencia de Kindle+
es la siguiente.

`https://www.amazon.com.mx/b/ref=ku_br_rw_lp_mn?node=9257648011`

## 1. Validar una sola página

Esta prueba revisa tarjetas, evidencia Kindle+ y autores en una sola categoría.
Por defecto elige Arte y Fotografía. Puedes elegir otra con `--category`.

```bash
cd /Volumes/External/kindle-crawler
.venv/bin/python kindle_crawler.py --validate-only
```

## 2. Iniciar o reanudar el recorrido

```bash
cd /Volumes/External/kindle-crawler
.venv/bin/python kindle_crawler.py
```

El mismo comando inicia un recorrido o recupera el último avance. Espera a que
termine la sesión abierta o ciérrala con Ctrl+C antes de lanzar otra. Amazon
decide qué páginas ofrece mediante su enlace «Siguiente». El total anunciado
en el encabezado es una estimación de resultados.

Si el avance anterior registró 25 páginas por fuente en todo el recorrido, el
crawler vuelve a abrir sólo la página 25 de cada fuente para recuperar «Siguiente»
y procesa desde la 26 cuando esté disponible. La página 25 sólo se usa para
obtener el enlace. En un avance parcial, la fuente en curso continúa desde su
checkpoint. Las fuentes anteriores con un avance incierto se revisan de nuevo.
Usa `--restart` sólo si quieres archivar el avance y comenzar otro recorrido.

Para ver qué mostró Amazon si el crawler se detiene por un error:

```bash
.venv/bin/python kindle_crawler.py --keep-open-on-error
```

El crawler guarda el avance y espera en la Terminal hasta que presiones Enter
para cerrar el navegador.

## Prueba pequeña opcional

Procesa hasta una página de Cómics y Novelas Gráficas, mezcla el resultado con 2.0
y guarda la siguiente página para reanudar.

```bash
.venv/bin/python kindle_crawler.py --category "Cómics y Novelas Gráficas" --pages 1
```

## Archivos 2.0

- `data/kindle_plus_mexico_2.0.json`
- `data/kindle_plus_mexico_2.0.csv`
- `data/kindle_plus_mexico_2.0_progress.json`
- `data/kindle_plus_mexico_2.0_report.json`

El reporte incluye ASIN nuevos, páginas completadas, cobertura de metadatos
y el avance por fuente. Si Amazon vuelve a mostrar una página ya procesada,
queda registrada como `repeated_page`.

## Enriquecer autores desde las fichas

Amazon ya no publica el autor en todas las tarjetas. El crawler deja ese campo
vacío antes que guardar promociones u ofertas como nombres. Valida una sola
ficha sin modificar el catálogo:

```bash
.venv/bin/python kindle_enrich_amazon_authors.py --validate-only --asin B0CDXQZJV4
```

Después puedes enriquecer por lotes reanudables:

```bash
.venv/bin/python kindle_enrich_amazon_authors.py --limit 100
```

Para continuar el siguiente lote, ejecuta el mismo comando. Para procesar todos
los pendientes en una sesión, omite `--limit`. El script crea un respaldo con
SHA-256 antes de su primera escritura y guarda cada 10 fichas. Los ASIN nuevos
de corridas posteriores se añaden automáticamente a la cola; usa `--restart`
sólo si quieres volver a revisar también los que ya fueron procesados.

## Exportar para el sitio PHP

```bash
.venv/bin/python build_kindle_web_catalog.py
```

El resultado compatible sigue siendo `data/books.web.json`. El exportador lee
primero el catálogo 2.0 y usa el catálogo legado sólo si 2.0 todavía no existe.

Si Amazon muestra CAPTCHA o bloqueo, el crawler se detiene y conserva el último
checkpoint; no intenta evadirlo.
