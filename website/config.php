<?php
// PHP >= 7.4. Do not add credentials here.
declare(strict_types=1);
const SITE_BASE = 'https://www.cristobalgalindo.com/kindle-plus-catalogo-mexico/';
const CATALOG_DATE = '18 al 26 de noviembre de 2026';
const CATALOG_UPDATED_ISO = '2026-11-26';
const PAGE_SIZE = 24;
const CATALOG_FILE = __DIR__ . '/data/books.json';

function e($value): string { return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function streamBooks($catalog): Generator {
    if ($catalog === false) {
        return;
    }
    rewind($catalog);
    $header = fgets($catalog);
    $line = $header !== false && trim($header) === '[' ? fgets($catalog) : false;
    $first = $line === false ? null : json_decode(rtrim(trim($line), ','), true);

    // También admite el JSON compacto de las publicaciones previas.
    if ($line === false || (!is_array($first) && trim($line) !== ']')) {
        rewind($catalog);
        $books = json_decode(stream_get_contents($catalog), true);
        if (is_array($books)) {
            yield from $books;
        }
        return;
    }

    if (is_array($first)) {
        yield $first;
    }
    while (($line = fgets($catalog)) !== false) {
        $line = trim($line);
        if ($line === ']') {
            break;
        }
        $book = json_decode(rtrim($line, ','), true);
        if (is_array($book)) {
            yield $book;
        }
    }
}
function foldText(string $value): string {
    // Normaliza acentos del español antes de usar iconv, cuyo resultado varía por sistema.
    $value = strtr($value, [
        'á'=>'a', 'é'=>'e', 'í'=>'i', 'ó'=>'o', 'ú'=>'u', 'ü'=>'u', 'ñ'=>'n',
        'Á'=>'A', 'É'=>'E', 'Í'=>'I', 'Ó'=>'O', 'Ú'=>'U', 'Ü'=>'U', 'Ñ'=>'N',
    ]);
    $value = preg_replace('/\p{Mn}+/u', '', $value) ?? $value;
    $without = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $value);
    return strtolower($without !== false ? $without : $value);
}

function sitePath(string $relative = ''): string {
    return parse_url(SITE_BASE, PHP_URL_PATH) . $relative;
}

function requestRoute(): string {
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
    $prefix = sitePath();
    if (is_string($path) && strpos($path, $prefix) === 0) {
        return substr($path, strlen($prefix));
    }
    return is_string($path) ? ltrim($path, '/') : '';
}

function queryString(string $key, string $default = ''): string {
    return is_string($_GET[$key] ?? null) ? trim($_GET[$key]) : $default;
}

function normalizedSearch(string $term): string {
    return trim(preg_replace('/[^\p{L}\p{N}]+/u', ' ', foldText($term)) ?? '');
}

function urlSlug(string $text): string {
    $slug = preg_replace('/[^a-z0-9]+/', '-', foldText($text)) ?? '';
    return trim(substr(trim($slug, '-'), 0, 100), '-');
}

function authorsPageList(): array {
    return ['byung-chul-han' => 'Byung-Chul Han'];
}

function bookAuthor(array $book): string {
    return ($book['author_verified'] ?? false) === true && is_string($book['author'] ?? null)
        ? trim($book['author'])
        : '';
}

function bookByAuthor(array $book, string $author): bool {
    foreach (explode(',', bookAuthor($book)) as $credit) {
        if (normalizedSearch($credit) === normalizedSearch($author)) {
            return true;
        }
    }
    return false;
}

function bookPath(array $book): string {
    return 'libro/' . rawurlencode($book['asin']) . '/' . (urlSlug($book['title']) ?: 'detalle') . '/';
}

function bookImage(array $book): ?string {
    $image = (string)($book['image_url'] ?? '');
    $host = strtolower((string)parse_url($image, PHP_URL_HOST));
    return parse_url($image, PHP_URL_SCHEME) === 'https'
        && in_array($host, ['m.media-amazon.com', 'images-na.ssl-images-amazon.com'], true)
        ? $image : null;
}

