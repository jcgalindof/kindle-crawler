<?php
// PHP >= 7.4. Do not add credentials here.
declare(strict_types=1);
const SITE_BASE = 'https://cristobalgalindo.com/kindle-plus-catalogo-mexico/';
const CATALOG_DATE = '18 al 25 de noviembre de 2026';
const CATALOG_UPDATED_ISO = '2026-11-25';
const PAGE_SIZE = 24;

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
function catalogUrl(string $q, string $topic, int $page): string {
    $params = [];
    if ($q !== '') $params['q'] = $q;
    if ($topic !== '') $params['tema'] = $topic;
    if ($page > 1) $params['page'] = $page;
    return '?' . http_build_query($params, '', '&', PHP_QUERY_RFC3986);
}
