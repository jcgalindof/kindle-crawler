# Catálogo Kindle+ México · micrositio PHP

Micrositio independiente de WordPress, sin Node, base de datos ni plugins.

## Requisitos
- Apache + PHP 7.4 o superior con extensiones `mbstring` e `iconv`.
- Subir el contenido completo de esta carpeta a `public_html/kindle-plus-catalogo-mexico/` (no la carpeta dentro de otra con el mismo nombre).
- Abrir `https://cristobalgalindo.com/kindle-plus-catalogo-mexico/`.
- Si WordPress captura la ruta, revisar sus reglas de rewrite; en configuración habitual Apache dará prioridad a una carpeta física con index.php.
- Validar que el servidor permita leer `data/books.json` y que tenga suficiente memoria PHP (64 MB suele ser más que suficiente para este catálogo).
- Si el dominio o ruta definitiva cambian, editar `SITE_BASE` en config.php, canonical en index.php y sitemap.xml.

## SEO
- Página principal con HTML renderizado en servidor, descripción, canonical, Open Graph y CollectionPage Schema.
- URLs filtradas tienen noindex para evitar indexar páginas repetitivas o con poco contenido.
- Enviar URL del `sitemap.xml` a Search Console o enlazarlo desde el sitemap del WordPress principal. Un sitemap en subdirectorio no sustituye el sitemap raíz.
- Agregar un enlace hacia este micrositio desde una página indexada de WordPress.

## Datos / limitaciones
- Archivo `data/books.json` generado de `kindle_plus_mexico.csv`, captura del 18/11/2026.
- 6404 ASIN únicos, de los cuales 6346 tenían texto de Kindle+ en la tarjeta de búsqueda. **No se ha comprobado el préstamo en las páginas de producto**.
- No se incluye autor: el crawler extrajo texto promocional en ese campo.
- Etiquetas temáticas inferidas exclusivamente desde títulos. No son categorías de Amazon ni una evaluación de rigor científico.
- Enlaces a URLs canónicas `amazon.com.mx/dp/{ASIN}` sin parámetros de afiliación ni seguimiento.
- No hay imágenes de portada porque el CSV no las contiene. Antes de usar portadas de Amazon, consultar condiciones de licencia y API.
- Los datos se vuelven obsoletos. Actualizar periódicamente con revisión humana y sin eludir barreras de acceso.

## Actualización de contenido
En la computadora local, regenera `data/books.json` a partir del CSV nuevo manteniendo los mismos nombres de campos. Vuelve a subir únicamente `data/books.json` y actualiza fecha de captura en `config.php`, el JSON-LD en `index.php` y `sitemap.xml`.

## Pruebas locales
Desde la carpeta, si PHP está instalado: `php -S 127.0.0.1:8000` y abrir http://127.0.0.1:8000/.

## Privacidad
El sitio no guarda sesiones ni datos de usuarios y no instala scripts de rastreo. No envía consultas a Amazon: solo abre enlaces cuando el visitante da clic.