function findBook(string $asin): ?array {
    $catalog = @fopen(CATALOG_FILE, 'rb');
    try {
        foreach (streamBooks($catalog) as $book) {
            if (($book['asin'] ?? '') === $asin) {
                return $book;
            }
        }
        return null;
    } finally {
        if ($catalog !== false) {
            fclose($catalog);
        }
    }
}

function redirectCatalog(string $url): void {
    header('Location: ' . $url, true, 301);
    exit;
}
function topics(): array {
    // These are HEURISTIC title matches, not Amazon metadata or editorial judgments.
    return [
        'fisica' => ['Física y astronomía', '/\\b(fisic|fisica|cuantic|relatividad|cosmol|astrofis|astronom|agujeros negros|gravitacion|universo|galaxia|boson|feynman|espacio.tiempo)\\b/u'],
        'biologia' => ['Biología y evolución', '/\\b(biolog|evolucion|genetic|genoma|darwin|celulas|ecolog|biodiversidad|microbi|animal|especies)\\b/u'],
        'neuro' => ['Neurociencia y psicología', '/\\b(neuro|cerebro|mente|cognic|psicolog|conducta|memoria|conciencia|aprendizaje|neurona)\\b/u'],
        'filosofia' => ['Filosofía y pensamiento', '/\\b(filosof|epistemolog|etica|logica|estoic|pensamiento critic|razonamiento)\\b/u'],
        'scifi' => ['Ciencia ficción (aproximado)', '/\\b(ciencia ficcion|space opera|cyberpunk|distopia|marciano|androides|extraterrestres|viaje espacial)\\b/u'],
        'matematicas' => ['Matemáticas', '/\\b(matematic|algebra|calculo|geometria|estadistic|probabilidad|teorema)\\b/u'],
        'musica' => ['Música', '/\\b(musica|guitarra|piano|armonia|composicion musical|solfeo|partitura|acordes)\\b/u'],
    ];
}
function matchesTopic(string $title, string $topic): bool {
    $map = topics();
    if (!isset($map[$topic])) return true;
    // Prefix matching handles singular/plural and conjugated forms.
    $patterns = [
      'fisica'=>'/fisic|cuantic|relativ|cosmol|astrofis|astronom|agujero.{0,8}negro|gravit|universo|galax|boson|feynman|espacio.tiempo/u',
      'biologia'=>'/biolog|evoluc|genetic|genoma|darwin|celul|ecolog|biodivers|microbi|animal|especie/u',
      'neuro'=>'/neuro|cerebro|mente|cognic|psicolog|conducta|memoria|conciencia|aprendizaje|neurona/u',
      'filosofia'=>'/filosof|epistemolog|etica|logica|estoic|pensamiento.critic|razonamiento/u',
      'scifi'=>'/ciencia.ficcion|space.opera|cyberpunk|distopia|marcian|androide|extraterrestre|viaje.espacial/u',
      'matematicas'=>'/matematic|algebra|calculo|geometria|estadistic|probabilidad|teorema/u',
      'musica'=>'/musica|guitarra|piano|armonia|composicion.musical|solfeo|partitura|acordes/u'
    ];
    return (bool)preg_match($patterns[$topic], foldText($title));
}
function catalogUrl(string $q, string $topic, int $page, string $sort = 'catalogo'): string {
    $params = [];
    $slug = urlSlug($q);
    $route = $slug === '' ? '' : (isset(authorsPageList()[$slug]) ? $slug . '/' : 'buscar/' . $slug . '/');
    if ($q !== '' && $route === '') $params['q'] = $q;
    if ($topic !== '') $params['tema'] = $topic;
    if ($page > 1) $params['page'] = $page;
    if ($sort !== 'catalogo') $params['orden'] = $sort;
    return sitePath($route) . ($params ? '?' . http_build_query($params, '', '&', PHP_QUERY_RFC3986) : '');
}
