<?php
require __DIR__ . '/config.php';
header('Content-Type: text/html; charset=utf-8');
$route = requestRoute();
$cleanRoute = trim($route, '/');
$requestedAsin = strtoupper(queryString('asin'));
if (preg_match('~^libro/([a-zA-Z0-9]{10})(?:/[^/]+)?$~D', $cleanRoute, $segments)) {
    $requestedAsin = strtoupper($segments[1]);
}
if ($requestedAsin !== '' || $cleanRoute === 'libro' || strpos($cleanRoute, 'libro/') === 0) {
    $book = preg_match('/^[A-Z0-9]{10}$/D', $requestedAsin) ? findBook($requestedAsin) : null;
    require __DIR__ . '/book.php';
    return;
}

$authorPages = authorsPageList();
$selectedAuthor = $authorPages[$cleanRoute] ?? '';
$q = queryString('q');
if ($selectedAuthor !== '') {
    $q = $selectedAuthor;
} elseif (preg_match('~^buscar/([a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?)$~D', $cleanRoute, $segments)) {
    $q = str_replace('-', ' ', $segments[1]);
} elseif (!in_array($cleanRoute, ['', 'index.php'], true)) {
    http_response_code(404);
    echo '<h1>Página no encontrada</h1><a href="' . e(sitePath()) . '">Volver al catálogo</a>';
    return;
}
$q = preg_replace('/^(.{0,100}).*$/us', '$1', $q) ?? substr($q, 0, 100);
$topic = queryString('tema');
if (!isset(topics()[$topic])) $topic = '';
$page = max(1, filter_var($_GET['page'] ?? 1, FILTER_VALIDATE_INT) ?: 1);
$sort = queryString('orden', 'catalogo');
if (!in_array($sort, ['catalogo','titulo','calificacion'], true)) $sort='catalogo';
$resultsUrl = catalogUrl($q, $topic, $page, $sort);
$resultsPath = parse_url($resultsUrl, PHP_URL_PATH);
if (urlSlug($q) !== '' && sitePath($route) !== $resultsPath) {
    redirectCatalog($resultsUrl);
}
$catalog = @fopen(CATALOG_FILE, 'rb');
$totalCatalog = 0;
$needle = normalizedSearch($q);
$matches = [];
foreach (streamBooks($catalog) as $position => $book) {
    $totalCatalog++;
    if (
        $selectedAuthor !== '' ? !bookByAuthor($book, $selectedAuthor) :
        ($needle !== '' && strpos(normalizedSearch((string)$book['title']), $needle) === false
            && strpos(normalizedSearch(bookAuthor($book)), $needle) === false)
    ) continue;
    if ($topic !== '' && !matchesTopic((string)$book['title'], $topic)) continue;

    if ($sort === 'titulo') {
        $matches[$position] = foldText($book['title']);
    } elseif ($sort === 'calificacion') {
        $matches[$position] = ($book['rating'] ?? 0) * min(1, log(1 + ($book['reviews'] ?? 0)) / log(101));
    } else {
        $matches[$position] = true;
    }
}
if ($sort === 'titulo') {
    asort($matches, SORT_STRING);
} elseif ($sort === 'calificacion') {
    arsort($matches, SORT_NUMERIC);
}
$total = count($matches);
$pages = max(1, (int)ceil($total/PAGE_SIZE));
$page = min($page,$pages);
$positions = array_keys(array_slice($matches, ($page-1)*PAGE_SIZE, PAGE_SIZE, true));
$wanted = array_flip($positions);
$selected = [];
if ($wanted) {
    // Usar el mismo archivo abierto mantiene las dos lecturas en la misma versión del catálogo.
    foreach (streamBooks($catalog) as $position => $book) {
        if (isset($wanted[$position])) {
            $selected[$position] = $book;
            if (count($selected) === count($wanted)) break;
        }
    }
}
if ($catalog !== false) fclose($catalog);
$visible = array_map(static function ($position) use ($selected) { return $selected[$position]; }, $positions);
$filteredMode = ($q!=='' || $topic!=='' || $page>1 || $sort!=='catalogo');
$authorLanding = $selectedAuthor !== '' && $total > 0 && $topic === '' && $page === 1 && $sort === 'catalogo';
$canonical = $authorLanding ? SITE_BASE . $cleanRoute . '/' : SITE_BASE;
$heading = $selectedAuthor !== '' ? 'Libros de ' . $selectedAuthor . ' en Kindle+ México' : 'Catálogo Kindle+ México';
$title = $q !== '' ? ($selectedAuthor !== '' ? $heading : $q . ' en Kindle+ México')
    : $heading . ': busca entre ' . number_format($totalCatalog, 0, '.', ',') . ' libros';
