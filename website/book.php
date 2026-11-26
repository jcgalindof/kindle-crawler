<?php
if (!defined('SITE_BASE')) {
    http_response_code(404);
    return;
}
if ($book === null) {
    http_response_code(404);
} else {
    $path = bookPath($book);
    if ($route !== $path || !empty($_SERVER['QUERY_STRING'])) {
        redirectCatalog(sitePath($path));
    }
}

$title = $book['title'] ?? 'Libro no encontrado';
$author = $book !== null ? bookAuthor($book) : '';
$image = $book !== null ? bookImage($book) : null;
$hardcover = null;
if ($book !== null) {
    require_once __DIR__ . '/hardcover.php';
    $hardcover = hardcoverForBook($book);
}
$number = static function (int $value): string {
    return number_format($value, 0, '.', ',');
};
?><!doctype html>
<html lang="es-MX">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title><?=e($title)?> | Kindle+ México</title>
  <?php if ($book !== null): ?>
  <link rel="canonical" href="<?=e(SITE_BASE . $path)?>">
  <meta name="description" content="<?=e($title . ($author !== '' ? ' de ' . $author : '') . '. Consulta esta edición en el catálogo Kindle+ México.')?>">
  <?php else: ?>
  <meta name="robots" content="noindex">
  <?php endif; ?>
  <link rel="stylesheet" href="<?=e(sitePath('assets/style.css?v=4'))?>">
</head>
<body>
<header class="topbar">
  <div class="wrap">
    <a class="brand" href="<?=e(sitePath())?>">Catálogo Kindle+ México</a>
    <a class="reset" href="<?=e(sitePath())?>">Volver al catálogo</a>
  </div>
</header>
<main class="wrap book-detail">
  <?php if ($book === null): ?>
    <h1><?=e($title)?></h1>
    <p>Esta edición no aparece en el catálogo actual.</p>
  <?php else: ?>
    <article class="detail-layout">
      <div class="cover detail-cover">
        <?php if ($image !== null): ?>
          <img src="<?=e($image)?>" alt="<?=e((string)($book['image_alt'] ?? 'Portada de ' . $title))?>">
        <?php else: ?>
          <div class="cover-fallback" aria-hidden="true"><span>LIBRO DIGITAL</span></div>
        <?php endif; ?>
      </div>
      <div>
        <h1><?=e($title)?></h1>
        <?php if ($author !== ''): ?>
          <p class="detail-author"><a href="<?=e(catalogUrl($author, '', 1))?>"><?=e($author)?></a></p>
        <?php endif; ?>
        <p class="meta">ASIN <?=e($book['asin'])?></p>
        <?php if (!empty($book['categories'])): ?>
          <ul class="detail-categories" aria-label="Categorías en Amazon">
            <?php foreach ($book['categories'] as $category): ?><li><?=e($category)?></li><?php endforeach; ?>
          </ul>
        <?php endif; ?>
        <p class="detail-status"><?=!empty($book['eligible']) ? 'Etiqueta Kindle+ detectada' : 'Elegibilidad de Kindle+ por comprobar'?></p>
        <a class="detail-amazon" href="https://www.amazon.com.mx/dp/<?=rawurlencode($book['asin'])?>" target="_blank" rel="noopener noreferrer nofollow">Consultar en Amazon México <span aria-hidden="true">↗</span></a>
        <section class="detail-hardcover" aria-labelledby="hardcover-title">
          <h2 id="hardcover-title">Hardcover</h2>
          <?php if ($hardcover !== null): ?>
            <?php if ($hardcover['rating'] !== null): ?>
              <p class="detail-score"><span aria-hidden="true">★</span> <strong><?=e(number_format($hardcover['rating'], 2, '.', ''))?> / 5</strong> · <?=$number($hardcover['ratings_count'])?> valoraciones</p>
            <?php else: ?>
              <p>Esta obra todavía no tiene calificaciones en Hardcover.</p>
            <?php endif; ?>
            <p><?=$number($hardcover['reviews_count'])?> <?=$hardcover['reviews_count'] === 1 ? 'reseña' : 'reseñas'?> de la obra en Hardcover.</p>
            <a href="https://hardcover.app/books/<?=rawurlencode($hardcover['slug'])?>" target="_blank" rel="noopener noreferrer">Ver la obra y sus reseñas en Hardcover <span aria-hidden="true">↗</span></a>
          <?php else: ?>
            <p>Por ahora no hay datos de Hardcover disponibles para esta edición.</p>
          <?php endif; ?>
        </section>
      </div>
    </article>
  <?php endif; ?>
</main>
</body>
</html>
