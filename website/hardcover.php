<?php
declare(strict_types=1);

const HARDCOVER_FIELDS = 'id slug title rating ratings_count reviews_count';
const HARDCOVER_SUCCESS_TTL = 14 * 86400;
const HARDCOVER_MISS_TTL = 7 * 86400;

function hardcoverStatePath(): string {
    return getenv('KINDLE_HARDCOVER_STATE_DIR') ?: dirname(__DIR__, 2) . '/.kindle-plus';
}

function hardcoverTitle(string $title): string {
    return trim(preg_replace('/\s*[\[(][^)\]]*(?:edici[oó]n|\bed\.?|edition)[^)\]]*[\])]\s*$/iu', '', $title) ?? $title);
}

function hardcoverRequest(PDO $db, string $token, string $query, array $variables): array {
    $now = time();
    $cutoff = (int)(floor($now / 86400) * 86400);
    $db->exec('DELETE FROM api_usage WHERE requested_at < ' . min($cutoff, $now - 60));
    $used = $db->query('SELECT SUM(requested_at >= ' . $cutoff . ') AS today, '
        . 'SUM(requested_at >= ' . ($now - 60) . ') AS minute FROM api_usage')->fetch(PDO::FETCH_ASSOC);
    $backoffUntil = (int)$db->query('SELECT until_time FROM api_backoff WHERE id = 1')->fetchColumn();
    if ($backoffUntil > $now || (int)$used['today'] >= 500 || (int)$used['minute'] >= 40) {
        throw new RuntimeException('Presupuesto de consultas de Hardcover en pausa');
    }
    $db->exec('INSERT INTO api_usage (requested_at) VALUES (' . $now . ')');

    $request = curl_init('https://api.hardcover.app/v1/graphql');
    curl_setopt_array($request, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode(['query' => $query, 'variables' => $variables], JSON_THROW_ON_ERROR),
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT_MS => 1200,
        CURLOPT_TIMEOUT_MS => 3500,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Authorization: Bearer ' . $token],
        CURLOPT_USERAGENT => 'KindleMexico/1.0 (cristobalgalindo.com)',
    ]);
    $body = curl_exec($request);
    $status = (int)curl_getinfo($request, CURLINFO_RESPONSE_CODE);
    if ($status !== 200 || !is_string($body)) {
        $delay = $status === 401 || $status === 403 ? 900 : 120;
        $db->exec('INSERT OR REPLACE INTO api_backoff (id, until_time) VALUES (1, ' . ($now + $delay) . ')');
        throw new RuntimeException('Hardcover no disponible');
    }
    $response = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
    if (!empty($response['errors']) || !is_array($response['data'] ?? null)) {
        $db->exec('INSERT OR REPLACE INTO api_backoff (id, until_time) VALUES (1, ' . ($now + 120) . ')');
        throw new RuntimeException('Hardcover rechazó la consulta');
    }
    return $response['data'];
}

function hardcoverStats(array $item): ?array {
    $id = filter_var($item['id'] ?? null, FILTER_VALIDATE_INT);
    $slug = $item['slug'] ?? '';
    if ($id === false || $id < 1 || !is_string($slug) || !preg_match('/^[a-z0-9_-]+$/D', $slug)) {
        return null;
    }
    $rating = (float)($item['rating'] ?? 0);
    $ratings = max(0, (int)($item['ratings_count'] ?? 0));
    return [
        'id' => $id,
        'slug' => $slug,
        'rating' => $rating > 0 && $rating <= 5 && $ratings > 0 ? $rating : null,
        'ratings_count' => $ratings,
        'reviews_count' => max(0, (int)($item['reviews_count'] ?? 0)),
    ];
}

function hardcoverMatch(array $documents, string $title, string $credit): ?array {
    $titleKey = normalizedSearch($title);
    $authors = array_map('normalizedSearch', explode(',', $credit));
    $matches = [];
    foreach ($documents as $item) {
        $titles = array_merge([$item['title'] ?? ''], (array)($item['alternative_titles'] ?? []));
        $matchTitle = false;
        foreach ($titles as $alternative) {
            $matchTitle = $matchTitle || (is_string($alternative)
                && $titleKey === normalizedSearch(hardcoverTitle($alternative)));
        }
        if (!$matchTitle) {
            continue;
        }
        foreach ($item['contributions'] ?? [] as $contributor) {
            $role = normalizedSearch((string)($contributor['contributor_role_name'] ?? $contributor['contribution'] ?? ''));
            $name = normalizedSearch((string)($contributor['author']['name'] ?? ''));
            if (in_array($role, ['author', 'co author', 'coauthor'], true)
                && $name !== '' && in_array($name, $authors, true)) {
                $stats = hardcoverStats($item);
                if ($stats !== null) {
                    $matches[$stats['id']] = $stats;
                }
                break;
            }
        }
    }
    return count($matches) === 1 ? reset($matches) : null;
}

