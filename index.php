<?php
/**
 * iTunes API Proxy v3.1.0 – MySQL Edition (Multi-Platform Attachments)
 *
 * v3.1.0 changes:
 *  ✔ Multi-platform attachments (telegram default, bale, eitaa, rubika, igap, whatsapp, other)
 *  ✔ Auto platform detection from URL (t.me → telegram, bale.ai → bale, ...)
 *  ✔ platform column added to entityMirrors (default 'telegram')
 *  ✔ Read filter: defaults to telegram; use platform=all|* for everything
 *  ✔ platform field emitted on every attachment item
 *
 * v3.0.0 (retained): users, social, playlists, library, apps, tokens, webhooks
 * v2.7.x (retained): batch attachment loading, artist/tracks pagination
 */

error_reporting(E_ALL);
ini_set('display_errors', 0);
ini_set('log_errors', 1);

/* ═══════════════ CONFIG ═══════════════ */

define('DEST_HOST', 'localhost');
define('DEST_NAME', 'rahir111_mm');
define('DEST_USER', 'rahir111_mm');
define('DEST_PASS', '%rOy9OZXJ%gQ');
define('DEST_PORT', 3306);

define('SQLITE_DB_FILE', __DIR__ . '/download_queue.sqlite');
define('DB_PERSISTENT', true);
define('DB_MAX_RETRIES', 2);
define('DB_CONNECTION_TIMEOUT', 5);
define('CHUNK_SIZE', 100);

define('CACHE_DURATION', 21600);
define('ITUNES_SEARCH_API', 'https://itunes.apple.com/search');
define('ITUNES_LOOKUP_API', 'https://itunes.apple.com/lookup');
define('BATCH_SIZE', 500);
define('ENABLE_GZIP', true);
define('RATE_LIMIT_MAX_RETRIES', 5);
define('RATE_LIMIT_BASE_DELAY', 0.5);
define('RATE_LIMIT_MAX_DELAY', 30);
define('ITUNES_RATE_LIMIT_PER_MINUTE', 50);
define('USE_PROXY_ROTATION', true);
define('PROXY_LIST_FILE', __DIR__ . '/proxies.txt');
define('ENABLE_REQUEST_THROTTLING', true);
define('THROTTLE_MIN_INTERVAL', 50000);
define('ENABLE_USER_AGENT_ROTATION', true);
define('ENABLE_IP_SPOOFING', true);
define('CACHE_ADAPTIVE_TTL', true);
define('SMART_CACHE_PRELOAD', true);
define('SUPPORTED_AUDIO_QUALITIES', ['320', '192', '128']);
define('DEFAULT_AUDIO_QUALITY', '320');
define('LONG_TRACK_THRESHOLD_MS', 8 * 60 * 1000);
define('LONG_TRACK_ONLY_QUALITY', '192');
define('LYRICS_SEARCH_MIN_LENGTH', 3);
define('LYRICS_SEARCH_MAX_RESULTS', 50);
define('VIEW_SESSION_TTL', 1800);
define('VIEW_LOG_RETENTION', 7 * 86400);
define('API_TOKEN', 'change_me_to_a_secure_token');

define('SITE_URL',          'https://mm.3rah.ir');
define('SPA_BASE_PATH',     '');
define('SITEMAP_MAX_URLS',  50000);
define('SITEMAP_FILE_PATH', __DIR__ . '/sitemap.xml');

define('GOOGLE_PING_ENABLED',    false);
define('INDEXNOW_ENABLED',       false);
define('INDEXNOW_KEY',           'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6');
define('INDEXNOW_ENDPOINT',      'https://api.indexnow.org/indexnow');
define('AUTO_SUBMIT_ON_REBUILD', true);
define('AUTO_SUBMIT_MAX_URLS',   10000);
define('AUTO_SUBMIT_BATCH_SIZE', 10000);
define('AUTO_SUBMIT_AFTER_NEW',  500);
define('GOOGLE_PING_URL',        'https://www.google.com/ping?sitemap=');

define('DOWNLOAD_STATUS_PENDING',     'pending');
define('DOWNLOAD_STATUS_DOWNLOADING', 'downloading');
define('DOWNLOAD_STATUS_PAUSED',      'paused');
define('DOWNLOAD_STATUS_COMPLETED',   'completed');
define('DOWNLOAD_STATUS_FAILED',      'failed');
define('DOWNLOAD_STATUS_STOPPED',     'stopped');

define('POPULAR_WINDOW_DAYS',      7);
define('POPULAR_MIN_RECENT_VIEWS', 1);
define('POPULAR_CACHE_ENABLED',    true);
define('SCHEMA_VERSION', '3.1.0');

/* Auth / Social / Apps */
define('USER_SESSION_TTL', 30 * 86400);
define('API_TOKEN_DEFAULT_TTL', 90 * 86400);
define('PASSWORD_MIN_LENGTH', 8);
define('USERNAME_MIN_LENGTH', 3);
define('USERNAME_MAX_LENGTH', 32);
define('COMMENT_MAX_LENGTH', 2000);
define('PLAYLIST_MAX_TRACKS', 5000);
define('NOTIFICATIONS_MAX_UNREAD', 500);
define('ENABLE_REGISTRATION', true);
define('ENABLE_EMAIL_VERIFICATION', false);
define('API_RATE_LIMIT_PER_MINUTE', 120);
define('TRUST_MASTER_TOKEN', true);

/* Platform */
define('DEFAULT_PLATFORM', 'telegram');
define('SUPPORTED_PLATFORMS', ['telegram', 'bale', 'eitaa', 'rubika', 'igap', 'whatsapp', 'other']);

$db = null; $dbConnectedAt = 0;
$sqliteDb = null; $statements = []; $sqliteStatements = [];
$lastRequestTime = 0; $currentProxyIndex = 0;
$GLOBALS['_ctx'] = [
    'user'   => null,
    'appId'  => null,
    'tokenId'=> null,
    'scopes' => [],
    'auth'   => 'none',
];

$GLOBALS['_userAgents'] = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
];

/* ═══════════════ ID / HASH HELPERS ═══════════════ */

function generateId(int $bytes = 16): string { return bin2hex(random_bytes($bytes)); }
function generateToken(): string { return bin2hex(random_bytes(32)); }
function hashToken(string $token): string { return hash('sha256', $token); }
function hashPassword(string $password): string { return password_hash($password, PASSWORD_BCRYPT); }
function verifyPassword(string $password, string $hash): bool { return password_verify($password, $hash); }
function nowSql(): string { return date('Y-m-d H:i:s'); }

function jsonEncode($v): string {
    $j = json_encode($v, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($j === false) throw new RuntimeException('json_encode failed: ' . json_last_error_msg());
    return $j;
}

/* ═══════════════ PLATFORM HELPERS ═══════════════ */

function normalizePlatform(?string $p): ?string
{
    if ($p === null) return null;
    $p = strtolower(trim($p));
    if ($p === '') return null;
    $aliases = [
        'tg' => 'telegram', 'telegram' => 'telegram', 'telegram_bot' => 'telegram',
        'bale' => 'bale', 'bale_ai' => 'bale', 'بله' => 'bale',
        'eitaa' => 'eitaa', 'ایتا' => 'eitaa',
        'rubika' => 'rubika', 'روبیکا' => 'rubika',
        'igap' => 'igap', 'اینستاگرام_پیامرسان' => 'igap',
        'whatsapp' => 'whatsapp', 'wa' => 'whatsapp',
    ];
    if (isset($aliases[$p])) return $aliases[$p];
    return in_array($p, SUPPORTED_PLATFORMS, true) ? $p : 'other';
}

/**
 * تشخیص پلتفرم از URL (اگر $explicit داده شده، همان برگردانده میشود).
 */
function detectPlatformFromUrl(string $url, ?string $explicit = null): string
{
    $exp = normalizePlatform($explicit);
    if ($exp !== null) return $exp;

    $url = trim($url);
    if ($url === '') return DEFAULT_PLATFORM;
    if (stripos($url, 'tg://') === 0)   return 'telegram';
    if (stripos($url, 'bale://') === 0) return 'bale';
    if (stripos($url, 'eitaa://') === 0) return 'eitaa';
    if (stripos($url, 'rubika://') === 0) return 'rubika';

    $host = strtolower((string)parse_url($url, PHP_URL_HOST));
    if ($host === '') return DEFAULT_PLATFORM;

    if (preg_match('/(^|\.)(t\.me|telegram\.(me|org|dog))$/i', $host))  return 'telegram';
    if (preg_match('/(^|\.)bale\.ai$/i', $host))                       return 'bale';
    if (preg_match('/(^|\.)eitaa\.(com|ir)$/i', $host))                return 'eitaa';
    if (preg_match('/(^|\.)rubika\.ir$/i', $host))                     return 'rubika';
    if (preg_match('/(^|\.)igap\.chat$/i', $host))                     return 'igap';
    if (preg_match('/(^|\.)whatsapp\.(com|net)$/i', $host))            return 'whatsapp';

    return 'other';
}

/**
 * تصمیم میگیرد برای خواندن از کدام پلتفرم فیلتر شود.
 *  - پارامتر خالی/نامعلوم → DEFAULT_PLATFORM ('telegram')
 *  - 'all' یا '*' → null (بدون فیلتر)
 *  - در غیر این صورت → همان پلتفرم نرمالشده
 */
function resolveReadPlatformFilter(?string $platform): ?string
{
    if ($platform === null) return DEFAULT_PLATFORM;
    $p = strtolower(trim($platform));
    if ($p === '') return DEFAULT_PLATFORM;
    if ($p === 'all' || $p === '*') return null;
    return normalizePlatform($p) ?? DEFAULT_PLATFORM;
}

/* ═══════════════ SITEMAP ═══════════════ */

function normalizeSitemapDate($date, bool $forOutput = false): string
{
    $fallback = $forOutput ? gmdate('Y-m-d\TH:i:s\Z') : gmdate('Y-m-d H:i:s');
    if ($date === null || $date === '' || $date === false) return $fallback;
    $date = trim((string)$date);
    if ($date === '') return $fallback;
    if (strpos($date, '0000-00-00') === 0 || strpos($date, '0000/00/00') === 0 || $date === '0000') return $fallback;
    $ts = strtotime($date);
    if ($ts === false || $ts < 86400 || $ts > 4102444800) return $fallback;
    return $forOutput ? gmdate('Y-m-d\TH:i:s\Z', $ts) : gmdate('Y-m-d H:i:s', $ts);
}

function addUrlToSitemap(PDO $db, string $type, string $id, ?string $lastmod = null): void
{
    if (empty($id)) return;
    $pathType = match (strtolower($type)) {
        'artist' => 'artist', 'collection' => 'collection', 'track' => 'track',
        'playlist' => 'playlist', 'user' => 'u', default => null,
    };
    if ($pathType === null) return;
    $id = preg_replace('/[^a-zA-Z0-9_\-]/', '', (string)$id);
    if ($id === '') return;
    try {
        getStatement(
            "INSERT INTO sitemapUrls (urlPath, entityType, entityId, lastmod)
             VALUES (:url, :type, :id, :lastmod)
             ON DUPLICATE KEY UPDATE lastmod = GREATEST(lastmod, VALUES(lastmod)), hits = hits + 1"
        )->execute([
            ':url'     => SPA_BASE_PATH . '/' . $pathType . '/' . $id,
            ':type'    => $pathType,
            ':id'      => $id,
            ':lastmod' => normalizeSitemapDate($lastmod, false),
        ]);
    } catch (Throwable $e) { error_log("Sitemap add failed [$pathType:$id]: " . $e->getMessage()); }
}

function addUrlsFromResults(PDO $db, array $results): void
{
    if (empty($results)) return;
    $now  = gmdate('Y-m-d H:i:s');
    $rows = []; $seen = [];
    foreach ($results as $item) {
        if (!is_array($item)) continue;
        $wrapper = $item['wrapperType'] ?? null;
        $type = null; $id = null;
        if ($wrapper === 'artist' && !empty($item['artistId']))              { $type = 'artist';     $id = $item['artistId']; }
        elseif ($wrapper === 'collection' && !empty($item['collectionId']))  { $type = 'collection'; $id = $item['collectionId']; }
        elseif ($wrapper === 'track' && !empty($item['trackId']))            { $type = 'track';      $id = $item['trackId']; }
        else continue;
        $id = preg_replace('/[^a-zA-Z0-9_\-]/', '', (string)$id);
        if ($id === '') continue;
        $url = SPA_BASE_PATH . '/' . $type . '/' . $id;
        if (isset($seen[$url])) continue;
        $seen[$url] = true;
        $lastmod = !empty($item['releaseDate']) ? normalizeSitemapDate($item['releaseDate'], false) : $now;
        $rows[] = [$url, $type, $id, $lastmod];
    }
    if (empty($rows)) return;
    foreach (array_chunk($rows, 100) as $chunk) {
        $values = []; $params = [];
        foreach ($chunk as $i => $r) {
            $values[] = "(:u$i,:t$i,:i$i,:l$i)";
            $params[":u$i"] = $r[0]; $params[":t$i"] = $r[1];
            $params[":i$i"] = $r[2]; $params[":l$i"] = $r[3];
        }
        $sql = "INSERT INTO sitemapUrls (urlPath, entityType, entityId, lastmod) VALUES "
             . implode(',', $values)
             . " ON DUPLICATE KEY UPDATE lastmod = GREATEST(lastmod, VALUES(lastmod)), hits = hits + 1";
        try { $db->prepare($sql)->execute($params); }
        catch (Throwable $e) { error_log('Sitemap batch insert failed: ' . $e->getMessage()); }
    }
}

function generateSitemapXml(PDO $db): string
{
    $limit = SITEMAP_MAX_URLS;
    $stmt  = $db->query("SELECT urlPath, lastmod FROM sitemapUrls ORDER BY lastmod DESC LIMIT $limit");
    $rows  = $stmt->fetchAll(PDO::FETCH_ASSOC);
    $xml  = '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
    $xml .= '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' . "\n";
    $now = gmdate('Y-m-d\TH:i:s\Z');
    $xml .= "  <url>\n    <loc>" . htmlspecialchars(SITE_URL . SPA_BASE_PATH . '/', ENT_XML1) . "</loc>\n";
    $xml .= "    <lastmod>$now</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>1.0</priority>\n  </url>\n";
    foreach ($rows as $row) {
        $rawPath = (string)($row['urlPath'] ?? '');
        if ($rawPath === '') continue;
        $loc     = htmlspecialchars(SITE_URL . $rawPath, ENT_XML1);
        $lastmod = normalizeSitemapDate($row['lastmod'] ?? null, true);
        $priority = '0.7';
        if (strpos($rawPath, '/track/')      !== false) $priority = '0.8';
        elseif (strpos($rawPath, '/playlist/') !== false) $priority = '0.7';
        elseif (strpos($rawPath, '/artist/') !== false) $priority = '0.6';
        $xml .= "  <url>\n    <loc>$loc</loc>\n    <lastmod>$lastmod</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>$priority</priority>\n  </url>\n";
    }
    $xml .= '</urlset>';
    return $xml;
}

function writeSitemapFile(PDO $db): array
{
    $xml   = generateSitemapXml($db);
    $bytes = file_put_contents(SITEMAP_FILE_PATH, $xml, LOCK_EX);
    if ($bytes === false) return ['success' => false, 'error' => 'Cannot write sitemap file'];
    return ['success' => true, 'bytes' => $bytes, 'urls' => substr_count($xml, '<url>'), 'file' => SITEMAP_FILE_PATH];
}

function ensureIndexNowKeyFile(): bool
{
    if (!INDEXNOW_ENABLED) return false;
    if (INDEXNOW_KEY === '' || strpos(INDEXNOW_KEY, 'change_me') !== false) return false;
    $path = __DIR__ . '/' . INDEXNOW_KEY . '.txt';
    if (file_exists($path) && trim((string)file_get_contents($path)) === INDEXNOW_KEY) return true;
    return @file_put_contents($path, INDEXNOW_KEY, LOCK_EX) !== false;
}

function submitToGoogle(string $sitemapUrl): array
{
    if (!GOOGLE_PING_ENABLED) return ['success' => false, 'error' => 'Google ping disabled'];
    $pingUrl = GOOGLE_PING_URL . urlencode($sitemapUrl);
    $ch = curl_init($pingUrl);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15, CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_SSL_VERIFYPEER => false, CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_USERAGENT => 'Mozilla/5.0 (compatible; SitemapSubmitter/1.0)',
    ]);
    $resp = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err  = curl_error($ch);
    curl_close($ch);
    $ok = in_array($code, [200, 204], true);
    return ['success' => $ok, 'http_code' => $code, 'response' => $resp, 'error' => $err ?: null, 'ping_url' => $pingUrl];
}

function submitToIndexNow(array $urls): array
{
    if (!INDEXNOW_ENABLED) return ['success' => false, 'error' => 'IndexNow disabled'];
    if (empty($urls)) return ['success' => false, 'error' => 'No URLs to submit'];
    if (!ensureIndexNowKeyFile()) return ['success' => false, 'error' => 'Cannot write IndexNow key file'];
    $host = parse_url(SITE_URL, PHP_URL_HOST);
    if (!$host) return ['success' => false, 'error' => 'Invalid SITE_URL'];
    $keyLocation = rtrim(SITE_URL, '/') . '/' . INDEXNOW_KEY . '.txt';
    $batches     = array_chunk(array_values($urls), AUTO_SUBMIT_BATCH_SIZE);
    $results     = [];
    foreach ($batches as $idx => $batch) {
        $payload = json_encode([
            'host' => $host, 'key' => INDEXNOW_KEY,
            'keyLocation' => $keyLocation, 'urlList' => $batch,
        ], JSON_UNESCAPED_SLASHES);
        $ch = curl_init(INDEXNOW_ENDPOINT);
        curl_setopt_array($ch, [
            CURLOPT_POST => true, CURLOPT_POSTFIELDS => $payload,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => ['Content-Type: application/json; charset=utf-8'],
            CURLOPT_TIMEOUT => 25, CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_SSL_VERIFYPEER => false,
        ]);
        $resp = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err  = curl_error($ch);
        curl_close($ch);
        $results[] = [
            'batch' => $idx + 1, 'count' => count($batch),
            'http_code' => $code, 'success' => in_array($code, [200, 202], true),
            'response' => $resp, 'error' => $err ?: null,
        ];
        if ($code !== 200 && $code !== 202) error_log("IndexNow batch $idx failed: HTTP $code $err");
        if (count($batches) > 1) usleep(500000);
    }
    $allOk = !empty($results) && !in_array(false, array_column($results, 'success'), true);
    return ['success' => $allOk, 'batches' => $results, 'total_urls' => count($urls)];
}

function logSitemapSubmission(PDO $db, array $payload): void
{
    try {
        getStatement(
            "INSERT INTO sitemapSubmissions (submittedAt, googleCode, indexnowBatches, totalUrls, response)
             VALUES (NOW(), :gc, :ib, :tu, :r)"
        )->execute([
            ':gc' => $payload['google']['http_code'] ?? null,
            ':ib' => isset($payload['indexnow']['batches']) ? count($payload['indexnow']['batches']) : 0,
            ':tu' => $payload['indexnow']['total_urls'] ?? 0,
            ':r'  => json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE),
        ]);
    } catch (Throwable $e) { error_log('Failed to log sitemap submission: ' . $e->getMessage()); }
}

function autoSubmitSitemap(PDO $db): array
{
    $sitemapUrl = rtrim(SITE_URL, '/') . '/sitemap.xml';
    $result = ['timestamp' => date('c'), 'sitemap_url' => $sitemapUrl, 'google' => null, 'indexnow' => null];
    $result['google'] = submitToGoogle($sitemapUrl);
    $stmt = $db->query("SELECT urlPath FROM sitemapUrls ORDER BY lastmod DESC LIMIT " . (int)AUTO_SUBMIT_MAX_URLS);
    $urls = [rtrim(SITE_URL, '/') . '/'];
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) $urls[] = rtrim(SITE_URL, '/') . $row['urlPath'];
    $urls = array_values(array_unique($urls));
    $result['indexnow'] = !empty($urls) ? submitToIndexNow($urls) : ['success' => false, 'error' => 'No URLs'];
    logSitemapSubmission($db, $result);
    return $result;
}

/* ═══════════════ DB ═══════════════ */

function getDB(): PDO
{
    global $db, $dbConnectedAt;
    if ($db !== null) {
        if ((time() - $dbConnectedAt) < 30) return $db;
        try { $db->query("SELECT 1"); $dbConnectedAt = time(); return $db; }
        catch (PDOException $e) { error_log("Database connection lost, reconnecting..."); $db = null; }
    }
    $dsn = sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', DEST_HOST, DEST_PORT, DEST_NAME);
    $options = [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
        PDO::ATTR_PERSISTENT         => DB_PERSISTENT,
        PDO::ATTR_TIMEOUT            => DB_CONNECTION_TIMEOUT,
    ];
    $lastException = null;
    for ($attempt = 0; $attempt <= DB_MAX_RETRIES; $attempt++) {
        try {
            $db = new PDO($dsn, DEST_USER, DEST_PASS, $options);
            $db->exec("SET NAMES utf8mb4 COLLATE utf8mb4_general_ci");
            $db->exec("SET SESSION wait_timeout = " . DB_CONNECTION_TIMEOUT);
            $db->exec("SET SESSION interactive_timeout = " . DB_CONNECTION_TIMEOUT);
            initDatabase($db);
            $dbConnectedAt = time();
            error_log("DB connected (attempt " . ($attempt + 1) . ")");
            return $db;
        } catch (PDOException $e) {
            $lastException = $e;
            $errorCode = $e->getCode();
            $db = null;
            if (in_array($errorCode, [1226, 1040, 2002, 2003, 2006, 2013]) && $attempt < DB_MAX_RETRIES) {
                usleep(100000 + ($attempt * 200000) + random_int(0, 500000));
                continue;
            }
            throw $e;
        }
    }
    throw $lastException;
}

function getStatement(string $sql): PDOStatement
{
    global $statements;
    if (!isset($statements[$sql])) $statements[$sql] = getDB()->prepare($sql);
    return $statements[$sql];
}

function getSQLiteDB(): PDO
{
    global $sqliteDb;
    if ($sqliteDb !== null) {
        try { $sqliteDb->query("SELECT 1"); return $sqliteDb; }
        catch (PDOException $e) { $sqliteDb = null; }
    }
    if (!extension_loaded('pdo_sqlite')) throw new RuntimeException('pdo_sqlite extension is not enabled');
    $options = [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
        PDO::ATTR_TIMEOUT            => 5,
    ];
    try {
        $sqliteDb = new PDO('sqlite:' . SQLITE_DB_FILE, null, null, $options);
        $sqliteDb->exec("PRAGMA journal_mode = WAL");
        $sqliteDb->exec("PRAGMA synchronous = NORMAL");
        $sqliteDb->exec("PRAGMA temp_store = MEMORY");
        $sqliteDb->exec("
            CREATE TABLE IF NOT EXISTS downloadQueue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trackId TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                filePath TEXT,
                quality TEXT,
                addedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
                startedAt DATETIME,
                completedAt DATETIME,
                errorMessage TEXT,
                retryCount INTEGER DEFAULT 0,
                priority INTEGER DEFAULT 0,
                percent INTEGER DEFAULT 0
            )");
        $sqliteDb->exec("CREATE INDEX IF NOT EXISTS idx_download_status ON downloadQueue(status)");
        $sqliteDb->exec("CREATE INDEX IF NOT EXISTS idx_download_track ON downloadQueue(trackId)");
        return $sqliteDb;
    } catch (PDOException $e) {
        error_log("Failed to open SQLite database: " . $e->getMessage());
        throw $e;
    }
}

function getSQLiteStatement(string $sql): PDOStatement
{
    global $sqliteStatements;
    if (!isset($sqliteStatements[$sql])) $sqliteStatements[$sql] = getSQLiteDB()->prepare($sql);
    return $sqliteStatements[$sql];
}

/* ═══════════════ SCHEMA ═══════════════ */

