<?php
require __DIR__ . '/config.php';

header('Content-Type: application/xml; charset=utf-8');
header('Cache-Control: public, max-age=600');
$authors = authorsPageList();
$paths = [''];
$catalog = @fopen(CATALOG_FILE, 'rb');
foreach (streamBooks($catalog) as $book) {
    foreach ($authors as $slug => $author) {
        if (bookByAuthor($book, $author)) {
            $paths[] = $slug . '/';
            unset($authors[$slug]);
        }
    }
    if (!$authors) {
        break;
    }
}
if ($catalog !== false) {
    fclose($catalog);
}
$mtime = @filemtime(CATALOG_FILE);
$date = $mtime === false ? CATALOG_UPDATED_ISO : gmdate('Y-m-d', $mtime);
echo '<?xml version="1.0" encoding="UTF-8"?>', "\n";
echo '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">', "\n";
foreach ($paths as $path) {
    echo '  <url><loc>', e(SITE_BASE . $path), '</loc><lastmod>', e($date), "</lastmod></url>\n";
}
echo "</urlset>\n";
