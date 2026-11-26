<?php
declare(strict_types=1);

require_once __DIR__ . '/hardcover.php';

function registerBookPage(string $asin): void {
    $directory = hardcoverStatePath();
    if (!extension_loaded('pdo_sqlite') || !is_dir($directory)) {
        return;
    }

    try {
        $db = new PDO('sqlite:' . $directory . '/book-pages.sqlite3', null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        ]);
        $db->exec('PRAGMA busy_timeout=800');
        $db->exec('CREATE TABLE IF NOT EXISTS book_pages (asin TEXT PRIMARY KEY)');
        $insert = $db->prepare('INSERT OR IGNORE INTO book_pages (asin) VALUES (?)');
        $insert->execute([$asin]);
    } catch (PDOException $exception) {
        error_log('No se pudo registrar la ficha en el sitemap: ' . $exception->getMessage());
    }
}

function registeredBookPages(): array {
    if (!extension_loaded('pdo_sqlite')) {
        return [];
    }

    $asins = [];
    $directory = hardcoverStatePath();
    // Incluye las fichas abiertas antes de que existiera el registro del sitemap.
    foreach (['book-pages.sqlite3' => 'book_pages', 'hardcover.sqlite3' => 'book_matches'] as $file => $table) {
        $path = $directory . '/' . $file;
        if (!is_readable($path)) {
            continue;
        }
        try {
            $options = class_exists(\Pdo\Sqlite::class)
                ? [\Pdo\Sqlite::ATTR_OPEN_FLAGS => \Pdo\Sqlite::OPEN_READONLY]
                : [PDO::SQLITE_ATTR_OPEN_FLAGS => PDO::SQLITE_OPEN_READONLY];
            $options[PDO::ATTR_ERRMODE] = PDO::ERRMODE_EXCEPTION;
            $db = new PDO('sqlite:' . $path, null, null, $options);
            $db->exec('PRAGMA busy_timeout=800');
            foreach ($db->query('SELECT asin FROM ' . $table, PDO::FETCH_COLUMN, 0) as $asin) {
                $asins[(string)$asin] = true;
            }
        } catch (PDOException $exception) {
            error_log('No se pudo leer el registro del sitemap: ' . $exception->getMessage());
        }
    }
    return $asins;
}