function initDatabase(PDO $db): void
{
    static $initialized = false;
    if ($initialized) return;

    $marker = sys_get_temp_dir() . '/itunes_proxy_schema_' . md5(DEST_NAME . ':' . DEST_USER . ':' . SCHEMA_VERSION);
    if (file_exists($marker) && (time() - filemtime($marker)) < 3600) { $initialized = true; return; }

    /* ─── Legacy catalog ─── */
    try {
        if ($db->query("SHOW TABLES LIKE 'entityMirrors'")->fetch()) {
            if (!$db->query("SHOW COLUMNS FROM entityMirrors LIKE 'id'")->fetch()) {
                $db->exec("ALTER TABLE entityMirrors ADD COLUMN id INT AUTO_INCREMENT PRIMARY KEY FIRST");
                try { $db->exec("ALTER TABLE entityMirrors DROP PRIMARY KEY"); } catch (Exception $e) {}
                $db->exec("ALTER TABLE entityMirrors ADD UNIQUE KEY unique_mirror (entityType, entityId, urlType, quality, mirrorUrl(255))");
                try { $db->exec("ALTER TABLE entityMirrors ADD COLUMN source VARCHAR(50) DEFAULT 'custom'"); } catch (Exception $e) {}
            } else {
                try { $db->exec("ALTER TABLE entityMirrors ADD COLUMN source VARCHAR(50) DEFAULT 'custom'"); } catch (Exception $e) {}
            }
        } else {
            $db->exec("CREATE TABLE entityMirrors (
                id INT AUTO_INCREMENT PRIMARY KEY,
                entityType VARCHAR(50) NOT NULL,
                entityId VARCHAR(255) NOT NULL,
                urlType VARCHAR(50) NOT NULL,
                mirrorUrl TEXT NOT NULL,
                quality VARCHAR(10),
                platform VARCHAR(32) NOT NULL DEFAULT 'telegram',
                source VARCHAR(50) DEFAULT 'custom',
                updatedAt DATETIME,
                UNIQUE KEY unique_mirror (entityType, entityId, urlType, quality, platform, mirrorUrl(255)),
                KEY idx_mirrors_platform (platform)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");
        }
    } catch (Exception $e) {}

    /* ─── Platform column migration ─── */
    try {
        if ($db->query("SHOW TABLES LIKE 'entityMirrors'")->fetch()) {
            if (!$db->query("SHOW COLUMNS FROM entityMirrors LIKE 'platform'")->fetch()) {
                $db->exec("ALTER TABLE entityMirrors
                           ADD COLUMN platform VARCHAR(32) NOT NULL DEFAULT 'telegram' AFTER quality");
                try { $db->exec("ALTER TABLE entityMirrors DROP INDEX unique_mirror"); } catch (Exception $e) {}
                $db->exec("ALTER TABLE entityMirrors
                           ADD UNIQUE KEY unique_mirror (entityType, entityId, urlType, quality, platform, mirrorUrl(255))");
                try { $db->exec("CREATE INDEX idx_mirrors_platform ON entityMirrors(platform)"); } catch (Exception $e) {}
            }
        }
    } catch (Exception $e) { error_log("Platform migration failed: " . $e->getMessage()); }

    $db->exec("CREATE TABLE IF NOT EXISTS artists (artistId VARCHAR(255) PRIMARY KEY) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");
    $db->exec("CREATE TABLE IF NOT EXISTS collections (collectionId VARCHAR(255) PRIMARY KEY) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");
    $db->exec("CREATE TABLE IF NOT EXISTS tracks (
        trackId VARCHAR(255) PRIMARY KEY,
        isStreamable TINYINT(1) DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec('CREATE TABLE IF NOT EXISTS externalCache (
        id INT AUTO_INCREMENT PRIMARY KEY,
        service VARCHAR(50) NOT NULL,
        cacheKey VARCHAR(255) NOT NULL,
        response MEDIUMTEXT,
        expiresAt DATETIME NOT NULL,
        UNIQUE KEY (service, cacheKey)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci');
    try { $db->exec("ALTER TABLE externalCache MODIFY COLUMN response MEDIUMTEXT"); } catch (Exception $e) {}

    $db->exec("CREATE TABLE IF NOT EXISTS trackLyrics (
        trackId VARCHAR(255) PRIMARY KEY,
        lyrics LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL,
        type ENUM('synced','unsynced') DEFAULT 'unsynced',
        source VARCHAR(50) DEFAULT 'custom',
        updatedAt DATETIME,
        FOREIGN KEY (trackId) REFERENCES tracks(trackId) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    try {
        if ($db->query("SHOW COLUMNS FROM tracks LIKE 'lyrics'")->fetch()) {
            $db->exec("INSERT IGNORE INTO trackLyrics (trackId, lyrics, type, source, updatedAt)
                       SELECT trackId, lyrics, 'unsynced', 'custom', NOW() FROM tracks WHERE lyrics IS NOT NULL AND lyrics != ''");
            $db->exec("ALTER TABLE tracks DROP COLUMN lyrics");
        }
    } catch (Exception $e) {}

    foreach (['tracks', 'artists', 'collections'] as $table) {
        try {
            $rows = $db->query("SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                                FROM information_schema.COLUMNS
                                WHERE TABLE_SCHEMA = DATABASE()
                                  AND TABLE_NAME = " . $db->quote($table) . "
                                  AND DATA_TYPE IN ('char','varchar','text','mediumtext','longtext','tinytext')
                                  AND COLLATION_NAME IS NOT NULL
                                  AND COLLATION_NAME <> 'utf8mb4_general_ci'")->fetchAll();
            foreach ($rows as $row) {
                $name = $row['COLUMN_NAME'];
                if (!preg_match('/^[a-zA-Z0-9_]+$/', $name)) continue;
                $type = $row['COLUMN_TYPE'];
                $null = $row['IS_NULLABLE'] === 'NO' ? 'NOT NULL' : 'NULL';
                $db->exec("ALTER TABLE `$table` MODIFY COLUMN `$name` $type CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci $null");
            }
        } catch (Exception $e) { error_log("Collation migration failed for $table: " . $e->getMessage()); }
    }

    $db->exec("CREATE TABLE IF NOT EXISTS requestCache (
        id INT AUTO_INCREMENT PRIMARY KEY,
        endpoint VARCHAR(255) NOT NULL,
        params VARCHAR(2048) NOT NULL,
        resultIds TEXT NOT NULL,
        expiresAt DATETIME NOT NULL,
        lastAccessed DATETIME,
        accessCount INT DEFAULT 0,
        UNIQUE KEY (endpoint, params)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS rateLimitLog (
        id INT AUTO_INCREMENT PRIMARY KEY,
        apiName VARCHAR(100) NOT NULL,
        lastRequestTime DATETIME NOT NULL,
        requestCount INT DEFAULT 1,
        successfulRequests INT DEFAULT 0,
        failedRequests INT DEFAULT 0,
        blockedUntil DATETIME,
        UNIQUE KEY (apiName)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS requestHistory (
        id INT AUTO_INCREMENT PRIMARY KEY,
        requestTime DATETIME NOT NULL,
        endpoint TEXT NOT NULL,
        statusCode INT,
        responseTime INT,
        userAgent TEXT,
        success INT DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS proxyStatus (
        id INT AUTO_INCREMENT PRIMARY KEY,
        proxyUrl VARCHAR(255) NOT NULL UNIQUE,
        lastUsed DATETIME,
        successCount INT DEFAULT 0,
        failCount INT DEFAULT 0,
        isBlocked INT DEFAULT 0,
        blockedUntil DATETIME,
        responseTimeAvg DECIMAL(10,2) DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS sitemapUrls (
        id INT AUTO_INCREMENT PRIMARY KEY,
        urlPath VARCHAR(500) NOT NULL,
        entityType VARCHAR(20) NOT NULL,
        entityId VARCHAR(255) NOT NULL,
        lastmod DATETIME NOT NULL,
        hits INT DEFAULT 1,
        UNIQUE KEY unique_url (urlPath(255)),
        INDEX idx_entity (entityType, entityId),
        INDEX idx_lastmod (lastmod)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS sitemapSubmissions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        submittedAt DATETIME NOT NULL,
        googleCode INT,
        indexnowBatches INT DEFAULT 0,
        totalUrls INT DEFAULT 0,
        response MEDIUMTEXT,
        INDEX idx_submittedAt (submittedAt)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS viewSessions (
        sessionKey VARCHAR(64) PRIMARY KEY,
        startedAt  DATETIME NOT NULL,
        lastSeenAt DATETIME NOT NULL,
        INDEX idx_last_seen (lastSeenAt)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS trackViews (
        trackId    VARCHAR(255) NOT NULL,
        sessionKey VARCHAR(64)  NOT NULL,
        viewedAt   DATETIME NOT NULL,
        PRIMARY KEY (trackId, sessionKey),
        INDEX idx_viewed_at (viewedAt),
        INDEX idx_session (sessionKey)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    /* ─── Users / Auth ─── */
    $db->exec("CREATE TABLE IF NOT EXISTS users (
        userId INT AUTO_INCREMENT PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        username VARCHAR(64) UNIQUE NOT NULL,
        passwordHash VARCHAR(255) NOT NULL,
        displayName VARCHAR(128),
        avatarUrl VARCHAR(512),
        bio TEXT,
        country VARCHAR(8),
        isVerified TINYINT(1) DEFAULT 0,
        isPrivate TINYINT(1) DEFAULT 0,
        role VARCHAR(32) DEFAULT 'user',
        followerCount INT DEFAULT 0,
        followingCount INT DEFAULT 0,
        playlistCount INT DEFAULT 0,
        likeCount INT DEFAULT 0,
        lastLoginAt DATETIME,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_username (username),
        INDEX idx_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS userSessions (
        sessionId VARCHAR(64) PRIMARY KEY,
        userId INT NOT NULL,
        ip VARCHAR(64),
        userAgent TEXT,
        expiresAt DATETIME NOT NULL,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user (userId),
        INDEX idx_expires (expiresAt)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    /* ─── API Apps & Tokens ─── */
    $db->exec("CREATE TABLE IF NOT EXISTS apiApps (
        appId VARCHAR(64) PRIMARY KEY,
        userId INT NOT NULL,
        name VARCHAR(128) NOT NULL,
        description TEXT,
        clientSecret VARCHAR(128) NOT NULL,
        redirectUris TEXT,
        websiteUrl VARCHAR(512),
        settings JSON,
        isActive TINYINT(1) DEFAULT 1,
        requestCount BIGINT DEFAULT 0,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_user (userId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS apiTokens (
        tokenId VARCHAR(64) PRIMARY KEY,
        tokenHash VARCHAR(128) UNIQUE NOT NULL,
        tokenPrefix VARCHAR(16),
        appId VARCHAR(64) NULL,
        userId INT NULL,
        name VARCHAR(128),
        scopes TEXT,
        isActive TINYINT(1) DEFAULT 1,
        expiresAt DATETIME NULL,
        lastUsedAt DATETIME,
        requestCount BIGINT DEFAULT 0,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user (userId),
        INDEX idx_app (appId),
        INDEX idx_hash (tokenHash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS apiRequestLog (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        appId VARCHAR(64),
        userId INT,
        tokenId VARCHAR(64),
        endpoint VARCHAR(255),
        method VARCHAR(10),
        statusCode INT,
        responseTime INT,
        ip VARCHAR(64),
        userAgent TEXT,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_app (appId),
        INDEX idx_user (userId),
        INDEX idx_created (createdAt)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS webhooks (
        webhookId VARCHAR(64) PRIMARY KEY,
        appId VARCHAR(64) NOT NULL,
        url VARCHAR(512) NOT NULL,
        events TEXT NOT NULL,
        secret VARCHAR(128),
        isActive TINYINT(1) DEFAULT 1,
        lastTriggeredAt DATETIME,
        failCount INT DEFAULT 0,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_app (appId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    /* ─── Social ─── */
    $db->exec("CREATE TABLE IF NOT EXISTS likes (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        userId INT NOT NULL,
        entityType VARCHAR(50) NOT NULL,
        entityId VARCHAR(255) NOT NULL,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_like (userId, entityType, entityId),
        INDEX idx_entity (entityType, entityId),
        INDEX idx_user (userId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS comments (
        commentId BIGINT AUTO_INCREMENT PRIMARY KEY,
        userId INT NOT NULL,
        entityType VARCHAR(50) NOT NULL,
        entityId VARCHAR(255) NOT NULL,
        parentId BIGINT DEFAULT NULL,
        content TEXT NOT NULL,
        likeCount INT DEFAULT 0,
        replyCount INT DEFAULT 0,
        isDeleted TINYINT(1) DEFAULT 0,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_entity (entityType, entityId),
        INDEX idx_parent (parentId),
        INDEX idx_user (userId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS commentLikes (
        commentId BIGINT NOT NULL,
        userId INT NOT NULL,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (commentId, userId),
        INDEX idx_user (userId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS follows (
        followerId INT NOT NULL,
        followingId INT NOT NULL,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (followerId, followingId),
        INDEX idx_following (followingId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS playlists (
        playlistId VARCHAR(64) PRIMARY KEY,
        userId INT NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        coverUrl VARCHAR(512),
        isPublic TINYINT(1) DEFAULT 1,
        isCollaborative TINYINT(1) DEFAULT 0,
        trackCount INT DEFAULT 0,
        likeCount INT DEFAULT 0,
        playCount INT DEFAULT 0,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_user (userId),
        INDEX idx_public (isPublic)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS playlistTracks (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        playlistId VARCHAR(64) NOT NULL,
        trackId VARCHAR(255) NOT NULL,
        position INT NOT NULL,
        addedBy INT,
        addedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_track (playlistId, trackId),
        INDEX idx_playlist (playlistId),
        INDEX idx_pos (playlistId, position)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS playlistLikes (
        playlistId VARCHAR(64) NOT NULL,
        userId INT NOT NULL,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (playlistId, userId),
        INDEX idx_user (userId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS userLibrary (
        userId INT NOT NULL,
        entityType VARCHAR(50) NOT NULL,
        entityId VARCHAR(255) NOT NULL,
        addedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (userId, entityType, entityId),
        INDEX idx_user (userId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS playHistory (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        userId INT NULL,
        trackId VARCHAR(255) NOT NULL,
        duration INT DEFAULT 0,
        playedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user (userId, playedAt),
        INDEX idx_track (trackId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS userFollowedArtists (
        userId INT NOT NULL,
        artistId VARCHAR(255) NOT NULL,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (userId, artistId),
        INDEX idx_artist (artistId)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS notifications (
        notificationId BIGINT AUTO_INCREMENT PRIMARY KEY,
        userId INT NOT NULL,
        actorId INT NULL,
        type VARCHAR(50) NOT NULL,
        entityType VARCHAR(50),
        entityId VARCHAR(255),
        message TEXT,
        isRead TINYINT(1) DEFAULT 0,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user (userId, isRead),
        INDEX idx_created (createdAt)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    $db->exec("CREATE TABLE IF NOT EXISTS activityFeed (
        activityId BIGINT AUTO_INCREMENT PRIMARY KEY,
        userId INT NOT NULL,
        type VARCHAR(50) NOT NULL,
        entityType VARCHAR(50),
        entityId VARCHAR(255),
        metadata JSON,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user (userId),
        INDEX idx_created (createdAt)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci");

    /* ─── Indexes (best effort) ─── */
    foreach ([
        "CREATE INDEX idx_mirrors_lookup ON entityMirrors(entityType, entityId)",
        "CREATE INDEX idx_mirrors_entity_ty ON entityMirrors(entityType, entityId, urlType)",
        "CREATE INDEX idx_mirrors_platform ON entityMirrors(platform)",
        "CREATE INDEX idx_cache_lookup ON requestCache(endpoint, params(255))",
        "CREATE INDEX idx_request_history ON requestHistory(requestTime)",
        "CREATE INDEX idx_lyrics_track ON trackLyrics(trackId)",
    ] as $sql) { try { $db->exec($sql); } catch (Exception $e) {} }

    try {
        if (!$db->query("SHOW COLUMNS FROM tracks LIKE 'isStreamable'")->fetch()) {
            $db->exec("ALTER TABLE tracks ADD COLUMN isStreamable TINYINT(1) DEFAULT 0");
        }
    } catch (Exception $e) {}

    try {
        if (!$db->query("SHOW COLUMNS FROM tracks LIKE 'views'")->fetch()) {
            $db->exec("ALTER TABLE tracks ADD COLUMN views BIGINT UNSIGNED NOT NULL DEFAULT 0");
            $db->exec("CREATE INDEX idx_track_views ON tracks(views)");
        }
    } catch (Exception $e) {}

    try {
        if ($db->query("SHOW COLUMNS FROM tracks LIKE 'artistId'")->fetch()) {
            try { $db->exec("CREATE INDEX idx_tracks_artist ON tracks(artistId)"); } catch (Exception $e) {}
            try { $db->exec("CREATE INDEX idx_tracks_artist_collection ON tracks(artistId, collectionId, trackNumber)"); } catch (Exception $e) {}
        }
    } catch (Exception $e) {}

    @touch($marker);
    $initialized = true;
}

/* ═══════════════ COLUMNS ═══════════════ */

function ensureColumns(PDO $db, string $table, array $data): void
{
    static $existingColumns = [];
    static $allowedTables = ['artists' => 1, 'collections' => 1, 'tracks' => 1];
    if (!isset($allowedTables[$table])) return;
    if (!isset($existingColumns[$table])) {
        $cols = $db->query("SHOW COLUMNS FROM $table")->fetchAll(PDO::FETCH_COLUMN, 0);
        $existingColumns[$table] = array_flip($cols);
    }
    foreach ($data as $col => $_) {
        if (!isset($existingColumns[$table][$col]) && preg_match('/^[a-zA-Z0-9_]+$/', $col)) {
            $db->exec("ALTER TABLE $table ADD COLUMN `$col` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL");
            $existingColumns[$table][$col] = true;
        }
    }
}

/* ═══════════════ SAVE ENTITIES ═══════════════ */

function saveEntitiesFromApi(PDO $db, string $table, array $entities): void
{
    if (empty($entities)) return;
    if (isset($entities['wrapperType']) || isset($entities['artistId']) || isset($entities['collectionId']) || isset($entities['trackId'])) {
        $entities = [$entities];
    }
    $expectedWrapper = match ($table) {
        'artists' => 'artist', 'collections' => 'collection', 'tracks' => 'track', default => null,
    };
    $pkCol = match ($table) {
        'artists' => 'artistId', 'collections' => 'collectionId', 'tracks' => 'trackId', default => null,
    };
    if ($expectedWrapper === null || $pkCol === null) return;

    $db->beginTransaction();
    try {
        foreach ($entities as $entity) {
            if (!is_array($entity)) continue;
            if (isset($entity['wrapperType']) && $entity['wrapperType'] !== $expectedWrapper) continue;
            if (!isset($entity[$pkCol])) continue;
            unset($entity['lyrics']);
            ensureColumns($db, $table, $entity);
            $columns = array_keys($entity);
            $colList = '`' . implode('`,`', $columns) . '`';
            $holders = ':' . implode(',:', $columns);
            $updateParts = [];
            foreach ($columns as $col) if ($col !== $pkCol) $updateParts[] = "`$col` = VALUES(`$col`)";
            $updateClause = empty($updateParts) ? '' : ' ON DUPLICATE KEY UPDATE ' . implode(',', $updateParts);
            $sql = "INSERT INTO $table ($colList) VALUES ($holders)$updateClause";
            $stmt = getStatement($sql);
            $params = [];
            foreach ($entity as $col => $val) $params[":$col"] = $val;
            $stmt->execute($params);
        }
        $db->commit();
    } catch (Throwable $e) {
        if ($db->inTransaction()) $db->rollBack();
        throw $e;
    }
}

/* ═══════════════ MIRRORS / BULK LOAD ═══════════════ */

function getAudioUrlTypeWithQuality(string $urlType, ?string $quality = null): string
{
    if ($urlType !== 'audioUrl' || !$quality) return $urlType;
    if (!in_array($quality, SUPPORTED_AUDIO_QUALITIES, true)) $quality = DEFAULT_AUDIO_QUALITY;
    return $urlType . '_' . $quality;
}

function extractQualityFromUrlType(string $urlType): ?string
{
    if (strpos($urlType, 'audioUrl_') === 0) {
        $qual = substr($urlType, 9);
        return in_array($qual, SUPPORTED_AUDIO_QUALITIES, true) ? $qual : null;
    }
    return null;
}

function getExternalCache(PDO $db, string $service, string $key): ?array
{
    $stmt = getStatement("SELECT response, expiresAt FROM externalCache
                          WHERE service = :s AND cacheKey = :k AND expiresAt > NOW() LIMIT 1");
    $stmt->execute([':s' => $service, ':k' => $key]);
    $row = $stmt->fetch();
    if (!$row) return null;
    return ['response' => json_decode($row['response'], true), 'expiresAt' => $row['expiresAt']];
}

function setExternalCache(PDO $db, string $service, string $key, $response, int $ttl = 86400): void
{
    $json = is_null($response) ? null : json_encode($response, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($json === false) throw new RuntimeException('setExternalCache: json_encode failed');
    getStatement("REPLACE INTO externalCache (service, cacheKey, response, expiresAt)
                  VALUES (:s, :k, :r, :e)")
        ->execute([':s' => $service, ':k' => $key, ':r' => $json, ':e' => date('Y-m-d H:i:s', time() + $ttl)]);
}

function getBestAvailableQuality(array $mirrors, ?string $platform = null): ?array
{
    $platform = normalizePlatform($platform);
    foreach (SUPPORTED_AUDIO_QUALITIES as $qual) {
        $key = 'audioUrl_' . $qual;
        if (!empty($mirrors[$key])) {
            foreach ($mirrors[$key] as $item) {
                if ($platform === null || ($item['platform'] ?? DEFAULT_PLATFORM) === $platform) {
                    return [
                        'url'      => $item['url'],
                        'quality'  => $qual,
                        'platform' => $item['platform'] ?? DEFAULT_PLATFORM,
                    ];
                }
            }
        }
    }
    if (!empty($mirrors['audioUrl'])) {
        foreach ($mirrors['audioUrl'] as $item) {
            if ($platform === null || ($item['platform'] ?? DEFAULT_PLATFORM) === $platform) {
                return [
                    'url'      => $item['url'],
                    'quality'  => $item['quality'] ?? DEFAULT_AUDIO_QUALITY,
                    'platform' => $item['platform'] ?? DEFAULT_PLATFORM,
                ];
            }
        }
    }
    return null;
}

function fetchEntitiesByIdsMap(array $idsByType): array
{
    $db = getDB();
    $tables = ['artist' => ['artists', 'artistId'], 'collection' => ['collections', 'collectionId'], 'track' => ['tracks', 'trackId']];
    $out = [];
    foreach ($idsByType as $type => $ids) {
        if (!isset($tables[$type]) || empty($ids)) continue;
        [$table, $pk] = $tables[$type];
        $ids = array_values(array_unique(array_filter($ids, fn($v) => $v !== null && $v !== '')));
        if (empty($ids)) continue;
        foreach (array_chunk($ids, 500) as $chunk) {
            $ph = implode(',', array_fill(0, count($chunk), '?'));
            $stmt = $db->prepare("SELECT * FROM `$table` WHERE `$pk` IN ($ph)");
            $stmt->execute($chunk);
            while ($row = $stmt->fetch()) $out[$type . ':' . $row[$pk]] = $row;
        }
    }
    return $out;
}

/**
 * لود mirrors با فیلتر پلتفرم.
 *  - $platformFilter === null  → همه پلتفرمها
 *  - $platformFilter === 'x'   → فقط همان پلتفرم
 *  - برای «پیشفرض telegram»، از resolveReadPlatformFilter استفاده کن.
 */
function loadMirrorsBatch(array $pairsByType, ?string $platformFilter = null): array
{
    $db = getDB();
    $out = [];
    if ($platformFilter !== null) $platformFilter = normalizePlatform($platformFilter);

    foreach ($pairsByType as $type => $ids) {
        $ids = array_values(array_unique(array_filter($ids, fn($v) => $v !== null && $v !== '')));
        if (empty($ids)) continue;

        foreach (array_chunk($ids, 500) as $chunk) {
            $ph  = implode(',', array_fill(0, count($chunk), '?'));
            $sql = "SELECT id, entityType, entityId, urlType, mirrorUrl, quality, platform, source
                    FROM entityMirrors
                    WHERE entityType = ? AND entityId IN ($ph)";
            $params = array_merge([$type], $chunk);

            if ($platformFilter !== null) {
                $sql .= " AND platform = ?";
                $params[] = $platformFilter;
            }

            $stmt = $db->prepare($sql);
            $stmt->execute($params);
            while ($row = $stmt->fetch()) {
                $key = $row['entityType'] . ':' . $row['entityId'];
                $out[$key][$row['urlType']][] = [
                    'id'       => $row['id'],
                    'url'      => $row['mirrorUrl'],
                    'quality'  => $row['quality'],
                    'platform' => $row['platform'] ?: DEFAULT_PLATFORM,
                    'source'   => $row['source'] ?? 'custom',
                ];
            }
        }
    }
    return $out;
}

function loadLyricsBatch(array $trackIds): array
{
    $trackIds = array_values(array_unique(array_filter($trackIds, fn($v) => $v !== null && $v !== '')));
    if (empty($trackIds)) return [];
    $db = getDB();
    $out = [];
    foreach (array_chunk($trackIds, 500) as $chunk) {
        $ph = implode(',', array_fill(0, count($chunk), '?'));
        $stmt = $db->prepare("SELECT trackId, lyrics, type, source FROM trackLyrics WHERE trackId IN ($ph)");
        $stmt->execute($chunk);
        while ($row = $stmt->fetch()) $out[$row['trackId']] = $row;
    }
    return $out;
}

function buildAttachments(array &$entity, string $type, string $id, array $mirrors, ?array $lyricsRow, ?string $requestedQuality = null): void
{
    $artworkUrls = [];
    foreach ($entity as $key => $value) {
        if (strpos($key, 'artworkUrl') === 0 && $key !== 'artworkUrl' && $value !== null) {
            $size = substr($key, strlen('artworkUrl'));
            if (is_numeric($size)) $artworkUrls[] = ['size' => $size . 'x' . $size, 'url' => $value, 'source' => 'itunes', 'platform' => 'itunes'];
        }
    }
    if (!empty($entity['artworkUrl'])) {
        $found = false;
        foreach ($artworkUrls as $a) if ($a['url'] === $entity['artworkUrl']) { $found = true; break; }
        if (!$found) $artworkUrls[] = ['size' => 'original', 'url' => $entity['artworkUrl'], 'source' => 'itunes', 'platform' => 'itunes'];
    }
    $attachments = [];
    $artworkFromMirrors = array_map(
        fn($m) => ['size' => 'mirror', 'url' => $m['url'], 'source' => $m['source'], 'platform' => $m['platform'] ?? DEFAULT_PLATFORM],
        $mirrors['artworkUrl'] ?? []
    );
    $attachments['artworkUrls'] = array_merge($artworkUrls, $artworkFromMirrors);
    if ($type === 'artist') {
        $attachments['bannerUrls']  = array_map(
            fn($m) => ['url' => $m['url'], 'source' => $m['source'], 'platform' => $m['platform'] ?? DEFAULT_PLATFORM],
            $mirrors['bannerUrl'] ?? []
        );
        $attachments['previewUrls'] = null;
        $attachments['audioUrls']   = null;
        $attachments['lyrics']      = null;
    } elseif ($type === 'collection') {
        $attachments['previewUrls'] = null;
        $attachments['audioUrls']   = null;
        $attachments['lyrics']      = null;
    } else {
        $previewUrls = [];
        if (!empty($entity['previewUrl'])) $previewUrls[] = ['url' => $entity['previewUrl'], 'source' => 'itunes', 'platform' => 'itunes'];
        foreach ($mirrors['previewUrl'] ?? [] as $m) $previewUrls[] = ['url' => $m['url'], 'source' => $m['source'], 'platform' => $m['platform'] ?? DEFAULT_PLATFORM];
        $attachments['previewUrls'] = $previewUrls;
        $forceQuality = null;
        if (!empty($entity['trackTimeMillis']) && (int)$entity['trackTimeMillis'] > LONG_TRACK_THRESHOLD_MS) {
            $forceQuality = LONG_TRACK_ONLY_QUALITY;
        }
        $audioUrls = [];
        foreach ($mirrors as $urlType => $items) {
            if (strpos($urlType, 'audioUrl') !== 0) continue;
            foreach ($items as $item) {
                $quality = $item['quality'] ?? null;
                if (!$quality && $urlType !== 'audioUrl') $quality = extractQualityFromUrlType($urlType);
                if ($forceQuality !== null && $quality !== $forceQuality) continue;
                $audioUrls[] = [
                    'quality'  => $quality ?: 'unknown',
                    'url'      => $item['url'],
                    'source'   => $item['source'],
                    'platform' => $item['platform'] ?? DEFAULT_PLATFORM,
                ];
            }
        }
        $attachments['audioUrls'] = $audioUrls;
        if ($lyricsRow && !empty($lyricsRow['lyrics'])) {
            $attachments['lyrics'] = [
                'type'   => $lyricsRow['type'],
                'text'   => json_decode($lyricsRow['lyrics'], true),
                'source' => $lyricsRow['source'] ?? 'custom',
            ];
        } else { $attachments['lyrics'] = null; }
    }
    $entity['attachments'] = $attachments;
    unset($entity['artworkUrl'], $entity['previewUrl'], $entity['audioUrl']);
    foreach (array_keys($entity) as $key) {
        if (strpos($key, 'artworkUrl') === 0 || strpos($key, 'previewUrl') === 0) unset($entity[$key]);
    }
    if (isset($entity['isStreamable'])) $entity['isStreamable'] = (int)$entity['isStreamable'];
}

/**
 * attach با فیلتر پلتفرم. اگر $platform === null باشد،
 * طبق خواستهٔ کاربر فقط DEFAULT_PLATFORM (telegram) در نظر گرفته میشود.
 * برای گرفتن همه، $platform = 'all' یا '*' بده.
 */
function attachAttachments(array &$entity, string $type, string $id, ?string $requestedQuality = null, ?string $platform = null): void
{
    $filter = resolveReadPlatformFilter($platform);
    $mirrors = loadMirrorsBatch([$type => [$id]], $filter);
    $lyrics  = $type === 'track' ? loadLyricsBatch([$id]) : [];
    buildAttachments($entity, $type, $id, $mirrors[$type . ':' . $id] ?? [], $lyrics[$id] ?? null, $requestedQuality);
}

function attachAttachmentsBatch(array &$entities, ?string $requestedQuality = null, ?string $platform = null): void
{
    if (empty($entities)) return;
    $filter = resolveReadPlatformFilter($platform);
    $pairsByType = ['artist' => [], 'collection' => [], 'track' => []];
    $trackIds = [];
    foreach ($entities as $e) {
        $w = $e['wrapperType'] ?? null;
        if ($w === 'artist' && !empty($e['artistId'])) $pairsByType['artist'][] = $e['artistId'];
        elseif ($w === 'collection' && !empty($e['collectionId'])) $pairsByType['collection'][] = $e['collectionId'];
        elseif ($w === 'track' && !empty($e['trackId'])) {
            $pairsByType['track'][] = $e['trackId'];
            $trackIds[] = $e['trackId'];
        }
    }
    $mirrors = loadMirrorsBatch($pairsByType, $filter);
    $lyrics  = loadLyricsBatch($trackIds);
    foreach ($entities as &$entity) {
        $w = $entity['wrapperType'] ?? null;
        $type = null; $id = null;
        if ($w === 'artist' && !empty($entity['artistId'])) { $type = 'artist'; $id = $entity['artistId']; }
        elseif ($w === 'collection' && !empty($entity['collectionId'])) { $type = 'collection'; $id = $entity['collectionId']; }
        elseif ($w === 'track' && !empty($entity['trackId'])) { $type = 'track'; $id = $entity['trackId']; }
        if (!$type) continue;
        $key = $type . ':' . $id;
        buildAttachments($entity, $type, $id, $mirrors[$key] ?? [], $lyrics[$id] ?? null, $requestedQuality);
    }
    unset($entity);
}

function updateStreamableStatus(PDO $db, string $trackId): void
{
    $stmt = getStatement("SELECT 1 FROM entityMirrors WHERE entityType='track' AND entityId=:id AND urlType LIKE 'audioUrl%' LIMIT 1");
    $stmt->execute([':id' => $trackId]);
    $hasAudio = (bool)$stmt->fetch();
    getStatement("UPDATE tracks SET isStreamable = :s WHERE trackId = :id")->execute([':s' => $hasAudio ? 1 : 0, ':id' => $trackId]);
}

/* ═══════════════ VIEW SESSIONS ═══════════════ */

function getViewSessionKey(array $params = []): string
{
    $explicit = $_SERVER['HTTP_X_SESSION_ID'] ?? $_SERVER['HTTP_X_VISITOR_ID'] ?? null;
    if (!$explicit) {
        $explicit = $params['sessionId'] ?? $params['session_id'] ?? $params['visitorId']
                 ?? $params['visitor_id'] ?? $params['deviceId'] ?? $params['device_id'] ?? null;
    }
    if (is_string($explicit) && $explicit !== '') return hash('sha256', 'sid:' . $explicit);
    $ip = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
    if (strpos($ip, ',') !== false) $ip = trim(explode(',', $ip)[0]);
    $ua = $_SERVER['HTTP_USER_AGENT'] ?? '';
    return hash('sha256', 'fp:' . $ip . '|' . $ua);
}

function incrementTrackViews(PDO $db, array $trackIds, ?string $sessionKey = null): void
{
    $ids = [];
    foreach ($trackIds as $id) { $id = trim((string)$id); if ($id !== '') $ids[$id] = true; }
    $ids = array_keys($ids);
    if (empty($ids)) return;
    $sessionKey = $sessionKey ?: getViewSessionKey();
    try {
        getStatement("INSERT INTO viewSessions (sessionKey, startedAt, lastSeenAt) VALUES (:k, NOW(), NOW())
            ON DUPLICATE KEY UPDATE lastSeenAt = NOW()")->execute([':k' => $sessionKey]);
        $stmt = getStatement("SELECT startedAt FROM viewSessions WHERE sessionKey = :k");
        $stmt->execute([':k' => $sessionKey]);
        $startedAt = (string)$stmt->fetchColumn();
        if ($startedAt !== '' && strtotime($startedAt) < time() - VIEW_SESSION_TTL) {
            getStatement("DELETE FROM trackViews WHERE sessionKey = :k")->execute([':k' => $sessionKey]);
            getStatement("UPDATE viewSessions SET startedAt = NOW(), lastSeenAt = NOW() WHERE sessionKey = :k")->execute([':k' => $sessionKey]);
        }
        $insert = getStatement("INSERT IGNORE INTO trackViews (trackId, sessionKey, viewedAt) VALUES (:tid, :k, NOW())");
        $newIds = [];
        foreach ($ids as $id) {
            $insert->execute([':tid' => $id, ':k' => $sessionKey]);
            if ($insert->rowCount() > 0) $newIds[] = $id;
        }
        if (empty($newIds)) return;
        $ph  = implode(',', array_fill(0, count($newIds), '?'));
        $upd = $db->prepare("UPDATE tracks SET views = views + 1 WHERE trackId IN ($ph)");
        $upd->execute($newIds);
    } catch (Throwable $e) { error_log('incrementTrackViews failed: ' . $e->getMessage()); }
}

/* ═══════════════ MIRROR CRUD ═══════════════ */

function addMirrorUrl(PDO $db, string $type, string $id, string $urlType, string $mirrorUrl,
                     ?string $quality = null, string $source = 'custom', ?string $platform = null): array
{
    if (!in_array($urlType, ['artworkUrl', 'previewUrl', 'audioUrl', 'bannerUrl'], true)) return ['success' => false, 'error' => 'Invalid urlType'];

    $isSchemeUrl = (bool)preg_match('#^(tg|bale|eitaa|rubika)://#i', $mirrorUrl);
    if (!filter_var($mirrorUrl, FILTER_VALIDATE_URL) && !$isSchemeUrl) {
        return ['success' => false, 'error' => 'Invalid URL'];
    }

    $platform = detectPlatformFromUrl($mirrorUrl, $platform);

    $table = match ($type) { 'artist' => 'artists', 'collection' => 'collections', 'track' => 'tracks', default => null };
    if ($table) {
        $pk = $type . 'Id';
        $db->prepare("INSERT IGNORE INTO $table ($pk) VALUES (:id)")->execute([':id' => $id]);
    }
    $actualUrlType = getAudioUrlTypeWithQuality($urlType, $quality);
    $qualityVal    = ($urlType === 'audioUrl') ? $quality : null;

    $stmt = getStatement("INSERT IGNORE INTO entityMirrors
                          (entityType, entityId, urlType, mirrorUrl, quality, platform, source, updatedAt)
                          VALUES (:t, :id, :ut, :url, :q, :pf, :src, NOW())");
    $stmt->execute([
        ':t' => $type, ':id' => $id, ':ut' => $actualUrlType,
        ':url' => $mirrorUrl, ':q' => $qualityVal,
        ':pf' => $platform, ':src' => $source,
    ]);
    if ($stmt->rowCount()) {
        if ($type === 'track') updateStreamableStatus($db, $id);
        return ['success' => true, 'id' => $db->lastInsertId(), 'platform' => $platform, 'message' => 'Mirror added'];
    }
    return ['success' => false, 'error' => 'Duplicate mirror already exists for this platform'];
}

function addMirrorUrlsBatch(PDO $db, array $attachments): array
{
    $results = [];
    foreach ($attachments as $item) {
        if (!isset($item['entityType'], $item['entityId'], $item['urlType'], $item['mirrorUrl'])) {
            $results[] = ['success' => false, 'error' => 'Missing required fields', 'item' => $item];
            continue;
        }
        $res = addMirrorUrl(
            $db,
            $item['entityType'], $item['entityId'], $item['urlType'], $item['mirrorUrl'],
            $item['quality']  ?? null,
            $item['source']   ?? 'custom',
            $item['platform'] ?? null
        );
        $results[] = array_merge($res, ['entity' => $item['entityId']]);
    }
    return ['success' => true, 'results' => $results];
}

function getMirrorUrls(PDO $db, string $type, string $id,
                      ?string $urlType = null, ?string $quality = null,
                      ?string $platform = null): array
{
    $filter = resolveReadPlatformFilter($platform);

    $sql = "SELECT id, urlType, mirrorUrl, quality, platform, source
            FROM entityMirrors WHERE entityType = :t AND entityId = :id";
    $params = [':t' => $type, ':id' => $id];
    if ($filter !== null) { $sql .= " AND platform = :pf"; $params[':pf'] = $filter; }

    $stmt = getStatement($sql);
    $stmt->execute($params);

    $attachments = ['artworkUrls' => []];
    if ($type === 'artist') {
        $attachments['bannerUrls'] = []; $attachments['previewUrls'] = null;
        $attachments['audioUrls'] = null; $attachments['lyrics'] = null;
    } elseif ($type === 'track') {
        $attachments['previewUrls'] = []; $attachments['audioUrls'] = []; $attachments['lyrics'] = null;
    } else {
        $attachments['previewUrls'] = null; $attachments['audioUrls'] = null; $attachments['lyrics'] = null;
    }

    while ($row = $stmt->fetch()) {
        $rowType = $row['urlType'];
        if ($urlType && $quality && $rowType !== getAudioUrlTypeWithQuality($urlType, $quality)) continue;
        $itemPlatform = $row['platform'] ?: DEFAULT_PLATFORM;
        $item = ['id' => $row['id'], 'url' => $row['mirrorUrl'], 'source' => $row['source'] ?? 'custom', 'platform' => $itemPlatform];
        if ($row['quality']) $item['quality'] = $row['quality'];

        if (strpos($rowType, 'audioUrl') === 0 && $type === 'track') {
            $qual = $row['quality'] ?? null;
            if (!$qual && $rowType !== 'audioUrl') $qual = extractQualityFromUrlType($rowType);
            $item['quality'] = $qual ?: 'unknown';
            $attachments['audioUrls'][] = $item;
        } elseif ($rowType === 'artworkUrl') {
            $attachments['artworkUrls'][] = ['size' => 'mirror', 'url' => $row['mirrorUrl'], 'source' => $item['source'], 'platform' => $itemPlatform];
        } elseif ($rowType === 'previewUrl' && $type === 'track') {
            $attachments['previewUrls'][] = ['url' => $row['mirrorUrl'], 'source' => $item['source'], 'platform' => $itemPlatform];
        } elseif ($rowType === 'bannerUrl' && $type === 'artist') {
            $attachments['bannerUrls'][] = ['url' => $row['mirrorUrl'], 'source' => $item['source'], 'platform' => $itemPlatform];
        }
    }

    return [
        'success' => true,
        'entityType' => $type,
        'entityId' => $id,
        'platformFilter' => $filter,   // null یعنی همه
        'attachments' => $attachments,
    ];
}

function deleteMirrorUrl(PDO $db, string $type, string $id, ?string $urlType = null,
                         ?string $quality = null, ?int $mirrorId = null, ?string $platform = null): array
{
    // برای حذف: platform خالی = حذف از همه پلتفرمها
    $pf = null;
    if ($platform !== null) {
        $p = strtolower(trim($platform));
        if ($p !== '' && $p !== 'all' && $p !== '*') $pf = normalizePlatform($p);
    }

    if ($mirrorId !== null) {
        $stmt = getStatement("DELETE FROM entityMirrors WHERE id = :mid AND entityType = :t AND entityId = :id");
        $stmt->execute([':mid' => $mirrorId, ':t' => $type, ':id' => $id]);
    } elseif ($urlType) {
        $actual = getAudioUrlTypeWithQuality($urlType, $quality);
        if ($pf !== null) {
            $stmt = getStatement("DELETE FROM entityMirrors
                                  WHERE entityType=:t AND entityId=:id AND urlType=:ut AND platform=:pf");
            $stmt->execute([':ut' => $actual, ':t' => $type, ':id' => $id, ':pf' => $pf]);
        } else {
            $stmt = getStatement("DELETE FROM entityMirrors
                                  WHERE entityType=:t AND entityId=:id AND urlType=:ut");
            $stmt->execute([':ut' => $actual, ':t' => $type, ':id' => $id]);
        }
    } else {
        if ($pf !== null) {
            $stmt = getStatement("DELETE FROM entityMirrors WHERE entityType=:t AND entityId=:id AND platform=:pf");
            $stmt->execute([':t' => $type, ':id' => $id, ':pf' => $pf]);
        } else {
            $stmt = getStatement("DELETE FROM entityMirrors WHERE entityType=:t AND entityId=:id");
            $stmt->execute([':t' => $type, ':id' => $id]);
        }
    }
    $deleted = $stmt->rowCount();
    if ($type === 'track') updateStreamableStatus($db, $id);
    return ['success' => true, 'deleted_count' => $deleted];
}

/* ═══════════════ LYRICS ═══════════════ */

function getLyrics(PDO $db, string $trackId): array
{
    $stmt = getStatement("SELECT lyrics, type, source FROM trackLyrics WHERE trackId = :id");
    $stmt->execute([':id' => $trackId]);
    $row = $stmt->fetch();
    if ($row && !empty($row['lyrics'])) {
        return [
            'success' => true, 'trackId' => $trackId,
            'lyrics'  => json_decode($row['lyrics'], true),
            'type'    => $row['type'],
            'source'  => $row['source'] ?? 'custom',
        ];
    }
    return ['success' => false, 'error' => 'Lyrics not found'];
}

function saveLyrics(PDO $db, string $trackId, $lyrics, string $type = 'unsynced', string $source = 'custom'): array
{
    if (is_string($lyrics)) {
        $decoded = json_decode($lyrics, true);
        if ($decoded === null && json_last_error() !== JSON_ERROR_NONE) {
            return ['success' => false, 'error' => 'Invalid JSON: ' . json_last_error_msg()];
        }
        $lyricsJson = json_encode($decoded, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    } else {
        $lyricsJson = json_encode($lyrics, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }
    if ($lyricsJson === false) return ['success' => false, 'error' => 'Encoding failed'];
    $db->prepare("INSERT IGNORE INTO tracks (trackId) VALUES (:id)")->execute([':id' => $trackId]);
    getStatement("REPLACE INTO trackLyrics (trackId, lyrics, type, source, updatedAt)
                  VALUES (:id, :lyrics, :type, :src, NOW())")
        ->execute([':id' => $trackId, ':lyrics' => $lyricsJson, ':type' => $type, ':src' => $source]);
    return ['success' => true, 'message' => 'Lyrics saved'];
}

function fetchLyricsFromLrclib(string $trackName, string $artistName, ?string $albumName = null): ?array
{
    $params = ['track_name' => $trackName, 'artist_name' => $artistName];
    if ($albumName) $params['album_name'] = $albumName;
    $url = 'https://lrclib.net/api/get?' . http_build_query($params);
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_URL => $url, CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true, CURLOPT_TIMEOUT => 10,
        CURLOPT_HTTPHEADER => ['Accept: application/json'],
    ]);
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($httpCode === 200 && $response) {
        $data = json_decode($response, true);
        if ($data) return [
            'data'   => $data,
            'type'   => !empty($data['syncedLyrics']) ? 'synced' : 'unsynced',
            'source' => 'lrclib',
        ];
    }
    return null;
}

/* ═══════════════ FETCH ENTITY ═══════════════ */

function fetchEntityById(PDO $db, string $type, string $id, ?string $quality = null, ?string $platform = null): ?array
{
    $table = match ($type) { 'artist' => 'artists', 'collection' => 'collections', 'track' => 'tracks', default => null };
    if (!$table) return null;
    $pk   = $type . 'Id';
    $stmt = getStatement("SELECT * FROM $table WHERE $pk = :id");
    $stmt->execute([':id' => $id]);
    $row = $stmt->fetch();
    if (!$row) return null;
    attachAttachments($row, $type, $id, $quality, $platform);
    return $row;
}

/* ═══════════════ CACHE ═══════════════ */

function getAdaptiveTTL(): int
{
    $stmt = getStatement("SELECT successfulRequests, failedRequests FROM rateLimitLog WHERE apiName='itunes' LIMIT 1");
    $stmt->execute();
    $row = $stmt->fetch();
    $base = CACHE_DURATION;
    if ($row) {
        $total = $row['successfulRequests'] + $row['failedRequests'];
        if ($total > 0) {
            $rate = $row['successfulRequests'] / $total;
            if ($rate < 0.5) $base *= 4;
            elseif ($rate < 0.7) $base *= 2;
            elseif ($rate < 0.9) $base = (int)($base * 1.5);
        }
    }
    $hour = (int)date('H');
    if ($hour >= 2 && $hour <= 5) $base = (int)($base * 0.7);
    elseif ($hour >= 18 && $hour <= 23) $base = (int)($base * 1.3);
    return $base;
}

function extractResultIds(array $results): string
{
    $ids = [];
    foreach ($results as $item) {
        if (isset($item['wrapperType'], $item[$item['wrapperType'] . 'Id'])) {
            $ids[] = ['type' => $item['wrapperType'], 'id' => $item[$item['wrapperType'] . 'Id']];
        }
    }
    return json_encode($ids);
}

function saveCacheIds(PDO $db, string $endpoint, array $params, array $results): void
{
    $idsJson = extractResultIds($results);
    if ($idsJson === '[]') return;
    $ttl = CACHE_ADAPTIVE_TTL ? getAdaptiveTTL() : CACHE_DURATION;
    getStatement("REPLACE INTO requestCache (endpoint, params, resultIds, expiresAt, lastAccessed, accessCount)
                  VALUES (:ep, :p, :ids, :ex, NOW(), 1)")
        ->execute([':ep' => $endpoint, ':p' => json_encode($params), ':ids' => $idsJson, ':ex' => date('Y-m-d H:i:s', time() + $ttl)]);
}

function getCachedResults(PDO $db, string $endpoint, array $params): ?array
{
    $paramsJson = json_encode($params);
    $stmt = getStatement("SELECT resultIds FROM requestCache WHERE endpoint=:ep AND params=:p AND expiresAt > NOW() LIMIT 1");
    $stmt->execute([':ep' => $endpoint, ':p' => $paramsJson]);
    $row = $stmt->fetch();
    if (!$row) return null;
    $ids = json_decode($row['resultIds'], true);
    if (!is_array($ids) || empty($ids)) return null;
    $idsByType = ['artist' => [], 'collection' => [], 'track' => []];
    foreach ($ids as $entry) {
        if (empty($entry['type']) || empty($entry['id'])) continue;
        if (isset($idsByType[$entry['type']])) $idsByType[$entry['type']][] = $entry['id'];
    }
    $map = fetchEntitiesByIdsMap($idsByType);
    $results = [];
    foreach ($ids as $entry) {
        $key = $entry['type'] . ':' . $entry['id'];
        if (isset($map[$key])) { $row = $map[$key]; $row['wrapperType'] = $entry['type']; $results[] = $row; }
    }
    if (empty($results) || count($results) < (int)ceil(count($ids) / 2)) {
        try { getStatement("DELETE FROM requestCache WHERE endpoint=:ep AND params=:p")->execute([':ep' => $endpoint, ':p' => $paramsJson]); }
        catch (Throwable $e) {}
        return null;
    }
    getStatement("UPDATE requestCache SET accessCount = accessCount + 1, lastAccessed = NOW() WHERE endpoint=:ep AND params=:p")
        ->execute([':ep' => $endpoint, ':p' => $paramsJson]);
    attachAttachmentsBatch($results, $params['quality'] ?? null, $params['platform'] ?? null);
    foreach ($results as &$r) $r['_source'] = 'cache';
    unset($r);
    return ['resultCount' => count($results), 'results' => $results, 'source' => 'cache'];
}

function cleanExpiredCache(PDO $db): void
{
    if (mt_rand(1, 20) !== 1) return;
    $now = time();
    $stmt = getStatement("SELECT lastRequestTime FROM rateLimitLog WHERE apiName = 'system_cleanup' LIMIT 1");
    $stmt->execute();
    $row = $stmt->fetch();
    $lastCleanup = $row ? strtotime($row['lastRequestTime']) : 0;
    if (($now - $lastCleanup) > 1800) {
        $db->exec("DELETE FROM requestCache WHERE expiresAt < NOW()");
        $db->exec("DELETE FROM requestHistory WHERE requestTime < DATE_SUB(NOW(), INTERVAL 7 DAY)");
        $db->exec("DELETE FROM userSessions WHERE expiresAt < NOW()");
        $db->exec("DELETE FROM apiRequestLog WHERE createdAt < DATE_SUB(NOW(), INTERVAL 30 DAY)");
        $db->exec("UPDATE proxyStatus SET isBlocked = 0, blockedUntil = NULL WHERE blockedUntil < DATE_SUB(NOW(), INTERVAL 24 HOUR)");
        try {
            $retention = (int)VIEW_LOG_RETENTION;
            $db->exec("DELETE FROM trackViews WHERE viewedAt < DATE_SUB(NOW(), INTERVAL $retention SECOND)");
            $db->exec("DELETE FROM viewSessions WHERE lastSeenAt < DATE_SUB(NOW(), INTERVAL 1 DAY)");
            $db->exec("DELETE FROM notifications WHERE isRead = 1 AND createdAt < DATE_SUB(NOW(), INTERVAL 60 DAY)");
        } catch (Throwable $e) {}
        getStatement("REPLACE INTO rateLimitLog (apiName, lastRequestTime) VALUES ('system_cleanup', NOW())")->execute();
    }
}

/* ═══════════════ RATE LIMIT / PROXY ═══════════════ */

function checkRateLimit(string $api = 'itunes'): bool
{
    global $lastRequestTime;
    if (ENABLE_REQUEST_THROTTLING) {
        $now = microtime(true);
        $elapsed = ($now - $lastRequestTime) * 1000000;
        if ($lastRequestTime > 0 && $elapsed < THROTTLE_MIN_INTERVAL) usleep((int)(THROTTLE_MIN_INTERVAL - $elapsed));
        $lastRequestTime = microtime(true);
    }
    return true;
}

function handleRateLimitHit(string $api = 'itunes'): void {}
function resetRateLimit(string $api = 'itunes', bool $success = true): void {}

function loadProxies(): array
{
    static $cache = null;
    if ($cache !== null) return $cache;
    if (!file_exists(PROXY_LIST_FILE)) return $cache = [];
    $lines = file(PROXY_LIST_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    return $cache = array_values(array_filter($lines, fn($l) => strpos($l, '://') !== false));
}

function getNextProxy(): ?string
{
    global $currentProxyIndex;
    $proxies = loadProxies();
    if (empty($proxies)) return null;
    $count = count($proxies);
    $stmt  = getStatement("SELECT isBlocked, blockedUntil FROM proxyStatus WHERE proxyUrl = :url");
    $rep   = getStatement("REPLACE INTO proxyStatus (proxyUrl, lastUsed) VALUES (:url, NOW())");
    for ($i = 0; $i < $count; $i++) {
        $idx   = ($currentProxyIndex + $i) % $count;
        $proxy = $proxies[$idx];
        $stmt->execute([':url' => $proxy]);
        $row = $stmt->fetch();
        if (!$row || !$row['isBlocked'] || strtotime($row['blockedUntil']) < time()) {
            $currentProxyIndex = ($idx + 1) % $count;
            $rep->execute([':url' => $proxy]);
            return $proxy;
        }
    }
    return null;
}

function rotateProxy(): ?string { return getNextProxy(); }

function markProxyStatus(string $proxy, bool $success): void
{
    if ($success) {
        getStatement("UPDATE proxyStatus SET successCount = successCount + 1, isBlocked = 0 WHERE proxyUrl = :url")->execute([':url' => $proxy]);
    } else {
        getStatement("UPDATE proxyStatus SET failCount = failCount + 1, isBlocked = 1, blockedUntil = DATE_ADD(NOW(), INTERVAL 1 HOUR) WHERE proxyUrl = :url")->execute([':url' => $proxy]);
    }
}

/* ═══════════════ ITUNES API ═══════════════ */

function makeApiRequest(string $url, int $retry = 0): ?array
{
    if (!checkRateLimit()) {
        if ($retry < RATE_LIMIT_MAX_RETRIES) {
            usleep((int)((RATE_LIMIT_BASE_DELAY * pow(2, $retry) + mt_rand(0, 1000000) / 1e6) * 1e6));
            return makeApiRequest($url, $retry + 1);
        }
        return null;
    }
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true, CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT => 15, CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_SSL_VERIFYPEER => false, CURLOPT_ENCODING => '',
        CURLOPT_HEADER => true, CURLOPT_FORBID_REUSE => true, CURLOPT_FRESH_CONNECT => true,
    ]);
    if (ENABLE_USER_AGENT_ROTATION) {
        $ua = $GLOBALS['_userAgents'];
        curl_setopt($ch, CURLOPT_USERAGENT, $ua[array_rand($ua)]);
    }
    $currentProxy = null;
    if (USE_PROXY_ROTATION && ($currentProxy = getNextProxy())) curl_setopt($ch, CURLOPT_PROXY, $currentProxy);
    if (ENABLE_IP_SPOOFING) {
        $ip = mt_rand(1, 255) . '.' . mt_rand(0, 255) . '.' . mt_rand(0, 255) . '.' . mt_rand(1, 255);
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['X-Forwarded-For: ' . $ip, 'X-Real-IP: ' . $ip, 'Client-IP: ' . $ip]);
    }
    usleep(mt_rand(20000, 80000));
    curl_setopt($ch, CURLOPT_URL, $url);
    $response   = curl_exec($ch);
    $httpCode   = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $headerSize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
    $totalTime  = curl_getinfo($ch, CURLINFO_TOTAL_TIME_T);
    $body       = substr($response, $headerSize);
    curl_close($ch);
    try {
        getStatement("INSERT INTO requestHistory (requestTime, endpoint, statusCode, responseTime, success)
                      VALUES (NOW(), :ep, :code, :time, :success)")
            ->execute([':ep' => $url, ':code' => $httpCode, ':time' => $totalTime, ':success' => $httpCode === 200 ? 1 : 0]);
    } catch (Throwable $e) {}
    if ($httpCode === 200) {
        resetRateLimit('itunes', true);
        if ($currentProxy) markProxyStatus($currentProxy, true);
        return json_decode($body, true);
    }
    if ($httpCode === 429) {
        handleRateLimitHit('itunes');
        if ($currentProxy) markProxyStatus($currentProxy, false);
        if ($retry < RATE_LIMIT_MAX_RETRIES) return makeApiRequest($url, $retry + 1);
        return null;
    }
    if (in_array($httpCode, [403, 503], true) && $retry < RATE_LIMIT_MAX_RETRIES) {
        rotateProxy();
        sleep(mt_rand(5, 15));
        return makeApiRequest($url, $retry + 1);
    }
    return null;
}

function searchTracksByLyrics(PDO $db, string $term, ?string $quality = null, int $limit = 50, ?string $platform = null): array
{
    $term = trim($term);
    if ($term === '' || mb_strlen($term) < LYRICS_SEARCH_MIN_LENGTH) return [];
    $limit   = max(1, min($limit, LYRICS_SEARCH_MAX_RESULTS));
    $pattern = '%' . mb_strtolower($term, 'UTF-8') . '%';
    try {
        $stmt = getStatement("
            SELECT t.*, 'track' AS wrapperType
            FROM tracks t
            INNER JOIN trackLyrics tl ON tl.trackId = t.trackId
            WHERE CONVERT(tl.lyrics USING utf8mb4) COLLATE utf8mb4_general_ci LIKE :term
            ORDER BY t.trackId DESC LIMIT :lim
        ");
        $stmt->bindValue(':term', $pattern, PDO::PARAM_STR);
        $stmt->bindValue(':lim',  $limit,   PDO::PARAM_INT);
        $stmt->execute();
        $rows = $stmt->fetchAll();
        if (empty($rows)) return [];
        attachAttachmentsBatch($rows, $quality, $platform);
        foreach ($rows as &$row) { $row['_source'] = 'lyrics'; $row['_matchedBy'] = 'lyrics'; }
        unset($row);
        return $rows;
    } catch (Throwable $e) { error_log('Lyrics search failed: ' . $e->getMessage()); return []; }
}

function searchLocalDatabase(array $params): array
{
    $db = getDB();
    $results = []; $seenIds = [];
    $quality = $params['quality'] ?? null;
    $platform = $params['platform'] ?? null;
    if (isset($params['term']) && $params['term'] !== '') {
        $termRaw = (string)$params['term'];
        $term    = '%' . strtolower($termRaw) . '%';
        $limit   = min((int)($params['limit'] ?? 50), 500);
        $entityRaw = strtolower(trim((string)($params['entity'] ?? 'all')));
        $entityMap = [
            'all' => ['artist','collection','track'],
            'musicartist' => ['artist'], 'artist' => ['artist'],
            'album' => ['collection'], 'collection' => ['collection'],
            'song' => ['track'], 'musictrack' => ['track'], 'track' => ['track'],
        ];
        $targets = [];
        foreach (array_map('trim', explode(',', $entityRaw)) as $e) {
            if ($e === '') continue;
            if (isset($entityMap[$e])) foreach ($entityMap[$e] as $t) $targets[$t] = true;
        }
        if (empty($targets)) $targets = ['artist' => true, 'collection' => true, 'track' => true];
        $targets = array_keys($targets);
        $allQueries = [
            'artist'     => ['table' => 'artists',     'idCol' => 'artistId',     'nameCol' => 'artistName',     'wrapper' => 'artist'],
            'collection' => ['table' => 'collections', 'idCol' => 'collectionId', 'nameCol' => 'collectionName', 'wrapper' => 'collection'],
            'track'      => ['table' => 'tracks',      'idCol' => 'trackId',      'nameCol' => 'trackName',      'wrapper' => 'track'],
        ];
        foreach ($targets as $t) {
            if (!isset($allQueries[$t])) continue;
            $q = $allQueries[$t];
            $stmt = getStatement("SELECT *, '{$q['wrapper']}' as wrapperType FROM {$q['table']}
                 WHERE LOWER({$q['nameCol']}) LIKE :term LIMIT :limit");
            $stmt->bindValue(':term', $term);
            $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
            $stmt->execute();
            while ($row = $stmt->fetch()) {
                $entityId = $row[$q['idCol']] ?? null;
                if ($entityId === null || $entityId === '') continue;
                $key = $t . ':' . $entityId;
                if (isset($seenIds[$key])) continue;
                $seenIds[$key] = true;
                $row['_source'] = 'database'; $row['_matchedBy'] = 'name';
                $results[] = $row;
            }
        }
        if (in_array('track', $targets, true) && mb_strlen($termRaw) >= LYRICS_SEARCH_MIN_LENGTH) {
            $lyricLimit = min($limit, LYRICS_SEARCH_MAX_RESULTS);
            $lyricTracks = searchTracksByLyrics($db, $termRaw, null, $lyricLimit, $platform);
            foreach ($lyricTracks as $row) {
                $tid = $row['trackId'] ?? null;
                if (!$tid) continue;
                $key = 'track:' . $tid;
                if (isset($seenIds[$key])) continue;
                $seenIds[$key] = true;
                unset($row['attachments']);
                $results[] = $row;
            }
        }
        attachAttachmentsBatch($results, $quality, $platform);
    } elseif (isset($params['id'])) {
        $ids = explode(',', (string)$params['id']);
        foreach (['artist', 'collection', 'track'] as $type) {
            $t = match ($type) { 'artist' => ['artists', 'artistId'], 'collection' => ['collections', 'collectionId'], 'track' => ['tracks', 'trackId'] };
            [$table, $pk] = $t;
            $cleanIds = array_filter(array_map('trim', $ids), fn($v) => $v !== '');
            if (empty($cleanIds)) continue;
            $ph = implode(',', array_fill(0, count($cleanIds), '?'));
            $stmt = $db->prepare("SELECT * FROM `$table` WHERE `$pk` IN ($ph)");
            $stmt->execute(array_values($cleanIds));
            while ($row = $stmt->fetch()) { $row['wrapperType'] = $type; $row['_source'] = 'database'; $results[] = $row; }
        }
        attachAttachmentsBatch($results, $quality, $platform);
    }
    return ['resultCount' => count($results), 'results' => $results, 'source' => 'database'];
}

function makeApiRequestWithFallback(string $url, array $params, int $retry = 0): array
{
    $response = makeApiRequest($url, $retry);
    if (!$response || !isset($response['results'])) {
        usleep(300000);
        $response = makeApiRequest($url, $retry + 1);
    }
    if ($response && isset($response['results'])) { $response['source'] = 'api'; return $response; }
    return searchLocalDatabase($params);
}

/* ═══════════════ CORE SEARCH / LOOKUP ═══════════════ */

function processApiResults(PDO $db, array &$results, ?string $quality = null, ?string $platform = null): void
{
    $artists = $collections = $tracks = [];
    foreach ($results as $item) {
        $w = $item['wrapperType'] ?? '';
        if ($w === 'artist')          $artists[]     = $item;
        elseif ($w === 'collection')  $collections[] = $item;
        elseif ($w === 'track')       $tracks[]      = $item;
    }
    if (!empty($artists))     saveEntitiesFromApi($db, 'artists', $artists);
    if (!empty($collections)) saveEntitiesFromApi($db, 'collections', $collections);
    if (!empty($tracks))      saveEntitiesFromApi($db, 'tracks', $tracks);
    attachAttachmentsBatch($results, $quality, $platform);
    foreach ($results as &$item) $item['_source'] = 'api';
    unset($item);
    addUrlsFromResults($db, $results);
}

function ensureResponseAttachments(array &$response, array $params): void
{
    if (!isset($response['results']) || !is_array($response['results'])) return;
    $missing = [];
    foreach ($response['results'] as $i => $it) if (!isset($it['attachments'])) $missing[$i] = $it;
    if (!empty($missing)) {
        $slice = array_values($missing);
        attachAttachmentsBatch($slice, $params['quality'] ?? null, $params['platform'] ?? null);
        $k = 0;
        foreach ($missing as $i => $_) $response['results'][$i] = $slice[$k++];
    }
    foreach ($response['results'] as &$item) {
        if (isset($item['isStreamable'])) $item['isStreamable'] = (int)$item['isStreamable'];
        if (!isset($item['_source'])) $item['_source'] = $response['source'] ?? 'unknown';
    }
    unset($item);
}

function mergeLyricMatches(PDO $db, array &$response, array $params): void
{
    $term = (string)($params['term'] ?? '');
    if ($term === '' || mb_strlen($term) < LYRICS_SEARCH_MIN_LENGTH) return;
    $entityRaw = strtolower((string)($params['entity'] ?? 'all'));
    $allowTracks = false;
    foreach (array_map('trim', explode(',', $entityRaw)) as $e) {
        if ($e === '' || $e === 'all') { $allowTracks = true; break; }
        if (in_array($e, ['song','musictrack','track'], true)) { $allowTracks = true; break; }
    }
    if (!$allowTracks) return;
    $existing = [];
    if (!empty($response['results']) && is_array($response['results'])) {
        foreach ($response['results'] as $r) if (!empty($r['trackId'])) $existing['track:' . $r['trackId']] = true;
    }
    $limit = min((int)($params['limit'] ?? 50), 200);
    $lyricTracks = searchTracksByLyrics($db, $term, $params['quality'] ?? null, $limit, $params['platform'] ?? null);
    if (empty($lyricTracks)) return;
    $added = 0;
    foreach ($lyricTracks as $track) {
        $tid = $track['trackId'] ?? null;
        if (!$tid) continue;
        $key = 'track:' . $tid;
        if (isset($existing[$key])) continue;
        $existing[$key] = true;
        $response['results'][] = $track;
        $added++;
    }
    if ($added > 0) {
        $response['resultCount']   = count($response['results']);
        $response['lyricsMatches'] = $added;
        if (($response['source'] ?? '') === 'cache') $response['source'] = 'cache+lyrics';
        elseif (($response['source'] ?? '') === 'api') $response['source'] = 'api+lyrics';
    }
}

function searchiTunes(PDO $db, array $params): array
{
    if (!isset($params['entity'])) $params['entity'] = 'musicArtist,album,song';
    $params['media'] = 'music';
    $cached = getCachedResults($db, 'search', $params);
    if ($cached) {
        mergeLyricMatches($db, $cached, $params);
        addUrlsFromResults($db, $cached['results'] ?? []);
        return $cached;
    }
    $url = ITUNES_SEARCH_API . '?' . http_build_query($params);
    $response = makeApiRequestWithFallback($url, $params);
    if (isset($response['source']) && $response['source'] === 'api' && !empty($response['results'])) {
        processApiResults($db, $response['results'], $params['quality'] ?? null, $params['platform'] ?? null);
        saveCacheIds($db, 'search', $params, $response['results']);
    }
    ensureResponseAttachments($response, $params);
    mergeLyricMatches($db, $response, $params);
    return $response ?? ['resultCount' => 0, 'results' => []];
}

function checkLocalAlbum(PDO $db, string $collectionId, ?string $quality = null, ?string $platform = null): ?array
{
    $stmt = getStatement("SELECT * FROM collections WHERE collectionId = :id");
    $stmt->execute([':id' => $collectionId]);
    $row = $stmt->fetch();
    if (!$row) return null;
    $row['wrapperType'] = 'collection';
    attachAttachments($row, 'collection', $collectionId, $quality, $platform);
    $row['_source'] = 'database';
    if (!empty($row['artistId'])) {
        $artistData = fetchEntityById($db, 'artist', $row['artistId'], $quality, $platform);
        if ($artistData) {
            $row['artistName']    = $row['artistName'] ?? $artistData['artistName'] ?? null;
            $row['artistViewUrl'] = $row['artistViewUrl'] ?? $artistData['artistViewUrl'] ?? null;
        }
    }
    return $row;
}

function checkLocalAlbumTracks(PDO $db, string $collectionId, ?string $quality = null, ?string $platform = null): ?array
{
    $collectionStmt = getStatement("SELECT * FROM collections WHERE collectionId = :id");
    $collectionStmt->execute([':id' => $collectionId]);
    $collection = $collectionStmt->fetch();
    if (!$collection) return null;
    $trackCount = isset($collection['trackCount']) ? (int)$collection['trackCount'] : 0;
    $stmt = getStatement("SELECT * FROM tracks WHERE collectionId = :cid");
    $stmt->execute([':cid' => $collectionId]);
    $tracks = $stmt->fetchAll();
    if (count($tracks) < $trackCount || $trackCount <= 0) return null;
    $collection['wrapperType'] = 'collection';
    $collection['_source'] = 'database';
    if (!empty($collection['artistId'])) {
        $artistData = fetchEntityById($db, 'artist', $collection['artistId'], $quality, $platform);
        if ($artistData) {
            $collection['artistName']    = $collection['artistName'] ?? $artistData['artistName'] ?? null;
            $collection['artistViewUrl'] = $collection['artistViewUrl'] ?? $artistData['artistViewUrl'] ?? null;
        }
    }
    $results = [$collection];
    foreach ($tracks as $track) {
        $track['wrapperType'] = 'track';
        $track['_source'] = 'database';
        if (!empty($track['collectionId'])) {
            foreach (['collectionName','collectionCensoredName','collectionViewUrl','collectionPrice','collectionExplicitness','trackCount','country','currency','collectionArtistName'] as $field) {
                $track[$field] = $track[$field] ?? $collection[$field] ?? null;
            }
        }
        $results[] = $track;
    }
    attachAttachmentsBatch($results, $quality, $platform);
    return $results;
}

function checkLocalTracksById(PDO $db, array $trackIds, ?string $quality = null, ?string $platform = null): ?array
{
    $results = []; $allFound = true; $collectionIds = [];
    foreach ($trackIds as $trackId) {
        $trackId = trim($trackId);
        if ($trackId === '') continue;
        $stmt = getStatement("SELECT * FROM tracks WHERE trackId = :id");
        $stmt->execute([':id' => $trackId]);
        $row = $stmt->fetch();
        if (!$row) { $allFound = false; continue; }
        $row['wrapperType'] = 'track';
        $row['_source'] = 'database';
        $results[] = $row;
        if (!empty($row['collectionId'])) $collectionIds[] = $row['collectionId'];
    }
    $collectionsMap = [];
    if (!empty($collectionIds)) {
        $collectionIds = array_values(array_unique($collectionIds));
        foreach (array_chunk($collectionIds, 500) as $chunk) {
            $ph = implode(',', array_fill(0, count($chunk), '?'));
            $stmt = $db->prepare("SELECT * FROM collections WHERE collectionId IN ($ph)");
            $stmt->execute($chunk);
            while ($c = $stmt->fetch()) $collectionsMap[$c['collectionId']] = $c;
        }
    }
    foreach ($results as &$track) {
        if (!empty($track['collectionId']) && isset($collectionsMap[$track['collectionId']])) {
            $collectionData = $collectionsMap[$track['collectionId']];
            foreach (['collectionName','collectionCensoredName','collectionViewUrl','collectionPrice','collectionExplicitness','trackCount','country','currency','collectionArtistName'] as $field) {
                $track[$field] = $track[$field] ?? $collectionData[$field] ?? null;
            }
        }
    }
    unset($track);
    if (!empty($results)) attachAttachmentsBatch($results, $quality, $platform);
    return $allFound && !empty($results) ? $results : null;
}

function lookupiTunes(PDO $db, array $params): array
{
    $cached = getCachedResults($db, 'lookup', $params);
    if ($cached) { addUrlsFromResults($db, $cached['results'] ?? []); return $cached; }
    $idParam = $params['id'] ?? '';
    $ids     = array_map('trim', explode(',', $idParam));
    $entity  = $params['entity'] ?? null;
    $quality = $params['quality'] ?? null;
    $platform = $params['platform'] ?? null;
    if ($entity === 'album' && count($ids) === 1) {
        $localAlbum = checkLocalAlbum($db, $ids[0], $quality, $platform);
        if ($localAlbum) {
            $response = ['resultCount' => 1, 'results' => [$localAlbum], 'source' => 'database'];
            ensureResponseAttachments($response, $params);
            addUrlsFromResults($db, $response['results']);
            saveCacheIds($db, 'lookup', $params, [$localAlbum]);
            return $response;
        }
    }
    if ($entity === 'song' && !empty($ids)) {
        $isCollectionId = false;
        if (count($ids) === 1) {
            $stmt = getStatement("SELECT collectionId FROM collections WHERE collectionId = :id");
            $stmt->execute([':id' => $ids[0]]);
            $isCollectionId = (bool)$stmt->fetch();
        }
        $localTracks = $isCollectionId ? checkLocalAlbumTracks($db, $ids[0], $quality, $platform) : checkLocalTracksById($db, $ids, $quality, $platform);
        if ($localTracks !== null && !empty($localTracks)) {
            $response = ['resultCount' => count($localTracks), 'results' => $localTracks, 'source' => 'database'];
            ensureResponseAttachments($response, $params);
            addUrlsFromResults($db, $response['results']);
            saveCacheIds($db, 'lookup', $params, $localTracks);
            return $response;
        }
    }
    if (!empty($ids) && !$entity) {
        $local = checkLocalTracksById($db, $ids, $quality, $platform);
        if ($local !== null && !empty($local)) {
            $response = ['resultCount' => count($local), 'results' => $local, 'source' => 'database'];
            ensureResponseAttachments($response, $params);
            addUrlsFromResults($db, $response['results']);
            saveCacheIds($db, 'lookup', $params, $local);
            return $response;
        }
    }
    $url = ITUNES_LOOKUP_API . '?' . http_build_query($params);
    $response = makeApiRequestWithFallback($url, $params);
    if (isset($response['source']) && $response['source'] === 'api' && !empty($response['results'])) {
        processApiResults($db, $response['results'], $params['quality'] ?? null, $params['platform'] ?? null);
        saveCacheIds($db, 'lookup', $params, $response['results']);
    }
    ensureResponseAttachments($response, $params);
    if (!isset($response['source'])) $response['source'] = 'api';
    return $response ?? ['resultCount' => 0, 'results' => []];
}

/* ═══════════════ SUGGEST (LOCAL + ITUNES) ═══════════════ */

function fetchItunesSuggestions(string $term, int $limit = 10, ?string $entity = null): array
{
    $params = [
        'term'   => $term,
        'media'  => 'music',
        'limit'  => $limit,
        'entity' => $entity ?: 'musicArtist,album,song',
    ];
    $url = ITUNES_SEARCH_API . '?' . http_build_query($params);
    $resp = makeApiRequest($url);
    if (!$resp || empty($resp['results'])) return [];
    $out = [];
    $baseUrl = rtrim(SITE_URL, '/') . SPA_BASE_PATH;
    foreach ($resp['results'] as $r) {
        $w = $r['wrapperType'] ?? null;
        $name = $id = null;
        if ($w === 'artist')       { $name = $r['artistName'] ?? null;     $id = $r['artistId'] ?? null; }
        elseif ($w === 'collection') { $name = $r['collectionName'] ?? null; $id = $r['collectionId'] ?? null; }
        elseif ($w === 'track')      { $name = $r['trackName'] ?? null;      $id = $r['trackId'] ?? null; }
        if (!$name || !$id) continue;
        $out[] = [
            'id'         => (string)$id,
            'name'       => $name,
            'type'       => $w,
            'url'        => $baseUrl . '/' . $w . '/' . $id,
            'matchedBy'  => 'itunes',
            'artistName' => $r['artistName'] ?? null,
            'artworkUrl' => $r['artworkUrl100'] ?? $r['artworkUrl60'] ?? null,
        ];
    }
    return $out;
}

function handleSuggest(PDO $db, array $params): array
{
    $q = trim((string)($params['q'] ?? $params['term'] ?? $params['query'] ?? ''));
    if ($q === '') return ['success' => true, 'query' => '', 'count' => 0, 'suggestions' => [], 'source' => 'database'];

    $limit         = min(max((int)($params['limit'] ?? 10), 1), 50);
    $includeLyrics = filter_var($params['includeLyrics'] ?? true, FILTER_VALIDATE_BOOL);
    $includeItunes = filter_var($params['includeItunes'] ?? true, FILTER_VALIDATE_BOOL);
    $qLower        = mb_strtolower($q, 'UTF-8');

    $entityRaw = strtolower(trim((string)($params['entity'] ?? 'all')));
    $entityMap = [
        'all' => ['artist','collection','track'],
        'musicartist' => ['artist'], 'artist' => ['artist'],
        'album' => ['collection'], 'collection' => ['collection'],
        'song' => ['track'], 'musictrack' => ['track'], 'track' => ['track'],
    ];
    $targets = [];
    foreach (array_map('trim', explode(',', $entityRaw)) as $e) {
        if ($e === '') continue;
        if (isset($entityMap[$e])) foreach ($entityMap[$e] as $t) $targets[$t] = true;
    }
    if (empty($targets)) $targets = ['artist' => true, 'collection' => true, 'track' => true];
    $targets = array_keys($targets);

    $queries = [
        'artist'     => ['table' => 'artists',     'idCol' => 'artistId',     'nameCol' => 'artistName',     'wrapper' => 'artist'],
        'collection' => ['table' => 'collections', 'idCol' => 'collectionId', 'nameCol' => 'collectionName', 'wrapper' => 'collection'],
        'track'      => ['table' => 'tracks',      'idCol' => 'trackId',      'nameCol' => 'trackName',      'wrapper' => 'track'],
    ];

    $seen = []; $suggestions = [];
    $baseUrl = rtrim(SITE_URL, '/') . SPA_BASE_PATH;
    $patterns = [$qLower . '%', '%' . $qLower . '%'];

    foreach ($patterns as $pattern) {
        if (count($suggestions) >= $limit) break;
        foreach ($targets as $t) {
            if (count($suggestions) >= $limit) break;
            if (!isset($queries[$t])) continue;
            $qr = $queries[$t];
            $stmt = getStatement(
                "SELECT `{$qr['idCol']}` AS id, `{$qr['nameCol']}` AS name
                 FROM `{$qr['table']}`
                 WHERE LOWER(`{$qr['nameCol']}`) LIKE :p
                 ORDER BY LENGTH(`{$qr['nameCol']}`) ASC LIMIT :lim"
            );
            $stmt->bindValue(':p', $pattern);
            $stmt->bindValue(':lim', $limit * 2, PDO::PARAM_INT);
            $stmt->execute();
            while ($row = $stmt->fetch()) {
                $id = (string)$row['id'];
                if ($id === '' || $row['name'] === null || $row['name'] === '') continue;
                $key = $t . ':' . $id;
                if (isset($seen[$key])) continue;
                $seen[$key] = true;
                $suggestions[] = [
                    'id' => $id, 'name' => (string)$row['name'], 'type' => $qr['wrapper'],
                    'url' => $baseUrl . '/' . $qr['wrapper'] . '/' . $id, 'matchedBy' => 'name',
                ];
                if (count($suggestions) >= $limit) break;
            }
        }
    }

    if ($includeLyrics && in_array('track', $targets, true) && count($suggestions) < $limit && mb_strlen($q) >= LYRICS_SEARCH_MIN_LENGTH) {
        $lyricTracks = searchTracksByLyrics($db, $q, null, $limit * 2, $params['platform'] ?? null);
        foreach ($lyricTracks as $track) {
            if (count($suggestions) >= $limit) break;
            $id = (string)($track['trackId'] ?? '');
            if ($id === '') continue;
            $key = 'track:' . $id;
            if (isset($seen[$key])) continue;
            $seen[$key] = true;
            $name = (string)($track['trackName'] ?? '');
            if ($name === '') continue;
            $suggestions[] = [
                'id' => $id, 'name' => $name, 'type' => 'track',
                'url' => $baseUrl . '/track/' . $id, 'matchedBy' => 'lyrics',
                'artistName' => $track['artistName'] ?? null,
            ];
        }
    }

    if ($includeItunes && count($suggestions) < $limit && mb_strlen($q) >= 2) {
        $itunesLimit = min($limit, 20);
        $itunesItems = fetchItunesSuggestions($q, $itunesLimit);
        foreach ($itunesItems as $item) {
            if (count($suggestions) >= $limit) break;
            $key = $item['type'] . ':' . $item['id'];
            if (isset($seen[$key])) continue;
            $seen[$key] = true;
            $suggestions[] = $item;
        }
    }

    return [
        'success'     => true, 'query' => $q, 'count' => count($suggestions),
        'suggestions' => $suggestions,
        'source'      => 'merged',
    ];
}

/* ═══════════════ OTHER ENDPOINTS ═══════════════ */

function handleBatchLookup(PDO $db, array $params): array
{
    if (empty($params['ids'])) throw new Exception('Missing ids parameter (comma-separated)', 400);
    $ids     = array_map('trim', explode(',', $params['ids']));
    $results = []; $quality = $params['quality'] ?? null; $platform = $params['platform'] ?? null;
    $localNotFound = [];
    foreach ($ids as $id) {
        $found = false;
        foreach (['artist', 'collection', 'track'] as $type) {
            $entity = fetchEntityById($db, $type, $id, $quality, $platform);
            if ($entity) { $entity['_source'] = 'database'; $results[] = $entity; $found = true; break; }
        }
        if (!$found) $localNotFound[] = $id;
    }
    if (!empty($localNotFound)) {
        foreach (array_chunk($localNotFound, BATCH_SIZE) as $chunk) {
            $lookup = lookupiTunes($db, ['id' => implode(',', $chunk), 'quality' => $quality, 'platform' => $platform]);
            if (!empty($lookup['results'])) {
                foreach ($lookup['results'] as &$item) if (!isset($item['_source'])) $item['_source'] = 'api';
                unset($item);
                $results = array_merge($results, $lookup['results']);
            }
        }
    }
    addUrlsFromResults($db, $results);
    return ['resultCount' => count($results), 'results' => $results, 'source' => count($localNotFound) === 0 ? 'database' : 'mixed'];
}

function handleFresh(PDO $db, array $params): array
{
    $limit   = min((int)($params['limit'] ?? 40), 100);
    $quality = $params['quality'] ?? null;
    $platform = $params['platform'] ?? null;
    $stmt = getStatement("
        SELECT DISTINCT t.* FROM entityMirrors m
        INNER JOIN tracks t ON t.trackId = m.entityId
        WHERE m.entityType = 'track' AND m.urlType LIKE 'audioUrl%'
        ORDER BY m.id DESC LIMIT :limit
    ");
    $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
    $stmt->execute();
    $tracks = [];
    while ($row = $stmt->fetch()) { $row['wrapperType'] = 'track'; $row['_source'] = 'database'; $tracks[] = $row; }
    attachAttachmentsBatch($tracks, $quality, $platform);
    addUrlsFromResults($db, $tracks);
    return ['resultCount' => count($tracks), 'results' => $tracks, 'source' => 'database'];
}

function handlePopular(PDO $db, array $params): array
{
    $limit    = min(max((int)($params['limit'] ?? 40), 1), 100);
    $offset   = max((int)($params['offset'] ?? 0), 0);
    $quality  = $params['quality'] ?? null;
    $platform = $params['platform'] ?? null;
    $windowDays = max(1, min((int)($params['days'] ?? POPULAR_WINDOW_DAYS), 365));
    $minRecent  = max(0, (int)($params['minRecent'] ?? POPULAR_MIN_RECENT_VIEWS));
    $noCache    = filter_var($params['nocache'] ?? false, FILTER_VALIDATE_BOOL);
    $cacheKey = 'popular:' . md5(json_encode([
        'limit' => $limit, 'offset' => $offset, 'quality' => $quality, 'platform' => $platform,
        'days' => $windowDays, 'minRecent' => $minRecent,
    ]));
    if (POPULAR_CACHE_ENABLED && !$noCache) {
        $cached = getExternalCache($db, 'popular', $cacheKey);
        if ($cached !== null && is_array($cached['response'])) {
            $resp = $cached['response'];
            $resp['source'] = 'cache'; $resp['cached'] = true;
            $resp['cacheExpiresAt'] = $cached['expiresAt'];
            return $resp;
        }
    }
    $stmt = getStatement("
        SELECT t.*, rv.cnt AS recentViews
        FROM tracks t
        INNER JOIN (
            SELECT trackId, COUNT(*) AS cnt FROM trackViews
            WHERE viewedAt >= DATE_SUB(NOW(), INTERVAL :days DAY)
            GROUP BY trackId HAVING cnt >= :min
        ) rv ON rv.trackId = t.trackId
        WHERE EXISTS (
            SELECT 1 FROM entityMirrors m
            WHERE m.entityType = 'track' AND m.entityId = t.trackId AND m.urlType LIKE 'audioUrl%'
        )
        ORDER BY rv.cnt DESC, t.views DESC, t.trackId DESC
        LIMIT :limit OFFSET :offset
    ");
    $stmt->bindValue(':days',   $windowDays, PDO::PARAM_INT);
    $stmt->bindValue(':min',    $minRecent,  PDO::PARAM_INT);
    $stmt->bindValue(':limit',  $limit,      PDO::PARAM_INT);
    $stmt->bindValue(':offset', $offset,     PDO::PARAM_INT);
    $stmt->execute();
    $tracks = [];
    while ($row = $stmt->fetch()) {
        $recentViews = (int)($row['recentViews'] ?? 0);
        unset($row['recentViews']);
        $row['wrapperType'] = 'track'; $row['_source'] = 'database';
        $row['recentViews'] = $recentViews; $row['views'] = (int)($row['views'] ?? 0);
        $tracks[] = $row;
    }
    attachAttachmentsBatch($tracks, $quality, $platform);
    addUrlsFromResults($db, $tracks);
    $response = [
        'resultCount' => count($tracks), 'results' => $tracks, 'source' => 'database',
        'window' => ['days' => $windowDays, 'minRecent' => $minRecent, 'orderedBy' => 'recent_views_desc'],
    ];
    if (POPULAR_CACHE_ENABLED && !$noCache) {
        $ttl = max(60, strtotime('tomorrow 00:00:00') - time());
        try {
            setExternalCache($db, 'popular', $cacheKey, $response, $ttl);
            $response['cached'] = false;
            $response['cacheExpiresAt'] = date('Y-m-d H:i:s', time() + $ttl);
        } catch (Throwable $e) { error_log('Popular cache write FAILED: ' . $e->getMessage()); }
    }
    return $response;
}

function handleArtistTracks(PDO $db, array $params): array
{
    $artistId = trim((string)($params['id'] ?? $params['artistId'] ?? ''));
    if ($artistId === '') throw new Exception('Missing artist id', 400);
    $limit = min(max((int)($params['limit'] ?? 50), 1), 200);
    if (isset($params['offset']) && $params['offset'] !== '') {
        $offset = max(0, (int)$params['offset']);
        $page   = (int)floor($offset / $limit) + 1;
    } else {
        $page   = max(1, (int)($params['page'] ?? 1));
        $offset = ($page - 1) * $limit;
    }
    $quality = $params['quality'] ?? null;
    $platform = $params['platform'] ?? null;
    $stmt = getStatement("SELECT artistId FROM artists WHERE artistId = :id");
    $stmt->execute([':id' => $artistId]);
    if (!$stmt->fetch()) {
        try { lookupiTunes($db, ['id' => $artistId, 'entity' => 'musicArtist']); } catch (Throwable $e) {}
        $stmt->execute([':id' => $artistId]);
        if (!$stmt->fetch()) {
            return ['success' => false, 'error' => 'Artist not found', 'artistId' => $artistId, 'resultCount' => 0, 'results' => []];
        }
    }
    $sort = strtolower((string)($params['sort'] ?? 'album'));
    $orderBy = match ($sort) {
        'recent' => 'COALESCE(releaseDate, addedAt, NOW()) DESC, t.trackId DESC',
        'name'   => 't.trackName ASC, t.trackId ASC',
        'views'  => 'COALESCE(t.views, 0) DESC, t.trackId DESC',
        default  => 'COALESCE(t.collectionId, "") ASC, COALESCE(t.trackNumber, 0) ASC, t.trackId ASC',
    };
    $countStmt = getStatement("SELECT COUNT(*) FROM tracks WHERE artistId = :aid");
    $countStmt->execute([':aid' => $artistId]);
    $total = (int)$countStmt->fetchColumn();
    $stmt = getStatement("SELECT t.* FROM tracks t WHERE t.artistId = :aid ORDER BY $orderBy LIMIT :limit OFFSET :offset");
    $stmt->bindValue(':aid',    $artistId, PDO::PARAM_STR);
    $stmt->bindValue(':limit',  $limit,    PDO::PARAM_INT);
    $stmt->bindValue(':offset', $offset,   PDO::PARAM_INT);
    $stmt->execute();
    $tracks = [];
    while ($row = $stmt->fetch()) { $row['wrapperType'] = 'track'; $row['_source'] = 'database'; $tracks[] = $row; }
    attachAttachmentsBatch($tracks, $quality, $platform);
    addUrlsFromResults($db, $tracks);
    $pages   = $limit > 0 ? (int)ceil($total / $limit) : 1;
    $hasMore = ($offset + count($tracks)) < $total;
    return [
        'success' => true, 'artistId' => $artistId, 'resultCount' => count($tracks),
        'total' => $total, 'page' => $page, 'limit' => $limit, 'offset' => $offset,
        'pages' => $pages, 'hasMore' => $hasMore, 'sort' => $sort,
        'results' => $tracks, 'source' => 'database',
    ];
}

function handleCacheClear(PDO $db): array
{
    $db->exec("DELETE FROM requestCache");
    $db->exec("DELETE FROM externalCache WHERE service = 'popular'");
    return ['success' => true, 'message' => 'Request cache + popular cache cleared'];
}

function handleStats(PDO $db): array
{
    return [
        'cache_entries'  => (int)$db->query("SELECT COUNT(*) FROM requestCache WHERE expiresAt > NOW()")->fetchColumn(),
        'track_count'    => (int)$db->query("SELECT COUNT(*) FROM tracks")->fetchColumn(),
        'artist_count'   => (int)$db->query("SELECT COUNT(*) FROM artists")->fetchColumn(),
        'album_count'    => (int)$db->query("SELECT COUNT(*) FROM collections")->fetchColumn(),
        'lyrics_count'   => (int)$db->query("SELECT COUNT(*) FROM trackLyrics")->fetchColumn(),
        'sitemap_urls'   => (int)$db->query("SELECT COUNT(*) FROM sitemapUrls")->fetchColumn(),
        'view_sessions'  => (int)$db->query("SELECT COUNT(*) FROM viewSessions")->fetchColumn(),
        'view_records'   => (int)$db->query("SELECT COUNT(*) FROM trackViews")->fetchColumn(),
        'users'          => (int)$db->query("SELECT COUNT(*) FROM users")->fetchColumn(),
        'playlists'      => (int)$db->query("SELECT COUNT(*) FROM playlists")->fetchColumn(),
        'comments'       => (int)$db->query("SELECT COUNT(*) FROM comments")->fetchColumn(),
        'likes'          => (int)$db->query("SELECT COUNT(*) FROM likes")->fetchColumn(),
        'api_apps'       => (int)$db->query("SELECT COUNT(*) FROM apiApps")->fetchColumn(),
        'api_tokens'     => (int)$db->query("SELECT COUNT(*) FROM apiTokens WHERE isActive = 1")->fetchColumn(),
        'mirrors_total'  => (int)$db->query("SELECT COUNT(*) FROM entityMirrors")->fetchColumn(),
        'mirrors_telegram' => (int)$db->query("SELECT COUNT(*) FROM entityMirrors WHERE platform='telegram'")->fetchColumn(),
        'mirrors_bale'     => (int)$db->query("SELECT COUNT(*) FROM entityMirrors WHERE platform='bale'")->fetchColumn(),
        'uptime_seconds' => time() - (filemtime(__FILE__) ?: time()),
    ];
}

function handleProxyStatus(PDO $db): array
{
    return ['proxies' => $db->query("SELECT proxyUrl, successCount, failCount, isBlocked, lastUsed FROM proxyStatus ORDER BY successCount DESC")->fetchAll()];
}

function handleResetRateLimit(PDO $db): array
{
    $db->exec("DELETE FROM rateLimitLog");
    $db->exec("DELETE FROM requestHistory WHERE success = 0 AND requestTime > DATE_SUB(NOW(), INTERVAL 1 HOUR)");
    return ['success' => true, 'message' => 'Rate limit counters reset'];
}

/* ═══════════════ SITEMAP ENDPOINTS ═══════════════ */

function handleSitemapStats(PDO $db): array
{
    $count  = (int)$db->query("SELECT COUNT(*) FROM sitemapUrls")->fetchColumn();
    $byType = $db->query("SELECT entityType, COUNT(*) as c FROM sitemapUrls GROUP BY entityType")->fetchAll();
    $lastSubmission = null;
    try {
        $row = $db->query("SELECT submittedAt, googleCode, totalUrls FROM sitemapSubmissions ORDER BY id DESC LIMIT 1")->fetch();
        if ($row) $lastSubmission = $row;
    } catch (Throwable $e) {}
    return [
        'success' => true, 'total_urls' => $count, 'by_type' => $byType,
        'max_urls' => SITEMAP_MAX_URLS,
        'sitemap_url' => rtrim(SITE_URL, '/') . '/sitemap.xml',
        'sitemap_file' => SITEMAP_FILE_PATH,
        'sitemap_file_exists' => file_exists(SITEMAP_FILE_PATH),
        'google_ping_enabled' => GOOGLE_PING_ENABLED,
        'indexnow_enabled' => INDEXNOW_ENABLED,
        'indexnow_key_file_exists' => file_exists(__DIR__ . '/' . INDEXNOW_KEY . '.txt'),
        'last_submission' => $lastSubmission,
    ];
}

function handleSitemapRebuild(PDO $db): array
{
    $result = writeSitemapFile($db);
    if ($result['success']) {
        $result['sitemap_url'] = rtrim(SITE_URL, '/') . '/sitemap.xml';
        if (AUTO_SUBMIT_ON_REBUILD) {
            $submit = autoSubmitSitemap($db);
            $result['submission'] = [
                'google' => $submit['google']['http_code'] ?? null,
                'indexnow' => $submit['indexnow']['success'] ?? false,
                'total_urls_submitted' => $submit['indexnow']['total_urls'] ?? 0,
            ];
        }
    }
    return $result;
}

function handleSitemapSubmit(PDO $db, array $params): array
{
    $targets = $params['targets'] ?? 'all';
    $sitemapUrl = rtrim(SITE_URL, '/') . '/sitemap.xml';
    $out = ['success' => true, 'timestamp' => date('c')];
    if ($targets === 'all' || $targets === 'google') $out['google'] = submitToGoogle($sitemapUrl);
    if ($targets === 'all' || $targets === 'indexnow') {
        if (!empty($params['urls'])) {
            $urls = is_array($params['urls']) ? $params['urls'] : explode(',', $params['urls']);
            $urls = array_map('trim', $urls);
        } else {
            $stmt = $db->query("SELECT urlPath FROM sitemapUrls ORDER BY lastmod DESC LIMIT " . (int)AUTO_SUBMIT_MAX_URLS);
            $urls = [rtrim(SITE_URL, '/') . '/'];
            while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) $urls[] = rtrim(SITE_URL, '/') . $row['urlPath'];
            $urls = array_values(array_unique($urls));
        }
        $out['indexnow'] = submitToIndexNow($urls);
    }
    logSitemapSubmission($db, $out);
    return $out;
}

function handleSitemapSubmissions(PDO $db, array $params): array
{
    $limit = min((int)($params['limit'] ?? 20), 100);
    $stmt = getStatement("SELECT * FROM sitemapSubmissions ORDER BY id DESC LIMIT :l");
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();
    foreach ($rows as &$r) $r['response'] = json_decode($r['response'], true);
    unset($r);
    return ['success' => true, 'count' => count($rows), 'items' => $rows];
}

/* ═══════════════ DOWNLOADS (SQLite) ═══════════════ */

function resolveTrackIdsFromInput(PDO $db, array $params): array
{
    $trackIds = [];
    if (!empty($params['trackId'])) {
        $ids = is_array($params['trackId']) ? $params['trackId'] : explode(',', $params['trackId']);
        $trackIds = array_merge($trackIds, array_map('trim', $ids));
    }
    if (!empty($params['albumId'])) {
        $albumId = $params['albumId'];
        $stmt = getStatement("SELECT trackId FROM tracks WHERE collectionId = :aid");
        $stmt->execute([':aid' => $albumId]);
        $found = false;
        while ($row = $stmt->fetch()) { $trackIds[] = $row['trackId']; $found = true; }
        if (!$found) {
            lookupiTunes($db, ['id' => $albumId, 'entity' => 'song']);
            $stmt2 = getStatement("SELECT trackId FROM tracks WHERE collectionId = :aid");
            $stmt2->execute([':aid' => $albumId]);
            while ($row = $stmt2->fetch()) $trackIds[] = $row['trackId'];
        }
    }
    if (!empty($params['artistId'])) {
        $stmt = getStatement("SELECT trackId FROM tracks WHERE artistId = :aid");
        $stmt->execute([':aid' => $params['artistId']]);
        while ($row = $stmt->fetch()) $trackIds[] = $row['trackId'];
    }
    return array_values(array_unique($trackIds));
}

function handleDownloadAdd(PDO $db, array $params): array
{
    $trackIds = resolveTrackIdsFromInput($db, $params);
    if (empty($trackIds)) throw new Exception('No tracks resolved. Provide trackId, albumId, or artistId.', 400);
    $quality       = DEFAULT_AUDIO_QUALITY;
    $platform      = $params['platform'] ?? null;
    $priority      = (int)($params['priority'] ?? 0);
    $skipExisting  = filter_var($params['skipExisting'] ?? true, FILTER_VALIDATE_BOOL);
    $force         = filter_var($params['force'] ?? false, FILTER_VALIDATE_BOOL);
    $skipCompleted = filter_var($params['skipCompleted'] ?? true, FILTER_VALIDATE_BOOL);
    $initialStatus = $params['status'] ?? DOWNLOAD_STATUS_PENDING;
    if (!in_array($initialStatus, [DOWNLOAD_STATUS_PENDING, DOWNLOAD_STATUS_DOWNLOADING, DOWNLOAD_STATUS_PAUSED], true)) {
        $initialStatus = DOWNLOAD_STATUS_PENDING;
    }
    $added = $skipped = $failed = [];
    $sqlite = getSQLiteDB();
    $sqlite->beginTransaction();
    try {
        foreach ($trackIds as $tid) {
            if ($skipExisting) {
                $stmt = getSQLiteStatement("SELECT id FROM downloadQueue WHERE trackId = :tid AND status NOT IN ('completed','failed','stopped') LIMIT 1");
                $stmt->execute([':tid' => $tid]);
                if ($stmt->fetch()) { $skipped[] = ['trackId' => $tid, 'reason' => 'Already in queue']; continue; }
            }
            $track = fetchEntityById($db, 'track', $tid, $quality, $platform);
            if (!$track) {
                $lookup = lookupiTunes($db, ['id' => $tid, 'platform' => $platform]);
                if (empty($lookup['results'])) { $failed[] = ['trackId' => $tid, 'reason' => 'Track not found in iTunes']; continue; }
                $track = $lookup['results'][0];
            }
            $hasAudio = !empty($track['attachments']['audioUrls']);
            if ($hasAudio && !$force && $skipCompleted) { $skipped[] = ['trackId' => $tid, 'reason' => 'Audio already exists (skipped)', 'has_audio' => true]; continue; }
            if ($hasAudio && $force) { $finalStatus = DOWNLOAD_STATUS_COMPLETED; $completedClause = 'CURRENT_TIMESTAMP'; }
            else { $finalStatus = $initialStatus; $completedClause = 'NULL'; }
            $sql = "INSERT INTO downloadQueue (trackId, status, quality, priority, addedAt, completedAt)
                    VALUES (:tid, :status, :qual, :prio, CURRENT_TIMESTAMP, $completedClause)";
            $stmt = $sqlite->prepare($sql);
            $stmt->execute([':tid' => $tid, ':status' => $finalStatus, ':qual' => $quality, ':prio' => $priority]);
            $added[] = ['downloadId' => $sqlite->lastInsertId(), 'trackId' => $tid, 'track' => $track];
        }
        $sqlite->commit();
    } catch (Throwable $e) {
        if ($sqlite->inTransaction()) $sqlite->rollBack();
        throw $e;
    }
    return ['success' => true, 'added_count' => count($added), 'skipped_count' => count($skipped), 'failed_count' => count($failed), 'added' => $added, 'skipped' => $skipped, 'failed' => $failed];
}

function handleDownloadQueue(PDO $db, array $params): array
{
    $status = $params['status'] ?? null;
    $limit  = min((int)($params['limit'] ?? 100), 100);
    $offset = (int)($params['offset'] ?? 0);
    $quality = DEFAULT_AUDIO_QUALITY;
    $platform = $params['platform'] ?? null;
    $hasStatus = $status && in_array($status, [DOWNLOAD_STATUS_PENDING, DOWNLOAD_STATUS_DOWNLOADING, DOWNLOAD_STATUS_PAUSED, DOWNLOAD_STATUS_COMPLETED, DOWNLOAD_STATUS_FAILED, DOWNLOAD_STATUS_STOPPED], true);
    $sql = "SELECT * FROM downloadQueue"; $countSql = "SELECT COUNT(*) as total FROM downloadQueue";
    if ($hasStatus) { $sql .= " WHERE status = :status"; $countSql .= " WHERE status = :status"; }
    $sql .= " ORDER BY priority DESC, addedAt DESC LIMIT :limit OFFSET :offset";
    $stmt = getSQLiteStatement($sql); $countStmt = getSQLiteStatement($countSql);
    if ($hasStatus) { $stmt->bindValue(':status', $status); $countStmt->bindValue(':status', $status); }
    $stmt->bindValue(':limit',  $limit, PDO::PARAM_INT);
    $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
    $stmt->execute(); $countStmt->execute();
    $rows = $stmt->fetchAll();
    $trackIds = array_column($rows, 'trackId');
    $tracksMap = [];
    if (!empty($trackIds)) {
        $idsByType = ['track' => $trackIds];
        $tracksMap = fetchEntitiesByIdsMap($idsByType);
        $trackRows = array_values(array_map(function($r){ $r['wrapperType'] = 'track'; return $r; }, $tracksMap));
        attachAttachmentsBatch($trackRows, $quality, $platform);
        $tracksMap = [];
        foreach ($trackRows as $t) $tracksMap['track:' . $t['trackId']] = $t;
    }
    $items = [];
    foreach ($rows as $row) {
        $trackData = $tracksMap['track:' . $row['trackId']] ?? ['trackId' => $row['trackId']];
        $items[] = array_merge($trackData, [
            'download_id' => $row['id'], 'download_status' => $row['status'],
            'file_path' => $row['filePath'], 'quality' => $row['quality'],
            'added_at' => $row['addedAt'], 'started_at' => $row['startedAt'],
            'completed_at' => $row['completedAt'], 'error_message' => $row['errorMessage'],
            'retry_count' => $row['retryCount'], 'priority' => $row['priority'],
            'percent' => (int)$row['percent'],
        ]);
    }
    return ['success' => true, 'total' => (int)$countStmt->fetchColumn(), 'limit' => $limit, 'offset' => $offset, 'items' => $items];
}

function handleDownloadStatus(PDO $db, array $params): array
{
    $id = $params['id'] ?? null; $trackId = $params['trackId'] ?? null;
    if (!$id && !$trackId) throw new Exception('Missing id or trackId parameter', 400);
    $quality = DEFAULT_AUDIO_QUALITY;
    $platform = $params['platform'] ?? null;
    if ($id) { $stmt = getSQLiteStatement("SELECT * FROM downloadQueue WHERE id = :id"); $stmt->execute([':id' => $id]); }
    else { $stmt = getSQLiteStatement("SELECT * FROM downloadQueue WHERE trackId = :tid ORDER BY id DESC LIMIT 1"); $stmt->execute([':tid' => $trackId]); }
    $row = $stmt->fetch();
    if (!$row) return ['success' => false, 'error' => 'Download entry not found'];
    $trackData = fetchEntityById($db, 'track', $row['trackId'], $quality, $platform) ?: ['trackId' => $row['trackId']];
    return ['success' => true, 'download' => array_merge($trackData, [
        'download_id' => $row['id'], 'download_status' => $row['status'],
        'file_path' => $row['filePath'], 'quality' => $row['quality'],
        'added_at' => $row['addedAt'], 'started_at' => $row['startedAt'],
        'completed_at' => $row['completedAt'], 'error_message' => $row['errorMessage'],
        'retry_count' => $row['retryCount'], 'priority' => $row['priority'],
        'percent' => (int)$row['percent'],
    ])];
}

function handleDownloadUpdate(PDO $db, array $params): array
{
    $idParam = $params['id'] ?? $params['ids'] ?? null;
    $trackIdsRaw = $params['trackIds'] ?? [];
    $filterStatus = $params['filterStatus'] ?? null;
    $status = $params['status'] ?? null;
    $filePath = $params['filePath'] ?? null;
    $errorMessage = $params['errorMessage'] ?? null;
    $percent = isset($params['percent']) ? (int)$params['percent'] : null;
    $deleteOnComplete = filter_var($params['deleteOnComplete'] ?? true, FILTER_VALIDATE_BOOL);
    $targetIds = [];
    if ($idParam !== null) { $idArray = is_array($idParam) ? $idParam : explode(',', (string)$idParam); $targetIds = array_map('intval', $idArray); }
    elseif (!empty($trackIdsRaw)) {
        $trackIds = is_array($trackIdsRaw) ? $trackIdsRaw : explode(',', (string)$trackIdsRaw);
        $ph = implode(',', array_fill(0, count($trackIds), '?'));
        $stmt = getSQLiteStatement("SELECT id FROM downloadQueue WHERE trackId IN ($ph)");
        foreach ($trackIds as $i => $tid) $stmt->bindValue($i + 1, $tid);
        $stmt->execute();
        while ($row = $stmt->fetch()) $targetIds[] = $row['id'];
    } elseif ($filterStatus !== null) {
        $stmt = getSQLiteStatement("SELECT id FROM downloadQueue WHERE status = :status");
        $stmt->execute([':status' => $filterStatus]);
        while ($row = $stmt->fetch()) $targetIds[] = $row['id'];
    }
    if (empty($targetIds)) return ['success' => true, 'updated_count' => 0, 'message' => 'No matching entries'];
    $sqlite = getSQLiteDB();
    if ($status === DOWNLOAD_STATUS_COMPLETED && $deleteOnComplete) {
        $ph = implode(',', array_fill(0, count($targetIds), '?'));
        $stmt = $sqlite->prepare("DELETE FROM downloadQueue WHERE id IN ($ph)");
        foreach ($targetIds as $i => $id) $stmt->bindValue($i + 1, $id, PDO::PARAM_INT);
        $stmt->execute();
        return ['success' => true, 'deleted_count' => $stmt->rowCount(), 'message' => 'Items completed and removed from queue'];
    }
    $updates = []; $bindings = [];
    if ($status !== null && $status !== '') {
        if (!in_array($status, [DOWNLOAD_STATUS_PENDING, DOWNLOAD_STATUS_DOWNLOADING, DOWNLOAD_STATUS_PAUSED, DOWNLOAD_STATUS_COMPLETED, DOWNLOAD_STATUS_FAILED, DOWNLOAD_STATUS_STOPPED], true)) throw new Exception('Invalid status', 400);
        $updates[] = "status = ?"; $bindings[] = $status;
        if ($status === DOWNLOAD_STATUS_DOWNLOADING) $updates[] = "startedAt = COALESCE(startedAt, CURRENT_TIMESTAMP)";
        if ($status === DOWNLOAD_STATUS_COMPLETED) { $updates[] = "completedAt = CURRENT_TIMESTAMP"; $updates[] = "errorMessage = NULL"; }
    }
    if ($filePath !== null) { $updates[] = "filePath = ?"; $bindings[] = $filePath; }
    if ($errorMessage !== null) { $updates[] = "errorMessage = ?"; $bindings[] = $errorMessage; if ($status === null) { $updates[] = "status = ?"; $bindings[] = DOWNLOAD_STATUS_FAILED; } }
    if ($percent !== null) { $updates[] = "percent = ?"; $bindings[] = $percent; }
    if (empty($updates)) throw new Exception('Nothing to update', 400);
    $sqlite->beginTransaction();
    try {
        $ph = implode(',', array_fill(0, count($targetIds), '?'));
        $stmt = $sqlite->prepare("UPDATE downloadQueue SET " . implode(', ', $updates) . " WHERE id IN ($ph)");
        $pos = 1;
        foreach ($bindings as $val) $stmt->bindValue($pos++, $val, is_int($val) ? PDO::PARAM_INT : PDO::PARAM_STR);
        foreach ($targetIds as $id) $stmt->bindValue($pos++, $id, PDO::PARAM_INT);
        $stmt->execute();
        $sqlite->commit();
    } catch (Throwable $e) { $sqlite->rollBack(); throw $e; }
    return ['success' => true, 'updated_count' => count($targetIds), 'message' => 'Updated successfully'];
}

function handleDownloadDelete(PDO $db, array $params): array
{
    $idParam = $params['id'] ?? null;
    $idsParam = $params['ids'] ?? null;
    $trackIdsRaw = $params['trackIds'] ?? [];
    $status = $params['status'] ?? null;
    $all = filter_var($params['all'] ?? false, FILTER_VALIDATE_BOOL);
    $singleTrackId = $params['trackId'] ?? null;
    if (!$idParam && !$idsParam && !$trackIdsRaw && !$status && !$all && !$singleTrackId) throw new Exception('No deletion criteria', 400);
    $sql = "DELETE FROM downloadQueue"; $bindings = []; $conditions = [];
    if ($all) {}
    elseif ($idParam !== null) {
        $idsArray = array_map('intval', is_array($idParam) ? $idParam : explode(',', $idParam));
        $conditions[] = "id IN (" . implode(',', array_fill(0, count($idsArray), '?')) . ")";
        $bindings = array_merge($bindings, $idsArray);
    } elseif (!empty($idsParam)) {
        $idsArray = array_map('intval', is_array($idsParam) ? $idsParam : explode(',', $idsParam));
        $conditions[] = "id IN (" . implode(',', array_fill(0, count($idsArray), '?')) . ")";
        $bindings = array_merge($bindings, $idsArray);
    } elseif (!empty($trackIdsRaw)) {
        $trackIds = is_array($trackIdsRaw) ? $trackIdsRaw : explode(',', $trackIdsRaw);
        $conditions[] = "trackId IN (" . implode(',', array_fill(0, count($trackIds), '?')) . ")";
        $bindings = array_merge($bindings, $trackIds);
    } elseif ($status) { $conditions[] = "status = ?"; $bindings[] = $status; }
    elseif ($singleTrackId) { $conditions[] = "trackId = ?"; $bindings[] = $singleTrackId; }
    if (!empty($conditions)) $sql .= " WHERE " . implode(' AND ', $conditions);
    $stmt = getSQLiteStatement($sql);
    foreach ($bindings as $idx => $val) $stmt->bindValue($idx + 1, $val, is_int($val) ? PDO::PARAM_INT : PDO::PARAM_STR);
    $stmt->execute();
    return ['success' => true, 'deleted_count' => $stmt->rowCount()];
}

/* ═══════════════ AUTH / USER MODULE ═══════════════ */

function extractAuthToken(): ?string
{
    if (!empty($_SERVER['HTTP_AUTHORIZATION'])) {
        if (preg_match('/Bearer\s+(.+)$/i', $_SERVER['HTTP_AUTHORIZATION'], $m)) return trim($m[1]);
    }
    if (!empty($_SERVER['HTTP_X_SESSION_TOKEN'])) return trim($_SERVER['HTTP_X_SESSION_TOKEN']);
    if (!empty($_SERVER['HTTP_X_API_TOKEN'])) return trim($_SERVER['HTTP_X_API_TOKEN']);
    if (!empty($_SERVER['HTTP_X_API_KEY'])) return trim($_SERVER['HTTP_X_API_KEY']);
    if (!empty($_GET['token'])) return trim($_GET['token']);
    if (!empty($_GET['sessionToken'])) return trim($_GET['sessionToken']);
    static $bodyCache = null;
    if ($bodyCache === null) {
        $bodyCache = json_decode(file_get_contents('php://input'), true) ?: [];
    }
    if (isset($bodyCache['token'])) return trim((string)$bodyCache['token']);
    if (isset($bodyCache['sessionToken'])) return trim((string)$bodyCache['sessionToken']);
    if (isset($_POST['token'])) return trim((string)$_POST['token']);
    return null;
}

function getBearerUser(PDO $db): ?array
{
    $token = extractAuthToken();
    if (!$token) return null;
    $sid = hash('sha256', 'session:' . $token);
    $stmt = getStatement("SELECT u.* FROM userSessions s
                          INNER JOIN users u ON u.userId = s.userId
                          WHERE s.sessionId = :sid AND s.expiresAt > NOW() LIMIT 1");
    $stmt->execute([':sid' => $sid]);
    $user = $stmt->fetch();
    if ($user) {
        unset($user['passwordHash']);
        $GLOBALS['_ctx']['auth'] = 'session';
        try { getStatement("UPDATE userSessions SET ip = :ip WHERE sessionId = :sid")
              ->execute([':ip' => substr($_SERVER['REMOTE_ADDR'] ?? '', 0, 64), ':sid' => $sid]); } catch (Throwable $e) {}
        return $user;
    }
    $th = hashToken($token);
    $stmt = getStatement("SELECT u.*, t.tokenId AS _tokenId, t.scopes AS _scopes, t.appId AS _appId
                          FROM apiTokens t
                          LEFT JOIN users u ON u.userId = t.userId
                          WHERE t.tokenHash = :th AND t.isActive = 1
                            AND (t.expiresAt IS NULL OR t.expiresAt > NOW())
                          LIMIT 1");
    $stmt->execute([':th' => $th]);
    $row = $stmt->fetch();
    if ($row) {
        try {
            getStatement("UPDATE apiTokens SET lastUsedAt = NOW(), requestCount = requestCount + 1 WHERE tokenId = :tid")
                ->execute([':tid' => $row['_tokenId']]);
        } catch (Throwable $e) {}
        $GLOBALS['_ctx']['auth']    = 'apitoken';
        $GLOBALS['_ctx']['appId']   = $row['_appId'] ?: null;
        $GLOBALS['_ctx']['tokenId'] = $row['_tokenId'];
        $GLOBALS['_ctx']['scopes']  = $row['_scopes'] ? array_map('trim', explode(',', $row['_scopes'])) : [];
        if ($row['userId']) {
            unset($row['passwordHash']);
            unset($row['_tokenId'], $row['_scopes'], $row['_appId']);
            return $row;
        }
        return ['userId' => 0, '_tokenOwnerOnly' => true];
    }
    return null;
}

function requireUser(PDO $db): array
{
    if (!empty($GLOBALS['_ctx']['user'])) return $GLOBALS['_ctx']['user'];
    $u = getBearerUser($db);
    if (!$u || empty($u['userId'])) {
        respond(['success' => false, 'error' => 'Unauthorized: authentication required'], 401);
    }
    $GLOBALS['_ctx']['user'] = $u;
    return $u;
}

function requireAuth(PDO $db, bool $allowMaster = true, array $requiredScopes = []): array
{
    if ($allowMaster && TRUST_MASTER_TOKEN) {
        $tok = extractAuthToken();
        if ($tok && hash_equals(API_TOKEN, $tok)) {
            $GLOBALS['_ctx']['auth'] = 'master';
            $GLOBALS['_ctx']['scopes'] = ['*'];
            return ['userId' => null, 'role' => 'master', '_master' => true];
        }
    }
    $u = requireUser($db);
    if (!empty($requiredScopes)) {
        $scopes = $GLOBALS['_ctx']['scopes'] ?? [];
        if (!in_array('*', $scopes, true)) {
            foreach ($requiredScopes as $s) {
                if (!in_array($s, $scopes, true)) respond(['success' => false, 'error' => 'Forbidden: missing scope ' . $s], 403);
            }
        }
    }
    return $u;
}

function validateEmail(string $email): bool { return (bool)filter_var($email, FILTER_VALIDATE_EMAIL); }
function validateUsername(string $u): bool
{
    $len = mb_strlen($u);
    if ($len < USERNAME_MIN_LENGTH || $len > USERNAME_MAX_LENGTH) return false;
    return (bool)preg_match('/^[a-zA-Z0-9_.\-]+$/', $u);
}

function sanitizeUser(array $u): array
{
    $u = array_diff_key($u, array_flip(['passwordHash']));
    return $u;
}

function userExistsByEmail(PDO $db, string $email): bool
{
    $stmt = getStatement("SELECT 1 FROM users WHERE LOWER(email) = LOWER(:e) LIMIT 1");
    $stmt->execute([':e' => $email]);
    return (bool)$stmt->fetch();
}

function userExistsByUsername(PDO $db, string $username): bool
{
    $stmt = getStatement("SELECT 1 FROM users WHERE LOWER(username) = LOWER(:u) LIMIT 1");
    $stmt->execute([':u' => $username]);
    return (bool)$stmt->fetch();
}

function createUserSession(PDO $db, int $userId): array
{
    $token = generateToken();
    $sid   = hash('sha256', 'session:' . $token);
    $ip    = substr($_SERVER['REMOTE_ADDR'] ?? '', 0, 64);
    $ua    = substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 1024);
    $exp   = time() + USER_SESSION_TTL;
    getStatement("INSERT INTO userSessions (sessionId, userId, ip, userAgent, expiresAt)
                  VALUES (:sid, :uid, :ip, :ua, :exp)")
        ->execute([
            ':sid' => $sid, ':uid' => $userId, ':ip' => $ip, ':ua' => $ua,
            ':exp' => date('Y-m-d H:i:s', $exp),
        ]);
    return ['sessionToken' => $token, 'expiresAt' => date('c', $exp)];
}

function handleSignup(PDO $db, array $params): array
{
    if (!ENABLE_REGISTRATION) throw new Exception('Registration is disabled', 403);
    $email    = trim((string)($params['email'] ?? ''));
    $username = trim((string)($params['username'] ?? ''));
    $password = (string)($params['password'] ?? '');
    $displayName = trim((string)($params['displayName'] ?? $username));

    if (!validateEmail($email)) throw new Exception('Invalid email address', 400);
    if (!validateUsername($username)) throw new Exception('Invalid username (3-32 chars, letters/numbers/._-)', 400);
    if (mb_strlen($password) < PASSWORD_MIN_LENGTH) throw new Exception('Password must be at least ' . PASSWORD_MIN_LENGTH . ' characters', 400);
    if (userExistsByEmail($db, $email)) throw new Exception('Email already registered', 409);
    if (userExistsByUsername($db, $username)) throw new Exception('Username already taken', 409);

    $hash = hashPassword($password);
    $stmt = getStatement("INSERT INTO users (email, username, passwordHash, displayName)
                          VALUES (:e, :u, :p, :d)");
    $stmt->execute([':e' => $email, ':u' => $username, ':p' => $hash, ':d' => $displayName ?: $username]);
    $userId = (int)$db->lastInsertId();

    $stmt = getStatement("SELECT * FROM users WHERE userId = :id");
    $stmt->execute([':id' => $userId]);
    $user = $stmt->fetch();
    $session = createUserSession($db, $userId);
    return [
        'success'  => true,
        'message'  => 'Registration successful',
        'user'     => sanitizeUser($user),
        'session'  => $session,
    ];
}

function handleLogin(PDO $db, array $params): array
{
    $identifier = trim((string)($params['email'] ?? $params['username'] ?? $params['identifier'] ?? ''));
    $password   = (string)($params['password'] ?? '');
    if ($identifier === '' || $password === '') throw new Exception('Missing credentials', 400);

    $stmt = getStatement("SELECT * FROM users WHERE LOWER(email) = LOWER(:i) OR LOWER(username) = LOWER(:i) LIMIT 1");
    $stmt->execute([':i' => $identifier]);
    $user = $stmt->fetch();
    if (!$user || !verifyPassword($password, $user['passwordHash'])) {
        throw new Exception('Invalid email/username or password', 401);
    }
    try { getStatement("UPDATE users SET lastLoginAt = NOW() WHERE userId = :id")->execute([':id' => $user['userId']]); } catch (Throwable $e) {}
    $session = createUserSession($db, (int)$user['userId']);
    return [
        'success' => true, 'message' => 'Login successful',
        'user'    => sanitizeUser($user),
        'session' => $session,
    ];
}

function handleLogout(PDO $db): array
{
    $token = extractAuthToken();
    if ($token) {
        $sid = hash('sha256', 'session:' . $token);
        getStatement("DELETE FROM userSessions WHERE sessionId = :sid")->execute([':sid' => $sid]);
    }
    return ['success' => true, 'message' => 'Logged out'];
}

function handleMe(PDO $db): array
{
    $user = requireUser($db);
    return ['success' => true, 'user' => sanitizeUser($user)];
}

function handleRefreshSession(PDO $db): array
{
    $user = requireUser($db);
    $token = extractAuthToken();
    if ($token) {
        $sid = hash('sha256', 'session:' . $token);
        getStatement("DELETE FROM userSessions WHERE sessionId = :sid")->execute([':sid' => $sid]);
    }
    $session = createUserSession($db, (int)$user['userId']);
    return ['success' => true, 'session' => $session];
}

function handleGetUser(PDO $db, array $params): array
{
    $id       = $params['id'] ?? $params['userId'] ?? null;
    $username = $params['username'] ?? null;
    if (!$id && !$username) throw new Exception('Missing id or username', 400);
    if ($id) {
        $stmt = getStatement("SELECT * FROM users WHERE userId = :id");
        $stmt->execute([':id' => $id]);
    } else {
        $stmt = getStatement("SELECT * FROM users WHERE LOWER(username) = LOWER(:u)");
        $stmt->execute([':u' => $username]);
    }
    $user = $stmt->fetch();
    if (!$user) return ['success' => false, 'error' => 'User not found'];
    $viewer = $GLOBALS['_ctx']['user'] ?? null;
    $isFollowing = false;
    if ($viewer && !empty($viewer['userId'])) {
        $s = getStatement("SELECT 1 FROM follows WHERE followerId = :a AND followingId = :b LIMIT 1");
        $s->execute([':a' => $viewer['userId'], ':b' => $user['userId']]);
        $isFollowing = (bool)$s->fetch();
    }
    return ['success' => true, 'user' => sanitizeUser($user), 'isFollowing' => $isFollowing];
}

function handleUpdateProfile(PDO $db, array $params): array
{
    $user = requireUser($db);
    $updates = []; $bindings = [];
    foreach (['displayName', 'avatarUrl', 'bio', 'country'] as $f) {
        if (array_key_exists($f, $params)) { $updates[] = "`$f` = ?"; $bindings[] = $params[$f]; }
    }
    if (array_key_exists('isPrivate', $params)) { $updates[] = "`isPrivate` = ?"; $bindings[] = (int)(bool)$params['isPrivate']; }
    if (array_key_exists('password', $params)) {
        if (mb_strlen($params['password']) < PASSWORD_MIN_LENGTH) throw new Exception('Password too short', 400);
        $updates[] = "`passwordHash` = ?"; $bindings[] = hashPassword($params['password']);
    }
    if (empty($updates)) throw new Exception('Nothing to update', 400);
    $bindings[] = $user['userId'];
    $stmt = $db->prepare("UPDATE users SET " . implode(', ', $updates) . " WHERE userId = ?");
    $stmt->execute($bindings);
    $stmt = getStatement("SELECT * FROM users WHERE userId = :id");
    $stmt->execute([':id' => $user['userId']]);
    return ['success' => true, 'user' => sanitizeUser($stmt->fetch())];
}

function handleUserSearch(PDO $db, array $params): array
{
    $q = trim((string)($params['q'] ?? $params['term'] ?? ''));
    $limit = min(max((int)($params['limit'] ?? 20), 1), 100);
    if ($q === '') return ['success' => true, 'count' => 0, 'users' => []];
    $term = '%' . strtolower($q) . '%';
    $stmt = getStatement("SELECT userId, username, displayName, avatarUrl, bio, followerCount, followingCount, isVerified
                          FROM users
                          WHERE LOWER(username) LIKE :t OR LOWER(displayName) LIKE :t
                          ORDER BY followerCount DESC, userId DESC
                          LIMIT :lim");
    $stmt->bindValue(':t', $term);
    $stmt->bindValue(':lim', $limit, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();
    return ['success' => true, 'count' => count($rows), 'users' => $rows];
}

/* ═══════════════ FOLLOWS ═══════════════ */

function handleFollow(PDO $db, array $params): array
{
    $user = requireUser($db);
    $target = (int)($params['userId'] ?? $params['id'] ?? 0);
    if (!$target) throw new Exception('Missing userId', 400);
    if ($target === (int)$user['userId']) throw new Exception('Cannot follow yourself', 400);

    $s = getStatement("SELECT userId FROM users WHERE userId = :id LIMIT 1");
    $s->execute([':id' => $target]);
    if (!$s->fetch()) throw new Exception('User not found', 404);

    $db->beginTransaction();
    try {
        $ins = getStatement("INSERT IGNORE INTO follows (followerId, followingId) VALUES (:a, :b)");
        $ins->execute([':a' => $user['userId'], ':b' => $target]);
        if ($ins->rowCount() > 0) {
            getStatement("UPDATE users SET followerCount = followerCount + 1 WHERE userId = :b")->execute([':b' => $target]);
            getStatement("UPDATE users SET followingCount = followingCount + 1 WHERE userId = :a")->execute([':a' => $user['userId']]);
            createNotification($db, $target, (int)$user['userId'], 'follow', 'user', $user['userId'], $user['displayName'] . ' started following you');
        }
        $db->commit();
    } catch (Throwable $e) { $db->rollBack(); throw $e; }
    return ['success' => true, 'following' => true];
}

function handleUnfollow(PDO $db, array $params): array
{
    $user = requireUser($db);
    $target = (int)($params['userId'] ?? $params['id'] ?? 0);
    if (!$target) throw new Exception('Missing userId', 400);
    $db->beginTransaction();
    try {
        $del = getStatement("DELETE FROM follows WHERE followerId = :a AND followingId = :b");
        $del->execute([':a' => $user['userId'], ':b' => $target]);
        if ($del->rowCount() > 0) {
            getStatement("UPDATE users SET followerCount = GREATEST(followerCount - 1, 0) WHERE userId = :b")->execute([':b' => $target]);
            getStatement("UPDATE users SET followingCount = GREATEST(followingCount - 1, 0) WHERE userId = :a")->execute([':a' => $user['userId']]);
        }
        $db->commit();
    } catch (Throwable $e) { $db->rollBack(); throw $e; }
    return ['success' => true, 'following' => false];
}

function handleFollowers(PDO $db, array $params): array
{
    $target = (int)($params['userId'] ?? $params['id'] ?? 0);
    if (!$target) { $me = $GLOBALS['_ctx']['user'] ?? null; $target = (int)($me['userId'] ?? 0); }
    if (!$target) throw new Exception('Missing userId', 400);
    $limit  = min(max((int)($params['limit'] ?? 50), 1), 200);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $stmt = getStatement("SELECT u.userId, u.username, u.displayName, u.avatarUrl, u.isVerified, u.followerCount, f.createdAt AS followedAt
                          FROM follows f INNER JOIN users u ON u.userId = f.followerId
                          WHERE f.followingId = :id
                          ORDER BY f.createdAt DESC LIMIT :l OFFSET :o");
    $stmt->bindValue(':id', $target, PDO::PARAM_INT);
    $stmt->bindValue(':l',  $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o',  $offset, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();
    $total = (int)$db->query("SELECT COUNT(*) FROM follows WHERE followingId = " . (int)$target)->fetchColumn();
    return ['success' => true, 'total' => $total, 'count' => count($rows), 'followers' => $rows];
}

function handleFollowing(PDO $db, array $params): array
{
    $target = (int)($params['userId'] ?? $params['id'] ?? 0);
    if (!$target) { $me = $GLOBALS['_ctx']['user'] ?? null; $target = (int)($me['userId'] ?? 0); }
    if (!$target) throw new Exception('Missing userId', 400);
    $limit  = min(max((int)($params['limit'] ?? 50), 1), 200);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $stmt = getStatement("SELECT u.userId, u.username, u.displayName, u.avatarUrl, u.isVerified, u.followerCount, f.createdAt AS followedAt
                          FROM follows f INNER JOIN users u ON u.userId = f.followingId
                          WHERE f.followerId = :id
                          ORDER BY f.createdAt DESC LIMIT :l OFFSET :o");
    $stmt->bindValue(':id', $target, PDO::PARAM_INT);
    $stmt->bindValue(':l',  $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o',  $offset, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();
    $total = (int)$db->query("SELECT COUNT(*) FROM follows WHERE followerId = " . (int)$target)->fetchColumn();
    return ['success' => true, 'total' => $total, 'count' => count($rows), 'following' => $rows];
}

function handleFollowStatus(PDO $db, array $params): array
{
    $viewer = $GLOBALS['_ctx']['user'] ?? null;
    $target = (int)($params['userId'] ?? $params['id'] ?? 0);
    if (!$viewer || !$target) return ['success' => true, 'isFollowing' => false, 'isFollowedBy' => false];
    $s1 = getStatement("SELECT 1 FROM follows WHERE followerId = :a AND followingId = :b LIMIT 1");
    $s1->execute([':a' => $viewer['userId'], ':b' => $target]);
    $s2 = getStatement("SELECT 1 FROM follows WHERE followerId = :a AND followingId = :b LIMIT 1");
    $s2->execute([':a' => $target, ':b' => $viewer['userId']]);
    return ['success' => true, 'isFollowing' => (bool)$s1->fetch(), 'isFollowedBy' => (bool)$s2->fetch()];
}

/* ═══════════════ LIKES ═══════════════ */

function handleLike(PDO $db, array $params): array
{
    $user = requireUser($db);
    $entityType = strtolower((string)($params['entityType'] ?? $params['type'] ?? ''));
    $entityId   = (string)($params['entityId'] ?? $params['id'] ?? '');
    if (!in_array($entityType, ['track', 'collection', 'artist', 'playlist', 'comment'], true)) throw new Exception('Invalid entityType', 400);
    if ($entityId === '') throw new Exception('Missing entityId', 400);

    $ins = getStatement("INSERT IGNORE INTO likes (userId, entityType, entityId) VALUES (:u, :t, :e)");
    $ins->execute([':u' => $user['userId'], ':t' => $entityType, ':e' => $entityId]);
    if ($ins->rowCount() > 0) {
        getStatement("UPDATE users SET likeCount = likeCount + 1 WHERE userId = :u")->execute([':u' => $user['userId']]);
        if ($entityType === 'playlist') {
            getStatement("UPDATE playlists SET likeCount = likeCount + 1 WHERE playlistId = :id")->execute([':id' => $entityId]);
            $owner = getStatement("SELECT userId FROM playlists WHERE playlistId = :id");
            $owner->execute([':id' => $entityId]);
            $row = $owner->fetch();
            if ($row && (int)$row['userId'] !== (int)$user['userId']) {
                createNotification($db, (int)$row['userId'], (int)$user['userId'], 'like', 'playlist', $entityId, $user['displayName'] . ' liked your playlist');
            }
        }
        if ($entityType === 'comment') {
            getStatement("UPDATE comments SET likeCount = likeCount + 1 WHERE commentId = :id")->execute([':id' => $entityId]);
        }
    }
    return ['success' => true, 'liked' => true];
}

function handleUnlike(PDO $db, array $params): array
{
    $user = requireUser($db);
    $entityType = strtolower((string)($params['entityType'] ?? $params['type'] ?? ''));
    $entityId   = (string)($params['entityId'] ?? $params['id'] ?? '');
    if (!in_array($entityType, ['track', 'collection', 'artist', 'playlist', 'comment'], true)) throw new Exception('Invalid entityType', 400);
    if ($entityId === '') throw new Exception('Missing entityId', 400);

    $del = getStatement("DELETE FROM likes WHERE userId = :u AND entityType = :t AND entityId = :e");
    $del->execute([':u' => $user['userId'], ':t' => $entityType, ':e' => $entityId]);
    if ($del->rowCount() > 0) {
        getStatement("UPDATE users SET likeCount = GREATEST(likeCount - 1, 0) WHERE userId = :u")->execute([':u' => $user['userId']]);
        if ($entityType === 'playlist') {
            getStatement("UPDATE playlists SET likeCount = GREATEST(likeCount - 1, 0) WHERE playlistId = :id")->execute([':id' => $entityId]);
        }
        if ($entityType === 'comment') {
            getStatement("UPDATE comments SET likeCount = GREATEST(likeCount - 1, 0) WHERE commentId = :id")->execute([':id' => $entityId]);
        }
    }
    return ['success' => true, 'liked' => false];
}

function handleLikeStatus(PDO $db, array $params): array
{
    $viewer = $GLOBALS['_ctx']['user'] ?? null;
    $entityType = strtolower((string)($params['entityType'] ?? $params['type'] ?? ''));
    $entityId   = (string)($params['entityId'] ?? $params['id'] ?? '');
    if (!$entityType || !$entityId) throw new Exception('Missing entityType/entityId', 400);
    $total = (int)$db->query("SELECT COUNT(*) FROM likes WHERE entityType = " . $db->quote($entityType) . " AND entityId = " . $db->quote($entityId))->fetchColumn();
    $liked = false;
    if ($viewer && !empty($viewer['userId'])) {
        $s = getStatement("SELECT 1 FROM likes WHERE userId = :u AND entityType = :t AND entityId = :e LIMIT 1");
        $s->execute([':u' => $viewer['userId'], ':t' => $entityType, ':e' => $entityId]);
        $liked = (bool)$s->fetch();
    }
    return ['success' => true, 'liked' => $liked, 'likeCount' => $total];
}

function handleUserLikes(PDO $db, array $params): array
{
    $target = (int)($params['userId'] ?? $params['id'] ?? 0);
    if (!$target) { $me = $GLOBALS['_ctx']['user'] ?? null; $target = (int)($me['userId'] ?? 0); }
    if (!$target) throw new Exception('Missing userId', 400);
    $entityType = isset($params['entityType']) ? strtolower((string)$params['entityType']) : null;
    $limit  = min(max((int)($params['limit'] ?? 50), 1), 200);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $sql = "SELECT entityType, entityId, createdAt FROM likes WHERE userId = :u";
    if ($entityType) $sql .= " AND entityType = :t";
    $sql .= " ORDER BY id DESC LIMIT :l OFFSET :o";
    $stmt = getStatement($sql);
    $stmt->bindValue(':u', $target, PDO::PARAM_INT);
    if ($entityType) $stmt->bindValue(':t', $entityType);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o', $offset, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();
    return ['success' => true, 'count' => count($rows), 'items' => $rows];
}

/* ═══════════════ COMMENTS ═══════════════ */

function handleCommentCreate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $entityType = strtolower((string)($params['entityType'] ?? $params['type'] ?? ''));
    $entityId   = (string)($params['entityId'] ?? $params['id'] ?? '');
    $content    = trim((string)($params['content'] ?? $params['text'] ?? ''));
    $parentId   = isset($params['parentId']) ? (int)$params['parentId'] : null;

    if (!in_array($entityType, ['track', 'collection', 'artist', 'playlist'], true)) throw new Exception('Invalid entityType', 400);
    if ($entityId === '') throw new Exception('Missing entityId', 400);
    if ($content === '') throw new Exception('Comment cannot be empty', 400);
    if (mb_strlen($content) > COMMENT_MAX_LENGTH) throw new Exception('Comment too long (max ' . COMMENT_MAX_LENGTH . ')', 400);

    if ($parentId) {
        $p = getStatement("SELECT commentId FROM comments WHERE commentId = :id AND isDeleted = 0 LIMIT 1");
        $p->execute([':id' => $parentId]);
        if (!$p->fetch()) throw new Exception('Parent comment not found', 404);
    }

    $ins = getStatement("INSERT INTO comments (userId, entityType, entityId, parentId, content)
                         VALUES (:u, :t, :e, :p, :c)");
    $ins->execute([':u' => $user['userId'], ':t' => $entityType, ':e' => $entityId, ':p' => $parentId, ':c' => $content]);
    $cid = (int)$db->lastInsertId();

    if ($parentId) {
        getStatement("UPDATE comments SET replyCount = replyCount + 1 WHERE commentId = :id")->execute([':id' => $parentId]);
        $parent = getStatement("SELECT userId FROM comments WHERE commentId = :id");
        $parent->execute([':id' => $parentId]);
        $prow = $parent->fetch();
        if ($prow && (int)$prow['userId'] !== (int)$user['userId']) {
            createNotification($db, (int)$prow['userId'], (int)$user['userId'], 'reply', 'comment', $parentId, $user['displayName'] . ' replied to your comment');
        }
    }

    $get = getStatement("SELECT c.*, u.username, u.displayName, u.avatarUrl, u.isVerified
                         FROM comments c INNER JOIN users u ON u.userId = c.userId
                         WHERE c.commentId = :id");
    $get->execute([':id' => $cid]);
    return ['success' => true, 'comment' => $get->fetch()];
}

function handleCommentList(PDO $db, array $params): array
{
    $entityType = strtolower((string)($params['entityType'] ?? $params['type'] ?? ''));
    $entityId   = (string)($params['entityId'] ?? $params['id'] ?? '');
    if (!$entityType || !$entityId) throw new Exception('Missing entityType/entityId', 400);
    $limit  = min(max((int)($params['limit'] ?? 50), 1), 200);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $viewer = $GLOBALS['_ctx']['user'] ?? null;

    $stmt = getStatement("SELECT c.*, u.username, u.displayName, u.avatarUrl, u.isVerified
                          FROM comments c INNER JOIN users u ON u.userId = c.userId
                          WHERE c.entityType = :t AND c.entityId = :e AND c.isDeleted = 0 AND c.parentId IS NULL
                          ORDER BY c.createdAt DESC LIMIT :l OFFSET :o");
    $stmt->bindValue(':t', $entityType);
    $stmt->bindValue(':e', $entityId);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o', $offset, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();

    $total = (int)(function() use ($db, $entityType, $entityId) {
        $s = getStatement("SELECT COUNT(*) FROM comments WHERE entityType = :t AND entityId = :e AND isDeleted = 0 AND parentId IS NULL");
        $s->execute([':t' => $entityType, ':e' => $entityId]);
        return $s->fetchColumn();
    })();

    $likedMap = [];
    if ($viewer && !empty($viewer['userId']) && !empty($rows)) {
        $ids = array_column($rows, 'commentId');
        $ph  = implode(',', array_fill(0, count($ids), '?'));
        $s = $db->prepare("SELECT commentId FROM commentLikes WHERE userId = ? AND commentId IN ($ph)");
        $s->execute(array_merge([$viewer['userId']], $ids));
        while ($r = $s->fetch()) $likedMap[(int)$r['commentId']] = true;
    }
    foreach ($rows as &$r) {
        $r['likedByMe'] = isset($likedMap[(int)$r['commentId']]);
    }
    unset($r);
    return ['success' => true, 'total' => $total, 'count' => count($rows), 'comments' => $rows];
}

function handleCommentReplies(PDO $db, array $params): array
{
    $parentId = (int)($params['parentId'] ?? $params['id'] ?? 0);
    if (!$parentId) throw new Exception('Missing parentId', 400);
    $limit = min(max((int)($params['limit'] ?? 50), 1), 200);
    $stmt = getStatement("SELECT c.*, u.username, u.displayName, u.avatarUrl, u.isVerified
                          FROM comments c INNER JOIN users u ON u.userId = c.userId
                          WHERE c.parentId = :p AND c.isDeleted = 0
                          ORDER BY c.createdAt ASC LIMIT :l");
    $stmt->bindValue(':p', $parentId, PDO::PARAM_INT);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->execute();
    return ['success' => true, 'comments' => $stmt->fetchAll()];
}

function handleCommentUpdate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $cid = (int)($params['commentId'] ?? $params['id'] ?? 0);
    $content = trim((string)($params['content'] ?? $params['text'] ?? ''));
    if (!$cid || $content === '') throw new Exception('Missing commentId or content', 400);
    if (mb_strlen($content) > COMMENT_MAX_LENGTH) throw new Exception('Comment too long', 400);
    $s = getStatement("SELECT userId FROM comments WHERE commentId = :id AND isDeleted = 0");
    $s->execute([':id' => $cid]);
    $row = $s->fetch();
    if (!$row) throw new Exception('Comment not found', 404);
    $isOwner = (int)$row['userId'] === (int)$user['userId'];
    $isAdmin = in_array($user['role'] ?? 'user', ['admin','moderator'], true);
    if (!$isOwner && !$isAdmin) throw new Exception('Forbidden', 403);
    getStatement("UPDATE comments SET content = :c WHERE commentId = :id")->execute([':c' => $content, ':id' => $cid]);
    return ['success' => true, 'message' => 'Comment updated'];
}

function handleCommentDelete(PDO $db, array $params): array
{
    $user = requireUser($db);
    $cid = (int)($params['commentId'] ?? $params['id'] ?? 0);
    if (!$cid) throw new Exception('Missing commentId', 400);
    $s = getStatement("SELECT userId, parentId FROM comments WHERE commentId = :id");
    $s->execute([':id' => $cid]);
    $row = $s->fetch();
    if (!$row) throw new Exception('Comment not found', 404);
    $isOwner = (int)$row['userId'] === (int)$user['userId'];
    $isAdmin = in_array($user['role'] ?? 'user', ['admin','moderator'], true);
    if (!$isOwner && !$isAdmin) throw new Exception('Forbidden', 403);
    getStatement("UPDATE comments SET isDeleted = 1, content = '[deleted]' WHERE commentId = :id")->execute([':id' => $cid]);
    if (!empty($row['parentId'])) {
        getStatement("UPDATE comments SET replyCount = GREATEST(replyCount - 1, 0) WHERE commentId = :id")->execute([':id' => $row['parentId']]);
    }
    return ['success' => true, 'message' => 'Comment deleted'];
}

function handleCommentLike(PDO $db, array $params): array
{
    $user = requireUser($db);
    $cid = (int)($params['commentId'] ?? $params['id'] ?? 0);
    if (!$cid) throw new Exception('Missing commentId', 400);
    $ins = getStatement("INSERT IGNORE INTO commentLikes (commentId, userId) VALUES (:c, :u)");
    $ins->execute([':c' => $cid, ':u' => $user['userId']]);
    if ($ins->rowCount() > 0) {
        getStatement("UPDATE comments SET likeCount = likeCount + 1 WHERE commentId = :c")->execute([':c' => $cid]);
    }
    return ['success' => true, 'liked' => true];
}

function handleCommentUnlike(PDO $db, array $params): array
{
    $user = requireUser($db);
    $cid = (int)($params['commentId'] ?? $params['id'] ?? 0);
    if (!$cid) throw new Exception('Missing commentId', 400);
    $del = getStatement("DELETE FROM commentLikes WHERE commentId = :c AND userId = :u");
    $del->execute([':c' => $cid, ':u' => $user['userId']]);
    if ($del->rowCount() > 0) {
        getStatement("UPDATE comments SET likeCount = GREATEST(likeCount - 1, 0) WHERE commentId = :c")->execute([':c' => $cid]);
    }
    return ['success' => true, 'liked' => false];
}

/* ═══════════════ PLAYLISTS ═══════════════ */

function canEditPlaylist(array $playlist, ?array $user): bool
{
    if (!$user) return false;
    return (int)$playlist['userId'] === (int)($user['userId'] ?? 0)
        || in_array($user['role'] ?? 'user', ['admin','moderator'], true);
}

function handlePlaylistCreate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $name = trim((string)($params['name'] ?? ''));
    if ($name === '') throw new Exception('Playlist name required', 400);
    if (mb_strlen($name) > 255) throw new Exception('Name too long', 400);
    $playlistId = 'pl_' . generateId(12);
    $desc  = isset($params['description']) ? (string)$params['description'] : null;
    $cover = isset($params['coverUrl']) ? (string)$params['coverUrl'] : null;
    $isPublic = isset($params['isPublic']) ? (int)(bool)$params['isPublic'] : 1;
    $isCollab = isset($params['isCollaborative']) ? (int)(bool)$params['isCollaborative'] : 0;

    getStatement("INSERT INTO playlists (playlistId, userId, name, description, coverUrl, isPublic, isCollaborative)
                  VALUES (:pid, :u, :n, :d, :c, :p, :k)")
        ->execute([':pid' => $playlistId, ':u' => $user['userId'], ':n' => $name,
                   ':d' => $desc, ':c' => $cover, ':p' => $isPublic, ':k' => $isCollab]);
    getStatement("UPDATE users SET playlistCount = playlistCount + 1 WHERE userId = :u")->execute([':u' => $user['userId']]);
    addUrlToSitemap($db, 'playlist', $playlistId);

    $s = getStatement("SELECT * FROM playlists WHERE playlistId = :id");
    $s->execute([':id' => $playlistId]);
    return ['success' => true, 'playlist' => $s->fetch()];
}

function handlePlaylistGet(PDO $db, array $params): array
{
    $pid = (string)($params['playlistId'] ?? $params['id'] ?? '');
    if ($pid === '') throw new Exception('Missing playlistId', 400);
    $s = getStatement("SELECT p.*, u.username, u.displayName, u.avatarUrl, u.isVerified
                       FROM playlists p INNER JOIN users u ON u.userId = p.userId
                       WHERE p.playlistId = :id");
    $s->execute([':id' => $pid]);
    $pl = $s->fetch();
    if (!$pl) return ['success' => false, 'error' => 'Playlist not found'];
    $viewer = $GLOBALS['_ctx']['user'] ?? null;
    if (!$pl['isPublic'] && (!canEditPlaylist($pl, $viewer))) {
        return ['success' => false, 'error' => 'Forbidden: private playlist'];
    }
    $pl['isOwner'] = $viewer && (int)$viewer['userId'] === (int)$pl['userId'];
    return ['success' => true, 'playlist' => $pl];
}

function handlePlaylistUpdate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $pid = (string)($params['playlistId'] ?? $params['id'] ?? '');
    if ($pid === '') throw new Exception('Missing playlistId', 400);
    $s = getStatement("SELECT * FROM playlists WHERE playlistId = :id");
    $s->execute([':id' => $pid]);
    $pl = $s->fetch();
    if (!$pl) throw new Exception('Playlist not found', 404);
    if (!canEditPlaylist($pl, $user)) throw new Exception('Forbidden', 403);
    $updates = []; $bind = [];
    foreach (['name', 'description', 'coverUrl'] as $f) {
        if (array_key_exists($f, $params)) { $updates[] = "`$f` = ?"; $bind[] = $params[$f]; }
    }
    foreach (['isPublic', 'isCollaborative'] as $f) {
        if (array_key_exists($f, $params)) { $updates[] = "`$f` = ?"; $bind[] = (int)(bool)$params[$f]; }
    }
    if (empty($updates)) throw new Exception('Nothing to update', 400);
    $bind[] = $pid;
    $db->prepare("UPDATE playlists SET " . implode(', ', $updates) . " WHERE playlistId = ?")->execute($bind);
    return ['success' => true, 'message' => 'Playlist updated'];
}

function handlePlaylistDelete(PDO $db, array $params): array
{
    $user = requireUser($db);
    $pid = (string)($params['playlistId'] ?? $params['id'] ?? '');
    if ($pid === '') throw new Exception('Missing playlistId', 400);
    $s = getStatement("SELECT * FROM playlists WHERE playlistId = :id");
    $s->execute([':id' => $pid]);
    $pl = $s->fetch();
    if (!$pl) throw new Exception('Playlist not found', 404);
    if (!canEditPlaylist($pl, $user)) throw new Exception('Forbidden', 403);
    $db->beginTransaction();
    try {
        getStatement("DELETE FROM playlistTracks WHERE playlistId = :id")->execute([':id' => $pid]);
        getStatement("DELETE FROM playlistLikes WHERE playlistId = :id")->execute([':id' => $pid]);
        getStatement("DELETE FROM playlists WHERE playlistId = :id")->execute([':id' => $pid]);
        getStatement("UPDATE users SET playlistCount = GREATEST(playlistCount - 1, 0) WHERE userId = :u")->execute([':u' => $pl['userId']]);
        $db->commit();
    } catch (Throwable $e) { $db->rollBack(); throw $e; }
    return ['success' => true, 'message' => 'Playlist deleted'];
}

function handlePlaylistAddTrack(PDO $db, array $params): array
{
    $user = requireUser($db);
    $pid = (string)($params['playlistId'] ?? $params['id'] ?? '');
    $trackId = (string)($params['trackId'] ?? '');
    if ($pid === '' || $trackId === '') throw new Exception('Missing playlistId or trackId', 400);
    $s = getStatement("SELECT * FROM playlists WHERE playlistId = :id");
    $s->execute([':id' => $pid]);
    $pl = $s->fetch();
    if (!$pl) throw new Exception('Playlist not found', 404);
    if (!canEditPlaylist($pl, $user)) throw new Exception('Forbidden', 403);
    $countStmt = getStatement("SELECT COUNT(*) FROM playlistTracks WHERE playlistId = :p");
    $countStmt->execute([':p' => $pid]);
    if ((int)$countStmt->fetchColumn() >= PLAYLIST_MAX_TRACKS) throw new Exception('Playlist is full', 400);

    $posStmt = getStatement("SELECT COALESCE(MAX(position), -1) + 1 FROM playlistTracks WHERE playlistId = :p");
    $posStmt->execute([':p' => $pid]);
    $nextPos = (int)$posStmt->fetchColumn();

    $ins = getStatement("INSERT IGNORE INTO playlistTracks (playlistId, trackId, position, addedBy)
                         VALUES (:p, :t, :pos, :u)");
    $ins->execute([':p' => $pid, ':t' => $trackId, ':pos' => $nextPos, ':u' => $user['userId']]);
    if ($ins->rowCount() === 0) return ['success' => true, 'alreadyPresent' => true];
    getStatement("UPDATE playlists SET trackCount = trackCount + 1 WHERE playlistId = :p")->execute([':p' => $pid]);
    return ['success' => true, 'message' => 'Track added', 'position' => $nextPos];
}

function handlePlaylistRemoveTrack(PDO $db, array $params): array
{
    $user = requireUser($db);
    $pid = (string)($params['playlistId'] ?? $params['id'] ?? '');
    $trackId = (string)($params['trackId'] ?? '');
    if ($pid === '' || $trackId === '') throw new Exception('Missing playlistId or trackId', 400);
    $s = getStatement("SELECT * FROM playlists WHERE playlistId = :id");
    $s->execute([':id' => $pid]);
    $pl = $s->fetch();
    if (!$pl) throw new Exception('Playlist not found', 404);
    if (!canEditPlaylist($pl, $user)) throw new Exception('Forbidden', 403);
    $del = getStatement("DELETE FROM playlistTracks WHERE playlistId = :p AND trackId = :t");
    $del->execute([':p' => $pid, ':t' => $trackId]);
    if ($del->rowCount() > 0) {
        getStatement("UPDATE playlists SET trackCount = GREATEST(trackCount - 1, 0) WHERE playlistId = :p")->execute([':p' => $pid]);
    }
    return ['success' => true, 'removed' => $del->rowCount()];
}

function handlePlaylistReorder(PDO $db, array $params): array
{
    $user = requireUser($db);
    $pid = (string)($params['playlistId'] ?? $params['id'] ?? '');
    $order = $params['order'] ?? [];
    if ($pid === '' || !is_array($order)) throw new Exception('Missing playlistId or order array', 400);
    $s = getStatement("SELECT * FROM playlists WHERE playlistId = :id");
    $s->execute([':id' => $pid]);
    $pl = $s->fetch();
    if (!$pl) throw new Exception('Playlist not found', 404);
    if (!canEditPlaylist($pl, $user)) throw new Exception('Forbidden', 403);
    $db->beginTransaction();
    try {
        $stmt = getStatement("UPDATE playlistTracks SET position = :pos WHERE playlistId = :p AND trackId = :t");
        foreach ($order as $idx => $tid) {
            $stmt->execute([':pos' => (int)$idx, ':p' => $pid, ':t' => (string)$tid]);
        }
        $db->commit();
    } catch (Throwable $e) { $db->rollBack(); throw $e; }
    return ['success' => true, 'message' => 'Reordered'];
}

function handlePlaylistTracks(PDO $db, array $params): array
{
    $pid = (string)($params['playlistId'] ?? $params['id'] ?? '');
    if ($pid === '') throw new Exception('Missing playlistId', 400);
    $s = getStatement("SELECT * FROM playlists WHERE playlistId = :id");
    $s->execute([':id' => $pid]);
    $pl = $s->fetch();
    if (!$pl) throw new Exception('Playlist not found', 404);
    $viewer = $GLOBALS['_ctx']['user'] ?? null;
    if (!$pl['isPublic'] && !canEditPlaylist($pl, $viewer)) throw new Exception('Forbidden: private playlist', 403);
    $limit = min(max((int)($params['limit'] ?? 200), 1), 1000);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $quality = $params['quality'] ?? null;
    $platform = $params['platform'] ?? null;
    $stmt = getStatement("SELECT pt.trackId, pt.position, pt.addedAt, pt.addedBy
                          FROM playlistTracks pt
                          WHERE pt.playlistId = :p
                          ORDER BY pt.position ASC LIMIT :l OFFSET :o");
    $stmt->bindValue(':p', $pid);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o', $offset, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();
    $trackIds = array_column($rows, 'trackId');
    $trackMap = [];
    if (!empty($trackIds)) {
        $map = fetchEntitiesByIdsMap(['track' => $trackIds]);
        $trackRows = array_values(array_map(function($r){ $r['wrapperType'] = 'track'; return $r; }, $map));
        attachAttachmentsBatch($trackRows, $quality, $platform);
        foreach ($trackRows as $t) $trackMap['track:' . $t['trackId']] = $t;
    }
    $items = [];
    foreach ($rows as $r) {
        $t = $trackMap['track:' . $r['trackId']] ?? ['trackId' => $r['trackId']];
        $t['position'] = (int)$r['position'];
        $t['addedAt']  = $r['addedAt'];
        $items[] = $t;
    }
    return ['success' => true, 'playlistId' => $pid, 'count' => count($items), 'tracks' => $items];
}

function handleMyPlaylists(PDO $db, array $params): array
{
    $user = requireUser($db);
    $limit = min(max((int)($params['limit'] ?? 50), 1), 200);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $stmt = getStatement("SELECT * FROM playlists WHERE userId = :u ORDER BY updatedAt DESC LIMIT :l OFFSET :o");
    $stmt->bindValue(':u', $user['userId'], PDO::PARAM_INT);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o', $offset, PDO::PARAM_INT);
    $stmt->execute();
    return ['success' => true, 'playlists' => $stmt->fetchAll()];
}

function handleUserPlaylists(PDO $db, array $params): array
{
    $target = (int)($params['userId'] ?? $params['id'] ?? 0);
    if (!$target) throw new Exception('Missing userId', 400);
    $viewer = $GLOBALS['_ctx']['user'] ?? null;
    $isSelf = $viewer && (int)$viewer['userId'] === $target;
    $limit = min(max((int)($params['limit'] ?? 50), 1), 200);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $sql = "SELECT * FROM playlists WHERE userId = :u";
    if (!$isSelf) $sql .= " AND isPublic = 1";
    $sql .= " ORDER BY updatedAt DESC LIMIT :l OFFSET :o";
    $stmt = getStatement($sql);
    $stmt->bindValue(':u', $target, PDO::PARAM_INT);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o', $offset, PDO::PARAM_INT);
    $stmt->execute();
    return ['success' => true, 'playlists' => $stmt->fetchAll()];
}

function handlePlaylistLike(PDO $db, array $params): array  { return handleLike($db, array_merge($params, ['entityType' => 'playlist'])); }
function handlePlaylistUnlike(PDO $db, array $params): array { return handleUnlike($db, array_merge($params, ['entityType' => 'playlist'])); }

/* ═══════════════ LIBRARY / HISTORY ═══════════════ */

function handleLibrarySave(PDO $db, array $params): array
{
    $user = requireUser($db);
    $entityType = strtolower((string)($params['entityType'] ?? $params['type'] ?? ''));
    $entityId   = (string)($params['entityId'] ?? $params['id'] ?? '');
    if (!in_array($entityType, ['track', 'collection', 'artist', 'playlist'], true)) throw new Exception('Invalid entityType', 400);
    if ($entityId === '') throw new Exception('Missing entityId', 400);
    $ins = getStatement("INSERT IGNORE INTO userLibrary (userId, entityType, entityId) VALUES (:u, :t, :e)");
    $ins->execute([':u' => $user['userId'], ':t' => $entityType, ':e' => $entityId]);
    return ['success' => true, 'saved' => true];
}

function handleLibraryRemove(PDO $db, array $params): array
{
    $user = requireUser($db);
    $entityType = strtolower((string)($params['entityType'] ?? $params['type'] ?? ''));
    $entityId   = (string)($params['entityId'] ?? $params['id'] ?? '');
    if ($entityType === '' || $entityId === '') throw new Exception('Missing entityType/entityId', 400);
    $del = getStatement("DELETE FROM userLibrary WHERE userId = :u AND entityType = :t AND entityId = :e");
    $del->execute([':u' => $user['userId'], ':t' => $entityType, ':e' => $entityId]);
    return ['success' => true, 'removed' => $del->rowCount()];
}

function handleLibraryList(PDO $db, array $params): array
{
    $user = requireUser($db);
    $entityType = isset($params['entityType']) ? strtolower((string)$params['entityType']) : null;
    $limit = min(max((int)($params['limit'] ?? 100), 1), 500);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $sql = "SELECT entityType, entityId, addedAt FROM userLibrary WHERE userId = :u";
    if ($entityType) $sql .= " AND entityType = :t";
    $sql .= " ORDER BY addedAt DESC LIMIT :l OFFSET :o";
    $stmt = getStatement($sql);
    $stmt->bindValue(':u', $user['userId'], PDO::PARAM_INT);
    if ($entityType) $stmt->bindValue(':t', $entityType);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o', $offset, PDO::PARAM_INT);
    $stmt->execute();
    return ['success' => true, 'items' => $stmt->fetchAll()];
}

function handleHistoryRecord(PDO $db, array $params): array
{
    $trackId = (string)($params['trackId'] ?? $params['id'] ?? '');
    if ($trackId === '') throw new Exception('Missing trackId', 400);
    $user = $GLOBALS['_ctx']['user'] ?? null;
    $userId = $user['userId'] ?? null;
    $duration = (int)($params['duration'] ?? 0);
    getStatement("INSERT INTO playHistory (userId, trackId, duration) VALUES (:u, :t, :d)")
        ->execute([':u' => $userId, ':t' => $trackId, ':d' => $duration]);
    return ['success' => true, 'recorded' => true];
}

function handleHistoryList(PDO $db, array $params): array
{
    $user = requireUser($db);
    $limit = min(max((int)($params['limit'] ?? 50), 1), 500);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $stmt = getStatement("SELECT trackId, duration, playedAt FROM playHistory
                          WHERE userId = :u ORDER BY id DESC LIMIT :l OFFSET :o");
    $stmt->bindValue(':u', $user['userId'], PDO::PARAM_INT);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o', $offset, PDO::PARAM_INT);
    $stmt->execute();
    return ['success' => true, 'history' => $stmt->fetchAll()];
}

function handleHistoryClear(PDO $db): array
{
    $user = requireUser($db);
    getStatement("DELETE FROM playHistory WHERE userId = :u")->execute([':u' => $user['userId']]);
    return ['success' => true, 'message' => 'History cleared'];
}

function handleFollowArtist(PDO $db, array $params): array
{
    $user = requireUser($db);
    $artistId = (string)($params['artistId'] ?? $params['id'] ?? '');
    if ($artistId === '') throw new Exception('Missing artistId', 400);
    $ins = getStatement("INSERT IGNORE INTO userFollowedArtists (userId, artistId) VALUES (:u, :a)");
    $ins->execute([':u' => $user['userId'], ':a' => $artistId]);
    return ['success' => true, 'following' => true];
}

function handleUnfollowArtist(PDO $db, array $params): array
{
    $user = requireUser($db);
    $artistId = (string)($params['artistId'] ?? $params['id'] ?? '');
    if ($artistId === '') throw new Exception('Missing artistId', 400);
    getStatement("DELETE FROM userFollowedArtists WHERE userId = :u AND artistId = :a")
        ->execute([':u' => $user['userId'], ':a' => $artistId]);
    return ['success' => true, 'following' => false];
}

function handleMyFollowedArtists(PDO $db): array
{
    $user = requireUser($db);
    $stmt = getStatement("SELECT artistId, createdAt FROM userFollowedArtists WHERE userId = :u ORDER BY createdAt DESC");
    $stmt->execute([':u' => $user['userId']]);
    return ['success' => true, 'artists' => $stmt->fetchAll()];
}

/* ═══════════════ NOTIFICATIONS ═══════════════ */

function createNotification(PDO $db, int $userId, ?int $actorId, string $type, ?string $entityType, $entityId, string $message): void
{
    try {
        getStatement("INSERT INTO notifications (userId, actorId, type, entityType, entityId, message)
                      VALUES (:u, :a, :t, :et, :e, :m)")
            ->execute([':u' => $userId, ':a' => $actorId, ':t' => $type, ':et' => $entityType, ':e' => (string)$entityId, ':m' => $message]);
    } catch (Throwable $e) { error_log('createNotification failed: ' . $e->getMessage()); }
}

function handleNotificationsList(PDO $db, array $params): array
{
    $user = requireUser($db);
    $limit = min(max((int)($params['limit'] ?? 50), 1), 200);
    $offset = max((int)($params['offset'] ?? 0), 0);
    $onlyUnread = filter_var($params['unread'] ?? false, FILTER_VALIDATE_BOOL);
    $sql = "SELECT n.*, u.username AS actorUsername, u.displayName AS actorDisplayName, u.avatarUrl AS actorAvatar
            FROM notifications n LEFT JOIN users u ON u.userId = n.actorId
            WHERE n.userId = :u";
    if ($onlyUnread) $sql .= " AND n.isRead = 0";
    $sql .= " ORDER BY n.id DESC LIMIT :l OFFSET :o";
    $stmt = getStatement($sql);
    $stmt->bindValue(':u', $user['userId'], PDO::PARAM_INT);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':o', $offset, PDO::PARAM_INT);
    $stmt->execute();
    return ['success' => true, 'notifications' => $stmt->fetchAll()];
}

function handleNotificationsCount(PDO $db): array
{
    $user = requireUser($db);
    $s = getStatement("SELECT COUNT(*) FROM notifications WHERE userId = :u AND isRead = 0");
    $s->execute([':u' => $user['userId']]);
    return ['success' => true, 'unread' => (int)$s->fetchColumn()];
}

function handleNotificationsRead(PDO $db, array $params): array
{
    $user = requireUser($db);
    if (!empty($params['notificationId'])) {
        getStatement("UPDATE notifications SET isRead = 1 WHERE userId = :u AND notificationId = :id")
            ->execute([':u' => $user['userId'], ':id' => (int)$params['notificationId']]);
    } elseif (!empty($params['ids']) && is_array($params['ids'])) {
        $ph = implode(',', array_fill(0, count($params['ids']), '?'));
        $stmt = $db->prepare("UPDATE notifications SET isRead = 1 WHERE userId = ? AND notificationId IN ($ph)");
        $stmt->execute(array_merge([$user['userId']], array_map('intval', $params['ids'])));
    } else {
        getStatement("UPDATE notifications SET isRead = 1 WHERE userId = :u")->execute([':u' => $user['userId']]);
    }
    return ['success' => true, 'message' => 'Notifications marked read'];
}

function handleNotificationsDelete(PDO $db, array $params): array
{
    $user = requireUser($db);
    $id = (int)($params['notificationId'] ?? $params['id'] ?? 0);
    if ($id) {
        getStatement("DELETE FROM notifications WHERE userId = :u AND notificationId = :id")
            ->execute([':u' => $user['userId'], ':id' => $id]);
    } else {
        getStatement("DELETE FROM notifications WHERE userId = :u")->execute([':u' => $user['userId']]);
    }
    return ['success' => true, 'message' => 'Notifications deleted'];
}

/* ═══════════════ API APPS & TOKENS ═══════════════ */

function handleAppCreate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $name = trim((string)($params['name'] ?? ''));
    if ($name === '') throw new Exception('App name required', 400);
    if (mb_strlen($name) > 128) throw new Exception('Name too long', 400);

    $appId = 'app_' . generateId(10);
    $secret = generateToken();
    $settings = isset($params['settings']) && is_array($params['settings']) ? jsonEncode($params['settings']) : null;
    $redirectUris = isset($params['redirectUris']) ? (is_array($params['redirectUris']) ? implode("\n", $params['redirectUris']) : (string)$params['redirectUris']) : null;
    $website = isset($params['websiteUrl']) ? (string)$params['websiteUrl'] : null;

    getStatement("INSERT INTO apiApps (appId, userId, name, description, clientSecret, redirectUris, websiteUrl, settings)
                  VALUES (:a, :u, :n, :d, :s, :r, :w, :st)")
        ->execute([
            ':a' => $appId, ':u' => $user['userId'], ':n' => $name,
            ':d' => $params['description'] ?? null, ':s' => $secret,
            ':r' => $redirectUris, ':w' => $website, ':st' => $settings,
        ]);
    return [
        'success' => true,
        'app' => [
            'appId' => $appId, 'userId' => $user['userId'], 'name' => $name,
            'clientSecret' => $secret, 'redirectUris' => $redirectUris,
            'websiteUrl' => $website, 'settings' => $settings,
            'createdAt' => date('c'),
        ],
    ];
}

function handleAppsList(PDO $db, array $params): array
{
    $user = requireUser($db);
    $stmt = getStatement("SELECT appId, userId, name, description, redirectUris, websiteUrl, settings, isActive, requestCount, createdAt
                          FROM apiApps WHERE userId = :u ORDER BY createdAt DESC");
    $stmt->execute([':u' => $user['userId']]);
    return ['success' => true, 'apps' => $stmt->fetchAll()];
}

function handleAppGet(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = (string)($params['appId'] ?? $params['id'] ?? '');
    if ($appId === '') throw new Exception('Missing appId', 400);
    $stmt = getStatement("SELECT * FROM apiApps WHERE appId = :a AND userId = :u");
    $stmt->execute([':a' => $appId, ':u' => $user['userId']]);
    $app = $stmt->fetch();
    if (!$app) return ['success' => false, 'error' => 'App not found'];
    return ['success' => true, 'app' => $app];
}

function handleAppUpdate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = (string)($params['appId'] ?? $params['id'] ?? '');
    if ($appId === '') throw new Exception('Missing appId', 400);
    $s = getStatement("SELECT * FROM apiApps WHERE appId = :a AND userId = :u");
    $s->execute([':a' => $appId, ':u' => $user['userId']]);
    if (!$s->fetch()) throw new Exception('App not found', 404);
    $updates = []; $bind = [];
    foreach (['name', 'description', 'websiteUrl'] as $f) {
        if (array_key_exists($f, $params)) { $updates[] = "`$f` = ?"; $bind[] = $params[$f]; }
    }
    if (array_key_exists('redirectUris', $params)) {
        $updates[] = "`redirectUris` = ?";
        $bind[] = is_array($params['redirectUris']) ? implode("\n", $params['redirectUris']) : (string)$params['redirectUris'];
    }
    if (array_key_exists('settings', $params)) {
        $updates[] = "`settings` = ?";
        $bind[] = is_array($params['settings']) ? jsonEncode($params['settings']) : (string)$params['settings'];
    }
    if (array_key_exists('isActive', $params)) { $updates[] = "`isActive` = ?"; $bind[] = (int)(bool)$params['isActive']; }
    if (array_key_exists('rotateSecret', $params) && $params['rotateSecret']) {
        $updates[] = "`clientSecret` = ?"; $bind[] = generateToken();
    }
    if (empty($updates)) throw new Exception('Nothing to update', 400);
    $bind[] = $appId;
    $db->prepare("UPDATE apiApps SET " . implode(', ', $updates) . " WHERE appId = ?")->execute($bind);
    return ['success' => true, 'message' => 'App updated'];
}

function handleAppDelete(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = (string)($params['appId'] ?? $params['id'] ?? '');
    if ($appId === '') throw new Exception('Missing appId', 400);
    $s = getStatement("SELECT appId FROM apiApps WHERE appId = :a AND userId = :u");
    $s->execute([':a' => $appId, ':u' => $user['userId']]);
    if (!$s->fetch()) throw new Exception('App not found', 404);
    getStatement("DELETE FROM apiApps WHERE appId = :a")->execute([':a' => $appId]);
    getStatement("UPDATE apiTokens SET isActive = 0 WHERE appId = :a")->execute([':a' => $appId]);
    getStatement("DELETE FROM webhooks WHERE appId = :a")->execute([':a' => $appId]);
    return ['success' => true, 'message' => 'App deleted'];
}

function handleTokenCreate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = isset($params['appId']) ? (string)$params['appId'] : null;
    if ($appId) {
        $s = getStatement("SELECT appId FROM apiApps WHERE appId = :a AND userId = :u");
        $s->execute([':a' => $appId, ':u' => $user['userId']]);
        if (!$s->fetch()) throw new Exception('App not found or not owned', 404);
    }
    $name   = isset($params['name']) ? trim((string)$params['name']) : 'Default token';
    $scopes = isset($params['scopes']) ? (is_array($params['scopes']) ? implode(',', $params['scopes']) : (string)$params['scopes']) : '*';
    $ttlDays = isset($params['ttlDays']) ? max(1, (int)$params['ttlDays']) : (int)(API_TOKEN_DEFAULT_TTL / 86400);
    $token  = generateToken();
    $tokenId = 'tok_' . generateId(10);
    $hash   = hashToken($token);
    $prefix = substr($token, 0, 10);
    $expiresAt = $ttlDays > 0 ? date('Y-m-d H:i:s', time() + $ttlDays * 86400) : null;

    getStatement("INSERT INTO apiTokens (tokenId, tokenHash, tokenPrefix, appId, userId, name, scopes, expiresAt)
                  VALUES (:tid, :th, :tp, :a, :u, :n, :s, :e)")
        ->execute([
            ':tid' => $tokenId, ':th' => $hash, ':tp' => $prefix,
            ':a' => $appId, ':u' => $user['userId'], ':n' => $name,
            ':s' => $scopes, ':e' => $expiresAt,
        ]);
    return [
        'success' => true,
        'token' => [
            'tokenId' => $tokenId, 'token' => $token, 'tokenPrefix' => $prefix,
            'name' => $name, 'scopes' => $scopes, 'appId' => $appId,
            'expiresAt' => $expiresAt,
        ],
        'warning' => 'Save this token now — it will NOT be shown again.',
    ];
}

function handleTokensList(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = isset($params['appId']) ? (string)$params['appId'] : null;
    $sql = "SELECT tokenId, tokenPrefix, appId, name, scopes, isActive, expiresAt, lastUsedAt, requestCount, createdAt
            FROM apiTokens WHERE userId = :u";
    if ($appId) $sql .= " AND appId = :a";
    $sql .= " ORDER BY createdAt DESC";
    $stmt = getStatement($sql);
    $stmt->bindValue(':u', $user['userId'], PDO::PARAM_INT);
    if ($appId) $stmt->bindValue(':a', $appId);
    $stmt->execute();
    return ['success' => true, 'tokens' => $stmt->fetchAll()];
}

function handleTokenRevoke(PDO $db, array $params): array
{
    $user = requireUser($db);
    $tokenId = (string)($params['tokenId'] ?? $params['id'] ?? '');
    if ($tokenId === '') throw new Exception('Missing tokenId', 400);
    $stmt = getStatement("UPDATE apiTokens SET isActive = 0 WHERE tokenId = :tid AND userId = :u");
    $stmt->execute([':tid' => $tokenId, ':u' => $user['userId']]);
    if ($stmt->rowCount() === 0) throw new Exception('Token not found', 404);
    return ['success' => true, 'message' => 'Token revoked'];
}

function handleTokenRotate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $tokenId = (string)($params['tokenId'] ?? $params['id'] ?? '');
    if ($tokenId === '') throw new Exception('Missing tokenId', 400);
    $s = getStatement("SELECT * FROM apiTokens WHERE tokenId = :tid AND userId = :u");
    $s->execute([':tid' => $tokenId, ':u' => $user['userId']]);
    $tok = $s->fetch();
    if (!$tok) throw new Exception('Token not found', 404);
    $new = generateToken();
    $nh  = hashToken($new);
    getStatement("UPDATE apiTokens SET tokenHash = :th, tokenPrefix = :tp WHERE tokenId = :tid")
        ->execute([':th' => $nh, ':tp' => substr($new, 0, 10), ':tid' => $tokenId]);
    return ['success' => true, 'token' => ['tokenId' => $tokenId, 'token' => $new, 'tokenPrefix' => substr($new, 0, 10)], 'warning' => 'Save this token now — it will NOT be shown again.'];
}

function handleAppLogs(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = (string)($params['appId'] ?? $params['id'] ?? '');
    if ($appId === '') throw new Exception('Missing appId', 400);
    $s = getStatement("SELECT appId FROM apiApps WHERE appId = :a AND userId = :u");
    $s->execute([':a' => $appId, ':u' => $user['userId']]);
    if (!$s->fetch()) throw new Exception('App not found', 404);
    $limit = min(max((int)($params['limit'] ?? 100), 1), 500);
    $stmt = getStatement("SELECT endpoint, method, statusCode, responseTime, ip, createdAt
                          FROM apiRequestLog WHERE appId = :a ORDER BY id DESC LIMIT :l");
    $stmt->bindValue(':a', $appId);
    $stmt->bindValue(':l', $limit, PDO::PARAM_INT);
    $stmt->execute();
    return ['success' => true, 'logs' => $stmt->fetchAll()];
}

function handleAppStats(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = (string)($params['appId'] ?? $params['id'] ?? '');
    if ($appId === '') throw new Exception('Missing appId', 400);
    $s = getStatement("SELECT appId FROM apiApps WHERE appId = :a AND userId = :u");
    $s->execute([':a' => $appId, ':u' => $user['userId']]);
    if (!$s->fetch()) throw new Exception('App not found', 404);
    $total = (int)$db->query("SELECT COUNT(*) FROM apiRequestLog WHERE appId = " . $db->quote($appId))->fetchColumn();
    $today = (int)$db->query("SELECT COUNT(*) FROM apiRequestLog WHERE appId = " . $db->quote($appId) . " AND createdAt >= CURDATE()")->fetchColumn();
    $errors = (int)$db->query("SELECT COUNT(*) FROM apiRequestLog WHERE appId = " . $db->quote($appId) . " AND statusCode >= 400")->fetchColumn();
    $tokens = (int)$db->query("SELECT COUNT(*) FROM apiTokens WHERE appId = " . $db->quote($appId) . " AND isActive = 1")->fetchColumn();
    return ['success' => true, 'stats' => ['totalRequests' => $total, 'todayRequests' => $today, 'errorRequests' => $errors, 'activeTokens' => $tokens]];
}

/* ═══════════════ WEBHOOKS ═══════════════ */

function handleWebhookCreate(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = (string)($params['appId'] ?? '');
    $url   = trim((string)($params['url'] ?? ''));
    $events = $params['events'] ?? ['*'];
    if ($appId === '' || $url === '') throw new Exception('Missing appId or url', 400);
    if (!filter_var($url, FILTER_VALIDATE_URL)) throw new Exception('Invalid URL', 400);
    if (!is_array($events)) $events = [$events];
    $s = getStatement("SELECT appId FROM apiApps WHERE appId = :a AND userId = :u");
    $s->execute([':a' => $appId, ':u' => $user['userId']]);
    if (!$s->fetch()) throw new Exception('App not found', 404);
    $wid = 'wh_' . generateId(10);
    $secret = generateToken();
    getStatement("INSERT INTO webhooks (webhookId, appId, url, events, secret) VALUES (:w, :a, :u, :e, :s)")
        ->execute([':w' => $wid, ':a' => $appId, ':u' => $url, ':e' => implode(',', $events), ':s' => $secret]);
    return ['success' => true, 'webhook' => ['webhookId' => $wid, 'url' => $url, 'events' => $events, 'secret' => $secret]];
}

function handleWebhooksList(PDO $db, array $params): array
{
    $user = requireUser($db);
    $appId = (string)($params['appId'] ?? '');
    if ($appId === '') throw new Exception('Missing appId', 400);
    $s = getStatement("SELECT appId FROM apiApps WHERE appId = :a AND userId = :u");
    $s->execute([':a' => $appId, ':u' => $user['userId']]);
    if (!$s->fetch()) throw new Exception('App not found', 404);
    $stmt = getStatement("SELECT webhookId, appId, url, events, isActive, lastTriggeredAt, failCount, createdAt
                          FROM webhooks WHERE appId = :a ORDER BY createdAt DESC");
    $stmt->execute([':a' => $appId]);
    $rows = $stmt->fetchAll();
    foreach ($rows as &$r) { $r['events'] = $r['events'] ? explode(',', $r['events']) : []; }
    unset($r);
    return ['success' => true, 'webhooks' => $rows];
}

function handleWebhookDelete(PDO $db, array $params): array
{
    $user = requireUser($db);
    $wid = (string)($params['webhookId'] ?? $params['id'] ?? '');
    if ($wid === '') throw new Exception('Missing webhookId', 400);
    $s = getStatement("SELECT w.webhookId FROM webhooks w INNER JOIN apiApps a ON a.appId = w.appId
                       WHERE w.webhookId = :w AND a.userId = :u");
    $s->execute([':w' => $wid, ':u' => $user['userId']]);
    if (!$s->fetch()) throw new Exception('Webhook not found', 404);
    getStatement("DELETE FROM webhooks WHERE webhookId = :w")->execute([':w' => $wid]);
    return ['success' => true, 'message' => 'Webhook deleted'];
}

/* ═══════════════ HTTP ═══════════════ */

function enableCompression(): void
{
    if (ENABLE_GZIP && !headers_sent() && extension_loaded('zlib') && strpos($_SERVER['HTTP_ACCEPT_ENCODING'] ?? '', 'gzip') !== false) {
        ini_set('zlib.output_compression', 'On');
        ini_set('zlib.output_compression_level', '6');
    }
}

function respond($data, $status = 200): void
{
    if (is_string($status) && ctype_digit($status)) $status = (int)$status;
    if (!is_int($status) || $status < 100 || $status > 599) $status = 500;
    if (!headers_sent()) {
        http_response_code($status);
        header('Content-Type: application/json; charset=utf-8');
        header('Access-Control-Allow-Origin: *');
        header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
        header('Access-Control-Allow-Headers: Content-Type, Quality, Platform, Authorization, X-Session-Id, X-Visitor-Id, X-Session-Token, X-Api-Token, X-Api-Key');
    }
    echo json_encode($data, JSON_UNESCAPED_SLASHES);
    exit;
}

function respondXml(string $xml, int $status = 200): void
{
    if (!headers_sent()) {
        http_response_code($status);
        header('Content-Type: application/xml; charset=utf-8');
        header('Access-Control-Allow-Origin: *');
        header('Cache-Control: public, max-age=3600');
    }
    echo $xml;
    exit;
}

/* ═══════════════ CLEANUP ═══════════════ */

function closeDatabaseConnection(): void
{
    global $db, $statements;
    foreach ($statements as $stmt) { try { $stmt->closeCursor(); } catch (Throwable $e) {} }
    $statements = []; $db = null;
}

function closeSQLiteConnection(): void
{
    global $sqliteDb, $sqliteStatements;
    foreach ($sqliteStatements as $stmt) { try { $stmt->closeCursor(); } catch (Throwable $e) {} }
    $sqliteStatements = []; $sqliteDb = null;
}

function handleLyricsGet(PDO $db, string $trackId): array
{
    $lyricsResult = getLyrics($db, $trackId);
    if ($lyricsResult['success']) return $lyricsResult;
    $cached = getExternalCache($db, 'lrclib', $trackId);
    if ($cached !== null) {
        if ($cached['response'] === null) return ['success' => false, 'error' => 'Lyrics not found (cached)'];
        $data = $cached['response'];
        saveLyrics($db, $trackId, $data['data'], $data['type'] ?? 'unsynced', $data['source'] ?? 'lrclib');
        return getLyrics($db, $trackId);
    }
    $track = fetchEntityById($db, 'track', $trackId);
    if (!$track || empty($track['trackName']) || empty($track['artistName'])) return ['success' => false, 'error' => 'Track metadata missing'];
    $fetched = fetchLyricsFromLrclib($track['trackName'], $track['artistName'], $track['collectionName'] ?? null);
    if ($fetched) {
        saveLyrics($db, $trackId, $fetched['data'], $fetched['type'], $fetched['source']);
        setExternalCache($db, 'lrclib', $trackId, $fetched, 86400 * 7);
        return getLyrics($db, $trackId);
    }
    setExternalCache($db, 'lrclib', $trackId, null, 86400 * 7);
    return ['success' => false, 'error' => 'Lyrics not found (cached)'];
}

/* ═══════════════ ROUTING TABLE ═══════════════ */

function getRouteTable(): array
{
    return [
        'POST /auth/signup'      => ['handler' => 'handleSignup',          'auth' => false],
        'POST /auth/login'       => ['handler' => 'handleLogin',           'auth' => false],
        'POST /auth/register'    => ['handler' => 'handleSignup',          'auth' => false],
        'GET /auth/check-username' => ['handler' => 'handleCheckUsername','auth' => false],
        'POST /auth/check-username' => ['handler' => 'handleCheckUsername','auth' => false],

        'POST /auth/logout'      => ['handler' => 'handleLogout'],
        'GET /auth/me'          => ['handler' => 'handleMe'],
        'POST /auth/refresh'     => ['handler' => 'handleRefreshSession'],

        'GET /user'             => ['handler' => 'handleGetUser'],
        'GET /user/profile'     => ['handler' => 'handleGetUser'],
        'PUT /user/profile'     => ['handler' => 'handleUpdateProfile'],
        'POST /user/profile'     => ['handler' => 'handleUpdateProfile'],
        'GET /users/search'     => ['handler' => 'handleUserSearch'],

        'POST /follow'           => ['handler' => 'handleFollow'],
        'POST /follow/add'       => ['handler' => 'handleFollow'],
        'POST /follow/remove'    => ['handler' => 'handleUnfollow'],
        'DELETE /follow'         => ['handler' => 'handleUnfollow'],
        'GET /followers'        => ['handler' => 'handleFollowers'],
        'GET /following'        => ['handler' => 'handleFollowing'],
        'GET /follow/status'    => ['handler' => 'handleFollowStatus'],

        'POST /like'             => ['handler' => 'handleLike'],
        'POST /like/add'         => ['handler' => 'handleLike'],
        'DELETE /like'           => ['handler' => 'handleUnlike'],
        'POST /like/remove'      => ['handler' => 'handleUnlike'],
        'GET  /like/status'      => ['handler' => 'handleLikeStatus'],
        'GET  /user/likes'       => ['handler' => 'handleUserLikes'],

        'POST /comment'          => ['handler' => 'handleCommentCreate'],
        'GET /comments'         => ['handler' => 'handleCommentList'],
        'GET /comment/replies'  => ['handler' => 'handleCommentReplies'],
        'PUT /comment'          => ['handler' => 'handleCommentUpdate'],
        'POST /comment/update'   => ['handler' => 'handleCommentUpdate'],
        'DELETE /comment'        => ['handler' => 'handleCommentDelete'],
        'POST /comment/delete'   => ['handler' => 'handleCommentDelete'],
        'POST /comment/like'     => ['handler' => 'handleCommentLike'],
        'POST /comment/unlike'   => ['handler' => 'handleCommentUnlike'],

        'POST /playlist/create'      => ['handler' => 'handlePlaylistCreate'],
        'GET /playlist'             => ['handler' => 'handlePlaylistGet'],
        'PUT /playlist'             => ['handler' => 'handlePlaylistUpdate'],
        'POST /playlist/update'      => ['handler' => 'handlePlaylistUpdate'],
        'DELETE /playlist'           => ['handler' => 'handlePlaylistDelete'],
        'POST /playlist/delete'      => ['handler' => 'handlePlaylistDelete'],
        'POST /playlist/add-track'   => ['handler' => 'handlePlaylistAddTrack'],
        'POST /playlist/remove-track'=> ['handler' => 'handlePlaylistRemoveTrack'],
        'POST /playlist/reorder'     => ['handler' => 'handlePlaylistReorder'],
        'GET /playlist/tracks'      => ['handler' => 'handlePlaylistTracks'],
        'POST /playlist/like'        => ['handler' => 'handlePlaylistLike'],
        'POST /playlist/unlike'      => ['handler' => 'handlePlaylistUnlike'],
        'GET /my/playlists'         => ['handler' => 'handleMyPlaylists'],
        'GET /user/playlists'       => ['handler' => 'handleUserPlaylists'],

        'POST /library/save'     => ['handler' => 'handleLibrarySave'],
        'POST /library/remove'   => ['handler' => 'handleLibraryRemove'],
        'GET /library'          => ['handler' => 'handleLibraryList'],
        'POST /history/record'   => ['handler' => 'handleHistoryRecord'],
        'GET /history'          => ['handler' => 'handleHistoryList'],
        'POST /history/clear'    => ['handler' => 'handleHistoryClear'],
        'POST /follow/artist'    => ['handler' => 'handleFollowArtist'],
        'POST /unfollow/artist'  => ['handler' => 'handleUnfollowArtist'],
        'GET /my/artists'       => ['handler' => 'handleMyFollowedArtists'],

        'GET /notifications'        => ['handler' => 'handleNotificationsList'],
        'GET /notifications/count'  => ['handler' => 'handleNotificationsCount'],
        'POST /notifications/read'   => ['handler' => 'handleNotificationsRead'],
        'POST /notifications/delete' => ['handler' => 'handleNotificationsDelete'],
        'DELETE /notifications'      => ['handler' => 'handleNotificationsDelete'],

        'POST /app/create'  => ['handler' => 'handleAppCreate'],
        'GET /apps'        => ['handler' => 'handleAppsList'],
        'GET /app'         => ['handler' => 'handleAppGet'],
        'PUT /app'         => ['handler' => 'handleAppUpdate'],
        'POST /app/update'  => ['handler' => 'handleAppUpdate'],
        'DELETE /app'       => ['handler' => 'handleAppDelete'],
        'POST /app/delete'  => ['handler' => 'handleAppDelete'],
        'GET /app/logs'    => ['handler' => 'handleAppLogs'],
        'GET /app/stats'   => ['handler' => 'handleAppStats'],

        'POST /token/create' => ['handler' => 'handleTokenCreate'],
        'GET /tokens'       => ['handler' => 'handleTokensList'],
        'POST /token/revoke' => ['handler' => 'handleTokenRevoke'],
        'DELETE /token'      => ['handler' => 'handleTokenRevoke'],
        'POST /token/rotate' => ['handler' => 'handleTokenRotate'],

        'POST /webhook/create' => ['handler' => 'handleWebhookCreate'],
        'GET /webhooks'       => ['handler' => 'handleWebhooksList'],
        'DELETE /webhook'      => ['handler' => 'handleWebhookDelete'],
        'POST /webhook/delete' => ['handler' => 'handleWebhookDelete'],

        'GET /search'           => ['handler' => 'routeSearch'],
        'GET /suggest'          => ['handler' => 'routeSuggest'],
        'POST /suggest'          => ['handler' => 'routeSuggest'],
        'GET /lookup'           => ['handler' => 'routeLookup'],
        'GET /artist/tracks'    => ['handler' => 'routeArtistTracks'],
        'GET /artist/songs'     => ['handler' => 'routeArtistTracks'],
        'POST /mirror/set'       => ['handler' => 'routeMirrorSet'],
        'GET  /mirror/get'       => ['handler' => 'routeMirrorGet'],
        'POST /mirror/delete'    => ['handler' => 'routeMirrorDelete'],
        'DELETE /mirror/remove'  => ['handler' => 'routeMirrorDelete'],
        'POST /track/save'       => ['handler' => 'routeTrackSave'],
        'POST /song/save'        => ['handler' => 'routeTrackSave'],
        'POST /collection/save'  => ['handler' => 'routeCollectionSave'],
        'POST /album/save'       => ['handler' => 'routeCollectionSave'],
        'POST /artist/save'      => ['handler' => 'routeArtistSave'],
        'GET /lyrics/get'       => ['handler' => 'routeLyricsGet'],
        'POST /lyrics/save'      => ['handler' => 'routeLyricsSave'],
        'GET /batch'            => ['handler' => 'routeBatch'],
        'GET /fresh'            => ['handler' => 'routeFresh'],
        'GET /popular'          => ['handler' => 'routePopular'],
        'POST /cache/clear'      => ['handler' => 'routeCacheClear'],
        'GET /stats'            => ['handler' => 'routeStats'],
        'GET /db/stats'         => ['handler' => 'routeStats'],
        'GET /health'           => ['handler' => 'routeHealth', 'auth' => false],
        'GET /proxy/status'     => ['handler' => 'routeProxyStatus'],
        'POST /rate-limit/reset' => ['handler' => 'routeResetRateLimit'],
        'POST /sitemap/rebuild'  => ['handler' => 'routeSitemapRebuild'],
        'GET /sitemap/stats'    => ['handler' => 'routeSitemapStats'],
        'POST /sitemap/submit'   => ['handler' => 'routeSitemapSubmit'],
        'GET /sitemap/submissions' => ['handler' => 'routeSitemapSubmissions'],

        'POST /download/add'    => ['handler' => 'routeDownloadAdd'],
        'GET /download/queue'  => ['handler' => 'routeDownloadQueue'],
        'GET /download/status' => ['handler' => 'routeDownloadStatus'],
        'GET /download/progress' => ['handler' => 'routeDownloadStatus'],
        'POST /download/update' => ['handler' => 'routeDownloadUpdate'],
        'PUT /download/update' => ['handler' => 'routeDownloadUpdate'],
        'POST /download/delete' => ['handler' => 'routeDownloadDelete'],
        'DELETE /download/delete' => ['handler' => 'routeDownloadDelete'],
    ];
}

/* ─── Route wrappers ─── */

function routeSearch(PDO $db, array $p): array {
    if (empty($p['term'])) throw new Exception('Missing term', 400);
    return searchiTunes($db, $p);
}
function routeSuggest(PDO $db, array $p): array { return handleSuggest($db, $p); }
function routeLookup(PDO $db, array $p): array {
    if (empty($p['id'])) throw new Exception('Missing id', 400);
    $r = lookupiTunes($db, $p);
    incrementTrackViews($db, explode(',', (string)$p['id']), getViewSessionKey($p));
    return $r;
}
function routeArtistTracks(PDO $db, array $p): array { return handleArtistTracks($db, $p); }
function routeMirrorSet(PDO $db, array $p): array {
    if (!empty($p['attachments']) && is_array($p['attachments'])) return addMirrorUrlsBatch($db, $p['attachments']);
    return addMirrorUrl(
        $db,
        $p['entityType'] ?? '', $p['entityId'] ?? '',
        $p['urlType']    ?? '', $p['mirrorUrl'] ?? '',
        $p['quality']    ?? null,
        $p['source']     ?? 'custom',
        $p['platform']   ?? null
    );
}
function routeMirrorGet(PDO $db, array $p): array {
    return getMirrorUrls($db, $p['entityType'] ?? '', $p['entityId'] ?? '',
                         $p['urlType'] ?? null, $p['quality'] ?? null, $p['platform'] ?? null);
}
function routeMirrorDelete(PDO $db, array $p): array {
    $mirrorId = isset($p['mirrorId']) ? (int)$p['mirrorId'] : null;
    return deleteMirrorUrl($db, $p['entityType'] ?? '', $p['entityId'] ?? '',
                           $p['urlType'] ?? null, $p['quality'] ?? null,
                           $mirrorId, $p['platform'] ?? null);
}
function routeTrackSave(PDO $db, array $p): array { saveEntitiesFromApi($db, 'tracks', $p); return ['success' => true, 'message' => 'Track metadata saved']; }
function routeCollectionSave(PDO $db, array $p): array { saveEntitiesFromApi($db, 'collections', $p); return ['success' => true, 'message' => 'Collection metadata saved']; }
function routeArtistSave(PDO $db, array $p): array { saveEntitiesFromApi($db, 'artists', $p); return ['success' => true, 'message' => 'Artist metadata saved']; }
function routeLyricsGet(PDO $db, array $p): array {
    if (empty($p['id'])) throw new Exception('Missing track id', 400);
    return handleLyricsGet($db, $p['id']);
}
function routeLyricsSave(PDO $db, array $p): array {
    if (empty($p['id']) || empty($p['lyrics'])) throw new Exception('Missing parameters', 400);
    return saveLyrics($db, $p['id'], $p['lyrics'], $p['type'] ?? 'unsynced', $p['source'] ?? 'custom');
}
function routeBatch(PDO $db, array $p): array { return handleBatchLookup($db, $p); }
function routeFresh(PDO $db, array $p): array { return handleFresh($db, $p); }
function routePopular(PDO $db, array $p): array { return handlePopular($db, $p); }
function routeCacheClear(PDO $db): array { return handleCacheClear($db); }
function routeStats(PDO $db): array { return handleStats($db); }
function routeHealth(): array { return ['status' => 'ok', 'timestamp' => date('c'), 'version' => SCHEMA_VERSION]; }
function routeProxyStatus(PDO $db): array { return handleProxyStatus($db); }
function routeResetRateLimit(PDO $db): array { return handleResetRateLimit($db); }
function routeSitemapRebuild(PDO $db): array { return handleSitemapRebuild($db); }
function routeSitemapStats(PDO $db): array { return handleSitemapStats($db); }
function routeSitemapSubmit(PDO $db, array $p): array { return handleSitemapSubmit($db, $p); }
function routeSitemapSubmissions(PDO $db, array $p): array { return handleSitemapSubmissions($db, $p); }
function routeDownloadAdd(PDO $db, array $p): array { return handleDownloadAdd($db, $p); }
function routeDownloadQueue(PDO $db, array $p): array { return handleDownloadQueue($db, $p); }
function routeDownloadStatus(PDO $db, array $p): array { return handleDownloadStatus($db, $p); }
function routeDownloadUpdate(PDO $db, array $p): array { return handleDownloadUpdate($db, $p); }
function routeDownloadDelete(PDO $db, array $p): array { return handleDownloadDelete($db, $p); }

function handleCheckUsername(PDO $db, array $params): array
{
    $u = trim((string)($params['username'] ?? ''));
    if ($u === '') return ['success' => false, 'error' => 'Missing username'];
    if (!validateUsername($u)) return ['success' => true, 'available' => false, 'reason' => 'invalid_format'];
    return ['success' => true, 'available' => !userExistsByUsername($db, $u), 'username' => $u];
}

/* ═══════════════ REQUEST DISPATCHER ═══════════════ */

function logApiRequest(PDO $db, string $endpoint, string $method, int $status, int $startMicro): void
{
    if (empty($GLOBALS['_ctx']['appId']) && empty($GLOBALS['_ctx']['tokenId'])) return;
    try {
        getStatement("INSERT INTO apiRequestLog (appId, userId, tokenId, endpoint, method, statusCode, responseTime, ip, userAgent)
                      VALUES (:a, :u, :t, :e, :m, :s, :rt, :ip, :ua)")
            ->execute([
                ':a'  => $GLOBALS['_ctx']['appId']  ?? null,
                ':u'  => $GLOBALS['_ctx']['user']['userId'] ?? null,
                ':t'  => $GLOBALS['_ctx']['tokenId'] ?? null,
                ':e'  => $endpoint,
                ':m'  => $method,
                ':s'  => $status,
                ':rt' => (int)((microtime(true) * 1e6 - $startMicro) / 1000),
                ':ip' => substr($_SERVER['REMOTE_ADDR'] ?? '', 0, 64),
                ':ua' => substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 1024),
            ]);
    } catch (Throwable $e) {}
}

function handleRequest(): void
{
    enableCompression();
    if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') respond([], 200);

    $path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    if (strpos($path, '/mm/api') === 0) {
        $path = substr($path, strlen('/mm/api'));
    } elseif (strpos($path, '/api') === 0) {
        $path = substr($path, strlen('/api'));
    }
    $path = '/' . trim($path, '/');
    if ($path === '/') $path = '/';

    $method = strtoupper($_SERVER['REQUEST_METHOD']);
    $startMicro = microtime(true) * 1e6;

    if (in_array($path, ['/sitemap', '/sitemap.xml', '/sitemap/index.xml'], true)) {
        try { respondXml(generateSitemapXml(getDB())); }
        catch (Throwable $e) {
            error_log('Sitemap generation failed: ' . $e->getMessage());
            respondXml('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>');
        }
    }
    if (INDEXNOW_KEY !== '' && preg_match('#^/' . preg_quote(INDEXNOW_KEY, '#') . '\.txt$#', $path)) {
        if (!headers_sent()) {
            header('Content-Type: text/plain; charset=utf-8');
            header('Cache-Control: public, max-age=86400');
        }
        echo INDEXNOW_KEY; exit;
    }

    $db = getDB();

    try {
        $u = getBearerUser($db);
        if ($u) $GLOBALS['_ctx']['user'] = $u;
    } catch (Throwable $e) {}

    cleanExpiredCache($db);

    $params = ($method === 'GET') ? $_GET : (json_decode(file_get_contents('php://input'), true) ?: $_POST);
    if (isset($params['term'])) $params['term'] = trim(strtolower($params['term']));

    $quality = $_SERVER['HTTP_QUALITY'] ?? $params['quality'] ?? null;
    if ($quality && !in_array($quality, SUPPORTED_AUDIO_QUALITIES, true)) $quality = DEFAULT_AUDIO_QUALITY;
    if ($quality) $params['quality'] = $quality;

    // Platform header override
    if (!isset($params['platform']) && !empty($_SERVER['HTTP_PLATFORM'])) {
        $params['platform'] = $_SERVER['HTTP_PLATFORM'];
    }

    $routes = getRouteTable();
    $key = $method . ' ' . $path;
    if (!isset($routes[$key])) {
        respond(['success' => false, 'error' => 'Endpoint not found', 'path' => $path, 'method' => $method], 404);
    }
    $route = $routes[$key];
    $public = isset($route['auth']) && $route['auth'] === false;

    try {
        if (!$public) {
            $masterOk = false;
            if (TRUST_MASTER_TOKEN) {
                $tok = extractAuthToken();
                if ($tok && hash_equals(API_TOKEN, $tok)) {
                    $GLOBALS['_ctx']['auth']   = 'master';
                    $GLOBALS['_ctx']['scopes'] = ['*'];
                    $masterOk = true;
                }
            }
            if (!$masterOk && empty($GLOBALS['_ctx']['user'])) {
                // soft — individual handlers enforce auth if needed
            }
        }

        $handler = $route['handler'];
        if (!function_exists($handler)) throw new Exception('Handler not implemented: ' . $handler, 500);

        $ref = new ReflectionFunction($handler);
        $argc = $ref->getNumberOfParameters();
        if ($argc >= 2) $response = $handler($db, $params);
        else            $response = $handler($db);

        logApiRequest($db, $path, $method, 200, $startMicro);
    } catch (Throwable $e) {
        $rawCode = $e->getCode();
        $status  = (is_int($rawCode) && $rawCode >= 100 && $rawCode <= 599) ? $rawCode : 500;
        logApiRequest($db, $path, $method, $status, $startMicro);
        respond(['success' => false, 'error' => $e->getMessage()], $status);
    }

    logApiRequest($db, $path, $method, 200, $startMicro);
    respond($response);
}

/* ═══════════════ BOOTSTRAP ═══════════════ */

if (php_sapi_name() !== 'cli' && !defined('SKIP_AUTO_HANDLE')) {
    try {
        handleRequest();
    } catch (Throwable $e) {
        http_response_code(500);
        error_log("Fatal error: " . $e->getMessage());
        echo json_encode(['success' => false, 'error' => 'Internal server error', 'message' => $e->getMessage()]);
    }
}
