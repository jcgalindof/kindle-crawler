<?php
require __DIR__ . '/config.php';
header('Content-Type: text/html; charset=utf-8');
$q = trim((string)($_GET['q'] ?? ''));
$q = preg_replace('/^(.{0,100}).*$/us', '$1', $q) ?? substr($q, 0, 100);
$topic = (string)($_GET['tema'] ?? '');
if (!isset(topics()[$topic])) $topic = '';
$page = max(1, filter_var($_GET['page'] ?? 1, FILTER_VALIDATE_INT) ?: 1);
$sort = (string)($_GET['orden'] ?? 'catalogo');
if (!in_array($sort, ['catalogo','titulo','calificacion'], true)) $sort='catalogo';
$catalog = @fopen(__DIR__ . '/data/books.json', 'rb');
$totalCatalog = 0;
$needle = foldText($q);
$authorFor = static function (array $book): string {
    return ($book['author_verified'] ?? false) === true && is_string($book['author'] ?? null)
        ? trim($book['author'])
        : '';
};
$matches = [];
foreach (streamBooks($catalog) as $position => $book) {
    $totalCatalog++;
    if (
        $needle !== ''
        && strpos(foldText((string)$book['title']), $needle) === false
        && strpos(foldText($authorFor($book)), $needle) === false
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
$qs = function(int $p) use($q,$topic,$sort) {
    $url = catalogUrl($q,$topic,$p);
    if ($sort!=='catalogo') $url .= ($url==='?'?'':'&') . 'orden=' . rawurlencode($sort);
    return $url;
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
<title>Catálogo Kindle+ México: busca entre <?=number_format($totalCatalog, 0, '.', ',')?> libros | Cristóbal Galindo</title>
<meta name="description" content="Explora <?=number_format($totalCatalog,0,'.',',')?> títulos encontrados en Kindle+ México. Busca por título o autor, filtra temas aproximados y consulta su disponibilidad actual en Amazon.">
<meta name="robots" content="<?= $filteredMode ? 'noindex,follow' : 'index,follow' ?>">
<link rel="canonical" href="<?= e(SITE_BASE) ?>">

<!-- Open Graph: Facebook, WhatsApp, LinkedIn -->
<meta property="og:type" content="website">
<meta property="og:locale" content="es_MX">
<meta property="og:site_name" content="Cristóbal Galindo">
<meta property="og:title" content="Catálogo Kindle+ México | <?=number_format($totalCatalog,0,'.',',')?> libros">
<meta property="og:description" content="¿Buscas qué leer? Explora miles de libros de Kindle+ México, filtra por categoría y descubre tu próxima lectura.">
<meta property="og:url" content="https://cristobalgalindo.com/kindle-plus-catalogo-mexico/">
<meta property="og:image" content="https://cristobalgalindo.com/kindle-plus-catalogo-mexico/catalogo-kindle-plus-mexico.png">
<meta property="og:image:secure_url" content="https://cristobalgalindo.com/kindle-plus-catalogo-mexico/catalogo-kindle-plus-mexico.png">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Catálogo Kindle+ México: explora el catálogo y encuentra tu próxima lectura.">

<!-- X / Twitter -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Catálogo Kindle+ México | <?=number_format($totalCatalog,0,'.',',')?> libros">
<meta name="twitter:description" content="Explora el catálogo Kindle+ México por categorías y encuentra tu próxima lectura.">
<meta name="twitter:image" content="https://cristobalgalindo.com/kindle-plus-catalogo-mexico/catalogo-kindle-plus-mexico.png">

<!-- Opcional: color de interfaz en navegadores móviles -->
<meta name="theme-color" content="#0b1530">

<link rel="stylesheet" href="assets/style.css?v=3">
<script type="application/ld+json"><?=json_encode(['@context'=>'https://schema.org','@type'=>'CollectionPage','name'=>'Catálogo Kindle+ México','url'=>SITE_BASE,'inLanguage'=>'es-MX','dateModified'=>CATALOG_UPDATED_ISO,'description'=>'Índice independiente de resultados detectados en Amazon México, con disponibilidad por confirmar.','isPartOf'=>['@type'=>'WebSite','name'=>'Cristóbal Galindo','url'=>'https://cristobalgalindo.com/']], JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE)?></script>
</head>
<body>
<a href="#resultados" class="skip">Ir a resultados</a>
<header class="topbar"><div class="wrap"><a class="brand" href="https://cristobalgalindo.com/">cristobalgalindo.com</a><span class="topnote">Explorador independiente</span></div></header>
<main>
<section class="hero"><div class="wrap">
  <p class="eyebrow">LECTURAS · MÉXICO</p>
  <h1>Catálogo Kindle+ México</h1>
  <p class="lead">Busca entre <strong><?=number_format($totalCatalog,0,'.',',')?> libros</strong> (y contando... cada día agregamos más) detectados en el catálogo mexicano. Sin navegar por cientos de páginas de Amazon.</p>
  <form action="" method="get" class="search-panel" role="search">
    <label for="q">Buscar por título o autor</label>
    <div class="search-row"><input id="q" name="q" type="search" placeholder="Ej. Watchmen, Alan Moore, cosmología..." value="<?=e($q)?>" maxlength="100"><button type="submit">Buscar</button></div>
    <div class="filters"><div><label for="tema">Tema sugerido</label><select name="tema" id="tema"><option value="">Todos los títulos</option><?php foreach(topics() as $key=>$meta): ?><option value="<?=e($key)?>" <?=$topic===$key?'selected':''?>><?=e($meta[0])?></option><?php endforeach; ?></select></div>
    <div><label for="orden">Ordenar</label><select name="orden" id="orden"><option value="catalogo" <?=$sort==='catalogo'?'selected':''?>>Orden de captura</option><option value="titulo" <?=$sort==='titulo'?'selected':''?>>Título A–Z</option><option value="calificacion" <?=$sort==='calificacion'?'selected':''?>>Calificación orientativa</option></select></div></div>
  </form>
  <p class="hero-note">Datos capturados del <?=e(CATALOG_DATE)?>. La disponibilidad puede cambiar. La búsqueda por autor cubre las fichas con un autor verificado.</p>
</div></section>
<section id="resultados" class="wrap results">
  <div class="section-head"><div><h2>Explorar libros</h2><p><?=number_format($total,0,'.',',')?> resultado<?= $total===1?'':'s'?><?= $q!=='' ? ' para «'.e($q).'»':'' ?></p></div><?php if ($filteredMode): ?><a class="reset" href="./">Limpiar filtros</a><?php endif;?></div>
  <?php if (!$visible): ?><div class="empty"><h3>Sin coincidencias</h3><p>Prueba otro término o quita el filtro temático.</p></div><?php else: ?>
  <div class="books">
  <?php foreach($visible as $book): ?>
    <article class="book">
      <div class="cover">
        <div class="cover-fallback" aria-hidden="true"><span>LIBRO DIGITAL</span><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2"><path d="M24 11c-7-4-14-4-20-2v29c7-2 14-2 20 2 6-4 13-4 20-2V9c-6-2-13-2-20 2Zm0 0v29"/></svg></div>
        <?php
          $imageUrl = (string)($book['image_url'] ?? '');
          $imageHost = strtolower((string)(parse_url($imageUrl, PHP_URL_HOST) ?: ''));
          $imageScheme = strtolower((string)(parse_url($imageUrl, PHP_URL_SCHEME) ?: ''));
          $allowedImageHosts = ['m.media-amazon.com', 'images-na.ssl-images-amazon.com'];
          $showImage = $imageScheme === 'https' && in_array($imageHost, $allowedImageHosts, true);
        ?>
        <?php if ($showImage): ?>
          <img src="<?=e($imageUrl)?>" alt="<?=e((string)($book['image_alt'] ?? 'Portada de ' . $book['title']))?>" loading="lazy" decoding="async" onerror="this.style.display='none'">
        <?php endif; ?>
      </div>
      <div class="book-text"><h3><?=e($book['title'])?></h3>
      <?php $author = $authorFor($book); if ($author !== ''): ?><p class="meta"><?=e($author)?></p><?php endif; ?>
      <p class="meta">ASIN <?=e($book['asin'])?></p>
      <?php if ($book['rating'] !== null): ?><p class="rating"><span aria-label="Calificación">★</span> <?=e(number_format((float)$book['rating'],1))?> / 5<?php if($book['reviews'] !== null): ?><small> · <?=number_format((int)$book['reviews'],0,'.',',')?> reseñas</small><?php endif;?></p><?php endif; ?>
      <p class="status <?=$book['eligible']?'found':'unknown'?>"><?=$book['eligible']?'Etiqueta Kindle+ detectada':'Elegibilidad no comprobada'?></p>
      <a class="book-link" href="https://www.amazon.com.mx/dp/<?=rawurlencode($book['asin'])?>" target="_blank" rel="noopener noreferrer nofollow">Consultar en Amazon <span aria-hidden="true">↗</span></a></div>
    </article>
  <?php endforeach; ?>
  </div>
  <nav class="pagination" aria-label="Páginas de resultados"><span>Página <?=number_format($page)?> de <?=number_format($pages)?></span><div><?php if($page>1):?><a href="<?=e($qs($page-1))?>" rel="prev">← Anterior</a><?php endif;?><?php if($page<$pages):?><a href="<?=e($qs($page+1))?>" rel="next">Siguiente →</a><?php endif;?></div></nav>
  <?php endif; ?>
</section>
<section class="wrap about"><h2>¿Qué es este catálogo?</h2><p>Es un proyecto independiente para facilitar la exploración de libros detectados en la búsqueda de Kindle+ en Amazon México. La recopilación procede de resultados visibles del <?=e(CATALOG_DATE)?>, no de una descarga oficial del catálogo completo.</p><p>Una etiqueta Kindle+ en un resultado de búsqueda <strong>no garantiza</strong> que un libro continúe incluido, que esté disponible para tu cuenta o que se pueda tomar en préstamo. Comprueba la ficha del libro antes de decidir. Las calificaciones y reseñas también son datos históricos del momento de captura.</p><p>El campo de autores de la captura original no era confiable y se omitió. Los temas son coincidencias automáticas de palabras en los títulos: pueden incluir falsos positivos y dejar fuera libros relevantes. Ninguna clasificación implica valoración científica o editorial. Este sitio no está afiliado ni avalado por Amazon.</p><p>Kindle, Kindle+ y Amazon son marcas de sus respectivos titulares. Los enlaces dirigen a fichas de Amazon México y no contienen identificadores de afiliado.</p></section>
</main>
<footer><div class="wrap"><span>© <?=date('Y')?> Cristóbal Galindo</span><span>Hecho para encontrar mejores lecturas, no para reemplazar Amazon.</span></div></footer>
</body>
  <!-- Silence is sexy... --> 
</html>