function hardcoverLookup(PDO $db, string $token, array $book, ?array $cached): ?array {
    if ($cached !== null) {
        $query = 'query($id:Int!) { books(where:{id:{_eq:$id}},limit:1){' . HARDCOVER_FIELDS . '} }';
        $data = hardcoverRequest($db, $token, $query, ['id' => $cached['id']]);
        $stats = hardcoverStats($data['books'][0] ?? []);
        return $stats ?? $cached;
    }

    $author = bookAuthor($book);
    $title = hardcoverTitle($book['title']);
    if (normalizedSearch($title) !== '' && $author !== '') {
        $query = 'query($term:String!) { search(query:$term,query_type:"Book",per_page:8){error results} }';
        $data = hardcoverRequest($db, $token, $query, ['term' => $title . ' ' . explode(',', $author, 2)[0]]);
        if (!empty($data['search']['error']) || !is_array($data['search']['results']['hits'] ?? null)
            || !empty($data['search']['results']['search_cutoff'])) {
            throw new RuntimeException('Búsqueda de Hardcover incompleta');
        }
        $documents = array_column($data['search']['results']['hits'], 'document');
        $stats = hardcoverMatch($documents, $title, $author);
        if ($stats !== null) {
            return $stats;
        }
    }

    $query = 'query($asin:String!) { editions(where:{asin:{_eq:$asin}},limit:5){book{' . HARDCOVER_FIELDS . '}} }';
    $data = hardcoverRequest($db, $token, $query, ['asin' => $book['asin']]);
    $matches = [];
    foreach ($data['editions'] ?? [] as $edition) {
        $stats = hardcoverStats($edition['book'] ?? []);
        if ($stats !== null) {
            $matches[$stats['id']] = $stats;
        }
    }
    return count($matches) === 1 ? reset($matches) : null;
}

function hardcoverCached(PDO $db, string $asin, string $signature): array {
    $select = $db->prepare('SELECT payload, saved_at FROM book_matches WHERE asin = ? AND signature = ?');
    $select->execute([$asin, $signature]);
    $row = $select->fetch(PDO::FETCH_ASSOC);
    if (!$row) {
        return [null, false];
    }
    $cached = $row['payload'] === null ? null : json_decode($row['payload'], true);
    $ttl = $cached === null ? HARDCOVER_MISS_TTL : HARDCOVER_SUCCESS_TTL;
    return [$cached, time() - (int)$row['saved_at'] < $ttl];
}

function hardcoverForBook(array $book): ?array {
    $state = hardcoverStatePath();
    if (!extension_loaded('pdo_sqlite') || !extension_loaded('curl') || !is_readable($state . '/hardcover.token')) {
        return null;
    }
    $token = trim((string)@file_get_contents($state . '/hardcover.token'));
    if (!preg_match('/^[A-Za-z0-9._-]+$/D', $token)) {
        return null;
    }

    $cached = null;
    $lock = null;
    try {
        $db = new PDO('sqlite:' . $state . '/hardcover.sqlite3', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
        $db->exec('PRAGMA busy_timeout=100');
        $db->exec('CREATE TABLE IF NOT EXISTS book_matches (asin TEXT PRIMARY KEY, signature TEXT NOT NULL, payload TEXT, saved_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS api_usage (requested_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS api_backoff (id INTEGER PRIMARY KEY, until_time INTEGER NOT NULL)');
        $asin = $book['asin'];
        $signature = hash('sha256', $book['title'] . "\n" . bookAuthor($book));
        [$cached, $fresh] = hardcoverCached($db, $asin, $signature);
        if ($fresh) {
            return $cached;
        }

        $lock = @fopen($state . '/hardcover.lock', 'c');
        if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) {
            return $cached;
        }
        [$cached, $fresh] = hardcoverCached($db, $asin, $signature);
        if ($fresh) {
            return $cached;
        }
        $stats = hardcoverLookup($db, $token, $book, $cached);
        $save = $db->prepare('INSERT OR REPLACE INTO book_matches (asin, signature, payload, saved_at) VALUES (?, ?, ?, ?)');
        $payload = $stats === null ? null : json_encode($stats, JSON_THROW_ON_ERROR);
        $save->execute([$asin, $signature, $payload, time()]);
        return $stats;
    } catch (RuntimeException | JsonException $exception) {
        return $cached;
    } finally {
        if (is_resource($lock)) {
            fclose($lock);
        }
    }
}