$description = $selectedAuthor !== '' ? 'Explora las ediciones de ' . $selectedAuthor . ' detectadas en Kindle+ México.'
    : 'Explora ' . number_format($totalCatalog, 0, '.', ',') . ' títulos encontrados en Kindle+ México y consulta su disponibilidad en Amazon.';
$qs = static function (int $p) use ($q, $topic, $sort): string {
    return catalogUrl($q, $topic, $p, $sort);
};
?><!doctype html>
<html lang="es-MX">
<head>
<script async src="https://www.googletagmanager.com/gtm.js?id=G-EN9JHYKEP3"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?=e($title)?> | Cristóbal Galindo</title>
<meta name="description" content="<?=e($description)?>">
<meta name="robots" content="<?= $filteredMode && !$authorLanding ? 'noindex,follow' : 'index,follow' ?>">
<link rel="canonical" href="<?=e($canonical)?>">

<!-- Open Graph: Facebook, WhatsApp, LinkedIn -->
<meta property="og:type" content="website">
<meta property="og:locale" content="es_MX">
<meta property="og:site_name" content="Cristóbal Galindo">
<meta property="og:title" content="<?=e($title)?>">
<meta property="og:description" content="¿Buscas qué leer? Explora miles de libros de Kindle+ México, filtra por categoría y descubre tu próxima lectura.">
<meta property="og:url" content="<?=e($canonical)?>">
<meta property="og:image" content="<?=e(SITE_BASE . 'catalogo-kindle-plus-mexico.png')?>">
<meta property="og:image:secure_url" content="<?=e(SITE_BASE . 'catalogo-kindle-plus-mexico.png')?>">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Catálogo Kindle+ México: explora el catálogo y encuentra tu próxima lectura.">

<!-- X / Twitter -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="<?=e($title)?>">
<meta name="twitter:description" content="Explora el catálogo Kindle+ México por categorías y encuentra tu próxima lectura.">
<meta name="twitter:image" content="<?=e(SITE_BASE . 'catalogo-kindle-plus-mexico.png')?>">

<!-- Opcional: color de interfaz en navegadores móviles -->
<meta name="theme-color" content="#0b1530">

<link rel="stylesheet" href="<?=e(sitePath('assets/style.css?v=5'))?>">
<script type="application/ld+json"><?=json_encode(['@context'=>'https://schema.org','@type'=>'CollectionPage','name'=>$heading,'url'=>$canonical,'inLanguage'=>'es-MX','dateModified'=>CATALOG_UPDATED_ISO,'description'=>$description,'isPartOf'=>['@type'=>'WebSite','name'=>'Cristóbal Galindo','url'=>'https://cristobalgalindo.com/']], JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE|JSON_HEX_TAG)?></script>
</head>
<body>
<a href="#resultados" class="skip">Ir a resultados</a>
<header class="topbar"><div class="wrap"><a class="brand" href="https://cristobalgalindo.com/">cristobalgalindo.com</a><a class="about-link" href="#acerca-de">Acerca de</a></div></header>
<main>
<section class="hero"><div class="wrap">
  <p class="eyebrow">LECTURAS · MÉXICO</p>
  <h1><?=e($heading)?></h1>
  <p class="lead">Busca entre <strong><?=number_format($totalCatalog,0,'.',',')?> libros</strong> (y contando... cada día agregamos más) detectados en el catálogo mexicano. Sin navegar por cientos de páginas de Amazon.</p>
  <form action="<?=e(sitePath())?>" method="get" class="search-panel" role="search">
    <label for="q">Buscar por título o autor</label>
    <div class="search-row"><input id="q" name="q" type="search" placeholder="Ej. Watchmen, Alan Moore, cosmología..." value="<?=e($q)?>" maxlength="100"><button type="submit">Buscar</button></div>
    <div class="filters"><div><label for="tema">Tema sugerido</label><select name="tema" id="tema"><option value="">Todos los títulos</option><?php foreach(topics() as $key=>$meta): ?><option value="<?=e($key)?>" <?=$topic===$key?'selected':''?>><?=e($meta[0])?></option><?php endforeach; ?></select></div>
    <div><label for="orden">Ordenar</label><select name="orden" id="orden"><option value="catalogo" <?=$sort==='catalogo'?'selected':''?>>Orden de captura</option><option value="titulo" <?=$sort==='titulo'?'selected':''?>>Título A–Z</option><option value="calificacion" <?=$sort==='calificacion'?'selected':''?>>Calificación orientativa</option></select></div></div>
  </form>
  <p class="hero-note">Datos capturados del <?=e(CATALOG_DATE)?>. La disponibilidad puede cambiar. La búsqueda por autor cubre las fichas con un autor verificado.</p>
