<?php
require __DIR__ . '/config.php';
require __DIR__ . '/book-pages.php';

const SITEMAP_LIMIT = 50000;
const SITEMAP_NAMESPACE = 'http://www.sitemaps.org/schemas/sitemap/0.9';

$route = requestRoute();
$part = preg_match('/^sitemap-([1-9][0-9]{0,4})\.xml$/D', $route, $match) ? (int)$match[1] : 0;
$authors = authorsPageList();
$authorPaths = [''];
$bookPaths = [];
$registered = registeredBookPages();
$catalog = @fopen(CATALOG_FILE, 'rb');
foreach (streamBooks($catalog) as $book) {
    foreach ($authors as $slug => $author) {
        if (bookByAuthor($book, $author)) {
            $authorPaths[] = $slug . '/';
            unset($authors[$slug]);
        }
    }
    $asin = $book['asin'] ?? '';
    if (isset($registered[$asin])) {
        $bookPaths[] = bookPath($book);
        unset($registered[$asin]);
    }
    if (!$authors && !$registered) {
        break;
    }
}
if ($catalog !== false) {
    fclose($catalog);
}

$paths = array_merge($authorPaths, $bookPaths);
$numParts = (int)ceil(count($paths) / SITEMAP_LIMIT);
if ($part > 0 && ($numParts === 1 || $part > $numParts)) {
    http_response_code(404);
    return;
}

header('Content-Type: application/xml; charset=utf-8');
header('Cache-Control: public, max-age=120');
echo '<?xml version="1.0" encoding="UTF-8"?>', "\n";
if ($numParts > 1 && $part === 0) {
    echo '<sitemapindex xmlns="', SITEMAP_NAMESPACE, '">', "\n";
    for ($index = 1; $index <= $numParts; $index++) {
        echo '  <sitemap><loc>', e(SITE_BASE . 'sitemap-' . $index . '.xml'), "</loc></sitemap>\n";
    }
    echo "</sitemapindex>\n";
    return;
}

$mtime = @filemtime(CATALOG_FILE);
$date = $mtime === false ? CATALOG_UPDATED_ISO : gmdate('Y-m-d', $mtime);
$datePaths = array_fill_keys($authorPaths, true);
echo '<urlset xmlns="', SITEMAP_NAMESPACE, '">', "\n";
$pagePaths = $part === 0 ? $paths : array_slice($paths, ($part - 1) * SITEMAP_LIMIT, SITEMAP_LIMIT);
foreach ($pagePaths as $path) {
    echo '  <url><loc>', e(SITE_BASE . $path), '</loc>';
    if (isset($datePaths[$path])) {
        echo '<lastmod>', e($date), '</lastmod>';
    }
    echo "</url>\n";
}
echo "</urlset>\n";