</div></section>
<section id="resultados" class="wrap results">
  <div class="section-head"><div><h2>Explorar libros</h2><p><?=number_format($total,0,'.',',')?> resultado<?= $total===1?'':'s'?><?= $q!=='' ? ' para «'.e($q).'»':'' ?></p></div><?php if ($filteredMode): ?><a class="reset" href="<?=e(sitePath())?>">Limpiar filtros</a><?php endif;?></div>
  <?php if (!$visible): ?><div class="empty"><h3>Sin coincidencias</h3><p>Prueba otro término o quita el filtro temático.</p></div><?php else: ?>
  <div class="books">
  <?php foreach($visible as $book): ?>
    <article class="book">
      <div class="cover">
        <div class="cover-fallback" aria-hidden="true"><span>LIBRO DIGITAL</span><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><path d="M24 11c-7-4-14-4-20-2v29c7-2 14-2 20 2 6-4 13-4 20-2V9c-6-2-13-2-20 2Zm0 0v29"/></svg></div>
        <?php $imageUrl = bookImage($book); if ($imageUrl !== null): ?>
          <img src="<?=e($imageUrl)?>" alt="<?=e((string)($book['image_alt'] ?? 'Portada de ' . $book['title']))?>" loading="lazy" decoding="async" onerror="this.style.display='none'">
        <?php endif; ?>
      </div>
      <div class="book-text"><h3><?=e($book['title'])?></h3>
      <?php $author = bookAuthor($book); if ($author !== ''): ?><p class="meta"><?=e($author)?></p><?php endif; ?>
      <p class="meta">ASIN <?=e($book['asin'])?></p>
      <?php if ($book['rating'] !== null): ?><p class="rating"><span aria-label="Calificación">★</span> <?=e(number_format((float)$book['rating'],1))?> / 5<?php if($book['reviews'] !== null): ?><small> · <?=number_format((int)$book['reviews'],0,'.',',')?> reseñas</small><?php endif;?></p><?php endif; ?>
      <p class="status <?=$book['eligible']?'found':'unknown'?>"><?=$book['eligible']?'Etiqueta Kindle+ detectada':'Elegibilidad no comprobada'?></p>
      <a class="book-link" href="<?=e(sitePath(bookPath($book)))?>" aria-label="<?=e('Ver detalle de ' . $book['title'])?>">Ver detalle <span aria-hidden="true">→</span></a></div>
    </article>
  <?php endforeach; ?>
  </div>
  <nav class="pagination" aria-label="Páginas de resultados"><span>Página <?=number_format($page)?> de <?=number_format($pages)?></span><div><?php if($page>1):?><a href="<?=e($qs($page-1))?>" rel="prev">← Anterior</a><?php endif;?><?php if($page<$pages):?><a href="<?=e($qs($page+1))?>" rel="next">Siguiente →</a><?php endif;?></div></nav>
  <?php endif; ?>
</section>
<section class="wrap about"><h2>¿Qué es este catálogo?</h2><p>Es un proyecto independiente para facilitar la exploración de libros detectados en la búsqueda de Kindle+ en Amazon México. La recopilación procede de resultados visibles del <?=e(CATALOG_DATE)?>, no de una descarga oficial del catálogo completo.</p><p>Una etiqueta Kindle+ en un resultado de búsqueda <strong>no garantiza</strong> que un libro continúe incluido, que esté disponible para tu cuenta o que se pueda tomar en préstamo. Comprueba la ficha del libro antes de decidir. Las calificaciones de Amazon corresponden al momento de captura.</p><p>Se muestran los autores verificados en Amazon. Los temas se sugieren a partir de los títulos. Este sitio no está afiliado ni avalado por Amazon.</p><p>Kindle, Kindle+ y Amazon son marcas de sus respectivos titulares. Los enlaces a Amazon México no contienen identificadores de afiliado.</p></section>
<section class="wrap about author-about" id="acerca-de" aria-labelledby="author-about-heading">
  <img class="author-portrait" src="<?=e(sitePath('assets/cristobal-galindo.webp'))?>" alt="Cristóbal Galindo" width="886" height="886" loading="lazy" decoding="async">
  <div>
    <h2 id="author-about-heading">Acerca de Cristóbal Galindo</h2>
    <p>Soy especialista en Salesforce Marketing Cloud. Entre mis lecturas hay filosofía, cómics y lo que se atraviese.</p>
    <p>Hago este catálogo con ayuda de <strong>Lykaia</strong>, mi instancia de ChatGPT Work, para encontrar qué leer en Kindle+ México.</p>
    <ul class="author-profiles" aria-label="Mis perfiles de lectura">
      <li><a href="https://www.goodreads.com/jcgalindof">Goodreads</a></li>
      <li><a href="https://hardcover.app/@jcgalindof">Hardcover</a></li>
    </ul>
  </div>
</section>
</main>
<footer><div class="wrap"><span>© <?=date('Y')?> Cristóbal Galindo</span><span>Hecho para encontrar mejores lecturas, no para reemplazar Amazon.</span></div></footer>
</body>
  <!-- Silence is sexy... --> 
</html>
