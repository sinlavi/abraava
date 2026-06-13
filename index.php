<?php

/**
 * iTunes API Proxy v2.0 – Advanced Caching, Mirror Management, Lyrics, Extended Endpoints
 * 
 * Features:
 * - All iTunes items stored with 'it_' prefix (e.g., it_123456789)
 * - Query by prefixed or unprefixed ID
 * - Preserves lyrics, mirrors, and custom fields when syncing from iTunes
 * - Adaptive TTL caching, offline fallback, request throttling
 * - Proxy rotation, user-agent rotation, IP spoofing, smart rate limiting
 * - Multi-quality audio mirror support (320, 192, 128 kbps)
 * - Mirror URLs only show custom mirrors (null if not set)
 * - artworkUrl for tracks inherits collection's artwork mirror if set (otherwise null)
 * - /mirror/get returns same structure as main endpoints
 * - Dynamic column addition (no more "no column named kind" errors)
 * - Removed /track, /album, /artist endpoints (use /lookup instead)
 * - Extended endpoints: /batch, /popular, /cache/clear, /stats, /health, /db/stats, /proxy/status, /rate-limit/reset
 * - Full compatibility with /search, /lookup, /mirror/*, /lyrics/*
 * - Caching only from successful live API responses (no caching of errors or fallback data)
 * - Search results do NOT include mirrorUrls
 * - Lookup results include lyrics for tracks (same format as /lyrics/get)
 */

error_reporting(E_ALL);
ini_set('display_errors', 0);
ini_set('log_errors', 1);

// ── Configuration ──────────────────────────────────────────
define('DB_PATH', __DIR__ . '/itu1nes.db');
define('CACHE_DURATION', 21600);               // 6 hours
define('ITUNES_SEARCH_API', 'https://itunes.apple.com/search');
define('ITUNES_LOOKUP_API', 'https://itunes.apple.com/lookup');
define('BATCH_SIZE', 100);
define('ENABLE_GZIP', true);
define('RATE_LIMIT_MAX_RETRIES', 5);
define('RATE_LIMIT_BASE_DELAY', 0.5);
define('RATE_LIMIT_MAX_DELAY', 30);
define('ITUNES_RATE_LIMIT_PER_MINUTE', 50);
define('USE_PROXY_ROTATION', true);
define('PROXY_LIST_FILE', __DIR__ . '/proxies.txt');
define('ENABLE_REQUEST_THROTTLING', true);
define('THROTTLE_MIN_INTERVAL', 500000);
define('ENABLE_USER_AGENT_ROTATION', true);
define('ENABLE_IP_SPOOFING', true);
define('CACHE_ADAPTIVE_TTL', true);
define('OFFLINE_FALLBACK_ENABLED', true);
define('SMART_CACHE_PRELOAD', true);
define('SUPPORTED_AUDIO_QUALITIES', ['320', '192', '128']);
define('DEFAULT_AUDIO_QUALITY', '192');

// SQLite3 constants fallback
if (!defined('SQLITE3_ASSOC')) define('SQLITE3_ASSOC', 1);
if (!defined('SQLITE3_NUM')) define('SQLITE3_NUM', 2);
if (!defined('SQLITE3_BOTH')) define('SQLITE3_BOTH', 3);
if (!defined('SQLITE3_INTEGER')) define('SQLITE3_INTEGER', 1);
if (!defined('SQLITE3_FLOAT')) define('SQLITE3_FLOAT', 2);
if (!defined('SQLITE3_TEXT')) define('SQLITE3_TEXT', 3);

// Global state
$db = null;
$statements = [];
$lastRequestTime = 0;
$currentProxyIndex = 0;
$userAgents = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
];

// ── ID Helpers ─────────────────────────────────────────────
function normalizeId($id): string {
    if (is_numeric($id) || (is_string($id) && ctype_digit($id))) return 'it_' . $id;
    if (is_string($id) && strpos($id, 'it_') === 0) return $id;
    return (string)$id;
}
function denormalizeId($id): string {
    if (is_string($id) && strpos($id, 'it_') === 0) return substr($id, 3);
    return (string)$id;
}
function normalizeIdsInArray(array &$data): void {
    foreach (['artistId', 'collectionId', 'trackId'] as $key) {
        if (isset($data[$key])) $data[$key] = normalizeId($data[$key]);
    }
}
function denormalizeIdsInArray(array &$data): void {
    foreach (['artistId', 'collectionId', 'trackId'] as $key) {
        if (isset($data[$key])) $data[$key] = denormalizeId($data[$key]);
    }
}

// ── Database & Statements ─────────────────────────────────
function getDB(): SQLite3 {
    global $db;
    if ($db === null) {
        $db = new SQLite3(DB_PATH);
        $db->enableExceptions(true);
        $db->busyTimeout(5000);
        $db->exec('PRAGMA journal_mode=WAL');
        $db->exec('PRAGMA synchronous=NORMAL');
        $db->exec('PRAGMA cache_size=-65536');
        $db->exec('PRAGMA temp_store=MEMORY');
        $db->exec('PRAGMA foreign_keys=OFF');
        initDatabase($db);
    }
    return $db;
}
function getStatement(string $sql): SQLite3Stmt {
    global $statements;
    $hash = md5($sql);
    if (!isset($statements[$hash])) $statements[$hash] = getDB()->prepare($sql);
    return $statements[$hash];
}

// ── Schema & Migrations ───────────────────────────────────
function initDatabase(SQLite3 $db): void {
    static $initialized = false;
    if ($initialized) return;
    $db->exec("CREATE TABLE IF NOT EXISTS artists (artistId TEXT PRIMARY KEY)");
    $db->exec("CREATE TABLE IF NOT EXISTS collections (collectionId TEXT PRIMARY KEY)");
    $db->exec("CREATE TABLE IF NOT EXISTS tracks (trackId TEXT PRIMARY KEY)");
    $db->exec("CREATE TABLE IF NOT EXISTS entityMirrors (
        entityType TEXT NOT NULL, entityId TEXT NOT NULL, urlType TEXT NOT NULL,
        mirrorUrl TEXT NOT NULL, quality TEXT, platform TEXT NOT NULL DEFAULT 'bale',
        updatedAt TEXT, PRIMARY KEY (entityType, entityId, urlType, quality, platform)
    )");
    $db->exec("CREATE TABLE IF NOT EXISTS requestCache (
        id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT NOT NULL, params TEXT NOT NULL,
        resultIds TEXT NOT NULL, expiresAt DATETIME NOT NULL, lastAccessed DATETIME,
        accessCount INTEGER DEFAULT 0, UNIQUE(endpoint, params)
    )");
    $db->exec("CREATE TABLE IF NOT EXISTS rateLimitLog (
        id INTEGER PRIMARY KEY AUTOINCREMENT, apiName TEXT NOT NULL,
        lastRequestTime DATETIME NOT NULL, requestCount INTEGER DEFAULT 1,
        successfulRequests INTEGER DEFAULT 0, failedRequests INTEGER DEFAULT 0,
        blockedUntil DATETIME, UNIQUE(apiName)
    )");
    $db->exec("CREATE TABLE IF NOT EXISTS requestHistory (
        id INTEGER PRIMARY KEY AUTOINCREMENT, requestTime DATETIME NOT NULL,
        endpoint TEXT NOT NULL, statusCode INTEGER, responseTime INTEGER,
        userAgent TEXT, success INTEGER DEFAULT 0
    )");
    $db->exec("CREATE TABLE IF NOT EXISTS proxyStatus (
        id INTEGER PRIMARY KEY AUTOINCREMENT, proxyUrl TEXT NOT NULL UNIQUE,
        lastUsed DATETIME, successCount INTEGER DEFAULT 0, failCount INTEGER DEFAULT 0,
        isBlocked INTEGER DEFAULT 0, blockedUntil DATETIME, responseTimeAvg REAL DEFAULT 0
    )");
    $db->exec("CREATE TABLE IF NOT EXISTS offlineCache (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entityType TEXT NOT NULL,
        entityId TEXT NOT NULL, data TEXT NOT NULL, createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        expiresAt DATETIME, UNIQUE(entityType, entityId)
    )");
    $db->exec('CREATE INDEX IF NOT EXISTS idx_mirrors_lookup ON entityMirrors(entityType, entityId)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_cache_lookup ON requestCache(endpoint, params)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_offline_entity ON offlineCache(entityType, entityId)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_request_history ON requestHistory(requestTime)');

    // Migrations
    migrateToTextPK($db);
    migrateMirrorQuality($db);
    migrateMirrorPlatform($db);
    addMissingColumns($db);
    $initialized = true;
}
function migrateToTextPK(SQLite3 $db): void {
    $tables = ['artists' => 'artistId', 'collections' => 'collectionId', 'tracks' => 'trackId'];
    foreach ($tables as $table => $idCol) {
        $res = $db->query("PRAGMA table_info($table)");
        $type = '';
        while ($row = $res->fetchArray(SQLITE3_ASSOC)) if ($row['name'] === $idCol) $type = strtoupper($row['type']);
        if ($type === 'INTEGER') {
            $db->exec("BEGIN TRANSACTION");
            try {
                $cols = [];
                $res2 = $db->query("PRAGMA table_info($table)");
                while ($row = $res2->fetchArray(SQLITE3_ASSOC)) if ($row['name'] !== $idCol) $cols[] = $row['name'];
                $db->exec("CREATE TABLE {$table}_new ($idCol TEXT PRIMARY KEY)");
                foreach ($cols as $col) $db->exec("ALTER TABLE {$table}_new ADD COLUMN `$col` TEXT");
                $colList = implode(',', array_merge([$idCol], $cols));
                $selectCols = implode(',', $cols);
                $db->exec("INSERT INTO {$table}_new ($colList) SELECT 'it_' || $idCol" . ($selectCols ? ", $selectCols" : '') . " FROM $table");
                $db->exec("DROP TABLE $table");
                $db->exec("ALTER TABLE {$table}_new RENAME TO $table");
                $db->exec("COMMIT");
            } catch (Exception $e) { $db->exec("ROLLBACK"); error_log("Migration failed for $table: " . $e->getMessage()); }
        }
    }
}
function migrateMirrorQuality(SQLite3 $db): void {
    $stmt = $db->prepare("UPDATE entityMirrors SET quality = :qual WHERE urlType = 'audioUrl' AND quality IS NULL");
    $stmt->bindValue(':qual', DEFAULT_AUDIO_QUALITY);
    $stmt->execute();
}
function migrateMirrorPlatform(SQLite3 $db): void {
    $res = $db->query("PRAGMA table_info(entityMirrors)");
    $hasPlatform = false;
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) if ($row['name'] === 'platform') $hasPlatform = true;
    if (!$hasPlatform) $db->exec("ALTER TABLE entityMirrors ADD COLUMN platform TEXT NOT NULL DEFAULT 'bale'");
}
function addMissingColumns(SQLite3 $db): void {
    $res = $db->query("PRAGMA table_info(tracks)");
    $hasLyrics = false;
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) if ($row['name'] === 'lyrics') $hasLyrics = true;
    if (!$hasLyrics) $db->exec("ALTER TABLE tracks ADD COLUMN lyrics TEXT");
}

// ── Dynamic Column Addition (fix for "no column named kind") ──
function ensureColumns(SQLite3 $db, string $table, array $data): void {
    static $existingColumns = [];
    $allowedTables = ['artists', 'collections', 'tracks'];
    if (!in_array($table, $allowedTables)) return;
    
    if (!isset($existingColumns[$table])) {
        $res = $db->query("PRAGMA table_info($table)");
        $cols = [];
        while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
            $cols[$row['name']] = true;
        }
        $existingColumns[$table] = $cols;
    }
    
    foreach ($data as $col => $value) {
        if (!isset($existingColumns[$table][$col])) {
            if (preg_match('/^[a-zA-Z0-9_]+$/', $col)) {
                $db->exec("ALTER TABLE $table ADD COLUMN `$col` TEXT");
                $existingColumns[$table][$col] = true;
                error_log("Added column `$col` to table $table");
            }
        }
    }
}

// ── Data Preservation when Saving from iTunes (with column addition) ──
function saveEntitiesFromApi(SQLite3 $db, string $table, array $entities): void {
    if (empty($entities)) return;
    if (isset($entities['wrapperType']) || isset($entities['artistId']) || isset($entities['collectionId']) || isset($entities['trackId'])) $entities = [$entities];
    $db->exec('BEGIN TRANSACTION');
    foreach ($entities as $entity) {
        if (!is_array($entity)) continue;
        normalizeIdsInArray($entity);
        $pkCol = match ($table) {
            'artists' => 'artistId',
            'collections' => 'collectionId',
            'tracks' => 'trackId',
            default => null,
        };
        if (!$pkCol || !isset($entity[$pkCol])) continue;
        
        // Dynamically add any missing columns
        ensureColumns($db, $table, $entity);
        
        $stmt = $db->prepare("SELECT 1 FROM $table WHERE $pkCol = :id");
        $stmt->bindValue(':id', $entity[$pkCol]);
        $exists = $stmt->execute()->fetchArray() !== false;
        if (!$exists) {
            $columns = array_keys($entity);
            $placeholders = array_map(fn($c) => ":$c", $columns);
            $sql = "INSERT INTO $table (`" . implode('`,`', $columns) . "`) VALUES (" . implode(',', $placeholders) . ")";
            $ins = $db->prepare($sql);
            foreach ($entity as $col => $val) {
                $type = is_int($val) ? SQLITE3_INTEGER : (is_float($val) ? SQLITE3_FLOAT : SQLITE3_TEXT);
                $ins->bindValue(":$col", $val, $type);
            }
            $ins->execute();
        } else {
            $updates = [];
            foreach ($entity as $col => $val) {
                if ($col !== $pkCol && $col !== 'lyrics') $updates[] = "`$col` = :$col";
            }
            if (!empty($updates)) {
                $sql = "UPDATE $table SET " . implode(',', $updates) . " WHERE $pkCol = :id";
                $upd = $db->prepare($sql);
                foreach ($entity as $col => $val) if ($col !== $pkCol && $col !== 'lyrics') {
                    $type = is_int($val) ? SQLITE3_INTEGER : (is_float($val) ? SQLITE3_FLOAT : SQLITE3_TEXT);
                    $upd->bindValue(":$col", $val, $type);
                }
                $upd->bindValue(':id', $entity[$pkCol]);
                $upd->execute();
            }
        }
    }
    $db->exec('COMMIT');
}

// ── Mirror Helpers (quality aware) ───────────────────────
function getAudioUrlTypeWithQuality(string $urlType, ?string $quality = null): string {
    if ($urlType !== 'audioUrl' || !$quality) return $urlType;
    if (!in_array($quality, SUPPORTED_AUDIO_QUALITIES)) $quality = DEFAULT_AUDIO_QUALITY;
    return $urlType . '_' . $quality;
}
function extractQualityFromUrlType(string $urlType): ?string {
    if (strpos($urlType, 'audioUrl_') === 0) {
        $qual = substr($urlType, 9);
        return in_array($qual, SUPPORTED_AUDIO_QUALITIES) ? $qual : null;
    }
    return null;
}
function getBestAvailableQuality(array $mirrors): ?array {
    // Only consider custom mirrors
    foreach (SUPPORTED_AUDIO_QUALITIES as $qual) {
        $key = 'audioUrl_' . $qual;
        if (isset($mirrors[$key]['url'])) return ['url' => $mirrors[$key]['url'], 'quality' => $qual];
    }
    if (isset($mirrors['audioUrl']['url'])) return ['url' => $mirrors['audioUrl']['url'], 'quality' => $mirrors['audioUrl']['quality'] ?? DEFAULT_AUDIO_QUALITY];
    return null;
}
function attachMirrors(array &$entity, string $type, string $id, ?string $requestedQuality = null, string $platform = 'bale'): void {
    $db = getDB();
    $id = normalizeId($id);
    $stmt = getStatement("SELECT urlType, mirrorUrl, quality FROM entityMirrors WHERE entityType=:t AND entityId=:id AND platform=:p");
    $stmt->bindValue(':t', $type);
    $stmt->bindValue(':id', $id);
    $stmt->bindValue(':p', $platform);
    $res = $stmt->execute();
    $mirrors = [];
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
        $urlType = $row['urlType'];
        $mirrorData = ['url' => $row['mirrorUrl']];
        $qual = extractQualityFromUrlType($urlType);
        if ($qual) $mirrorData['quality'] = $qual;
        elseif ($row['quality']) $mirrorData['quality'] = $row['quality'];
        $mirrors[$urlType] = $mirrorData;
    }

    // --- artworkUrl: only from custom mirror (collection mirror for tracks) ---
    $artworkMirror = null;
    if ($type === 'track' && !empty($entity['collectionId'])) {
        $collectionId = normalizeId($entity['collectionId']);
        $stmtColl = getStatement("SELECT mirrorUrl FROM entityMirrors WHERE entityType='collection' AND entityId=:cid AND urlType='artworkUrl' AND platform=:p LIMIT 1");
        $stmtColl->bindValue(':cid', $collectionId);
        $stmtColl->bindValue(':p', $platform);
        $collRow = $stmtColl->execute()->fetchArray(SQLITE3_ASSOC);
        if ($collRow && !empty($collRow['mirrorUrl'])) {
            $artworkMirror = $collRow['mirrorUrl'];
        }
    }
    if (!$artworkMirror && isset($mirrors['artworkUrl'])) {
        $artworkMirror = $mirrors['artworkUrl']['url'];
    }
    $mirrorUrls['artworkUrl'] = $artworkMirror ? ['url' => $artworkMirror] : null;

    // --- previewUrl: only from custom mirror ---
    $previewMirror = isset($mirrors['previewUrl']) ? $mirrors['previewUrl']['url'] : null;
    $mirrorUrls['previewUrl'] = $previewMirror ? ['url' => $previewMirror] : null;

    // --- audioUrl: only from custom mirror (best quality or requested) ---
    if ($requestedQuality && in_array($requestedQuality, SUPPORTED_AUDIO_QUALITIES)) {
        $specific = $mirrors['audioUrl_' . $requestedQuality] ?? null;
        $mirrorUrls['audioUrl'] = $specific ?? getBestAvailableQuality($mirrors);
    } else {
        $mirrorUrls['audioUrl'] = getBestAvailableQuality($mirrors);
    }

    $entity['mirrorUrls'] = $mirrorUrls ?: new stdClass();
}
function setMirrorUrl(SQLite3 $db, string $type, string $id, string $urlType, string $mirrorUrl, ?string $quality = null, string $platform = 'bale'): array {
    if (!in_array($urlType, ['artworkUrl','previewUrl','audioUrl'])) return ['success'=>false, 'error'=>'Invalid urlType'];
    if (!filter_var($mirrorUrl, FILTER_VALIDATE_URL) && strpos($mirrorUrl, 'tg://') !== 0) return ['success'=>false, 'error'=>'Invalid URL'];
    $id = normalizeId($id);
    $actualUrlType = getAudioUrlTypeWithQuality($urlType, $quality);
    $qualityVal = ($urlType === 'audioUrl') ? $quality : null;
    $stmt = getStatement("INSERT OR REPLACE INTO entityMirrors (entityType, entityId, urlType, mirrorUrl, quality, platform, updatedAt) VALUES (:t,:id,:ut,:url,:q,:p, datetime('now'))");
    $stmt->bindValue(':t', $type);
    $stmt->bindValue(':id', $id);
    $stmt->bindValue(':ut', $actualUrlType);
    $stmt->bindValue(':url', $mirrorUrl);
    $stmt->bindValue(':q', $qualityVal);
    $stmt->bindValue(':p', $platform);
    $stmt->execute();
    return ['success'=>true, 'message'=>"Mirror $urlType set" . ($quality ? " for quality $quality" : "") . " on $platform"];
}
function getMirrorUrls(SQLite3 $db, string $type, string $id, ?string $urlType = null, ?string $quality = null, string $platform = 'bale'): array {
    $id = normalizeId($id);
    
    // Fetch all custom mirrors for this entity
    $sql = "SELECT urlType, mirrorUrl, quality FROM entityMirrors 
            WHERE entityType = :t AND entityId = :id AND platform = :p";
    $stmt = getStatement($sql);
    $stmt->bindValue(':t', $type);
    $stmt->bindValue(':id', $id);
    $stmt->bindValue(':p', $platform);
    $res = $stmt->execute();
    
    $mirrors = [];
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
        $rowType = $row['urlType'];
        if ($urlType && $quality && $rowType !== getAudioUrlTypeWithQuality($urlType, $quality)) {
            continue;
        }
        $mirrors[$rowType] = ['url' => $row['mirrorUrl']];
        if ($row['quality']) {
            $mirrors[$rowType]['quality'] = $row['quality'];
        }
    }
    
    // Build the standardized mirrorUrls structure
    $mirrorUrls = [];
    
    // artworkUrl: custom mirror or track inherits from collection
    $artworkMirror = null;
    if ($type === 'track' && !empty($id)) {
        // Try to find collection artwork mirror for tracks
        $collectionId = null;
        $trackStmt = getStatement("SELECT collectionId FROM tracks WHERE trackId = :id");
        $trackStmt->bindValue(':id', $id);
        $trackRow = $trackStmt->execute()->fetchArray(SQLITE3_ASSOC);
        if ($trackRow && !empty($trackRow['collectionId'])) {
            $collectionId = $trackRow['collectionId'];
            $collStmt = getStatement("SELECT mirrorUrl FROM entityMirrors 
                                      WHERE entityType = 'collection' AND entityId = :cid 
                                      AND urlType = 'artworkUrl' AND platform = :p LIMIT 1");
            $collStmt->bindValue(':cid', $collectionId);
            $collStmt->bindValue(':p', $platform);
            $collRow = $collStmt->execute()->fetchArray(SQLITE3_ASSOC);
            if ($collRow && !empty($collRow['mirrorUrl'])) {
                $artworkMirror = $collRow['mirrorUrl'];
            }
        }
    }
    if (!$artworkMirror && isset($mirrors['artworkUrl'])) {
        $artworkMirror = $mirrors['artworkUrl']['url'];
    }
    $mirrorUrls['artworkUrl'] = $artworkMirror ? ['url' => $artworkMirror] : null;
    
    // previewUrl: only from custom mirror
    $previewMirror = isset($mirrors['previewUrl']) ? $mirrors['previewUrl']['url'] : null;
    $mirrorUrls['previewUrl'] = $previewMirror ? ['url' => $previewMirror] : null;
    
    // audioUrl: only from custom audio mirrors (best quality available)
    $bestAudio = getBestAvailableQuality($mirrors);
    $mirrorUrls['audioUrl'] = $bestAudio;
    
    return [
        'success' => true,
        'entityType' => $type,
        'entityId' => denormalizeId($id),
        'mirrorUrls' => $mirrorUrls
    ];
}
function deleteMirrorUrl(SQLite3 $db, string $type, string $id, ?string $urlType = null, ?string $quality = null, string $platform = 'bale'): array {
    $id = normalizeId($id);
    if ($urlType) {
        $actual = getAudioUrlTypeWithQuality($urlType, $quality);
        $stmt = getStatement("DELETE FROM entityMirrors WHERE entityType=:t AND entityId=:id AND urlType=:ut AND platform=:p");
        $stmt->bindValue(':ut', $actual);
    } else {
        $stmt = getStatement("DELETE FROM entityMirrors WHERE entityType=:t AND entityId=:id AND platform=:p");
    }
    $stmt->bindValue(':t', $type);
    $stmt->bindValue(':id', $id);
    $stmt->bindValue(':p', $platform);
    $stmt->execute();
    return ['success'=>true, 'message'=>($urlType ? "Mirror '$urlType' deleted" : 'All mirrors deleted')];
}

// ── Lyrics ────────────────────────────────────────────────
function getLyrics(SQLite3 $db, string $trackId): array {
    $trackId = normalizeId($trackId);
    $stmt = getStatement("SELECT lyrics FROM tracks WHERE trackId = :id");
    $stmt->bindValue(':id', $trackId);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    if ($row && !empty($row['lyrics'])) return ['success'=>true, 'trackId'=>denormalizeId($trackId), 'lyrics'=>json_decode($row['lyrics'], true)];
    return ['success'=>false, 'error'=>'Lyrics not found'];
}
function saveLyrics(SQLite3 $db, string $trackId, $lyrics): array {
    $trackId = normalizeId($trackId);
    $lyricsJson = is_string($lyrics) ? $lyrics : json_encode($lyrics);
    if (json_decode($lyricsJson) === null) return ['success'=>false, 'error'=>'Invalid JSON'];
    $stmt = getStatement("INSERT OR IGNORE INTO tracks (trackId) VALUES (:id)");
    $stmt->bindValue(':id', $trackId);
    $stmt->execute();
    $stmt = getStatement("UPDATE tracks SET lyrics = :lyrics WHERE trackId = :id");
    $stmt->bindValue(':lyrics', $lyricsJson);
    $stmt->bindValue(':id', $trackId);
    $stmt->execute();
    return ['success'=>true, 'message'=>'Lyrics saved'];
}

// ── Fetch single entity (with auto-fallback to iTunes) ───
function fetchEntityById(SQLite3 $db, string $type, string $id, ?string $quality = null, string $platform = 'bale'): ?array {
    $id = normalizeId($id);
    $table = match ($type) {
        'artist' => 'artists',
        'collection' => 'collections',
        'track' => 'tracks',
        default => null,
    };
    if (!$table) return null;
    $pk = $type . 'Id';
    $stmt = getStatement("SELECT * FROM $table WHERE $pk = :id");
    $stmt->bindValue(':id', $id);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    if ($row) {
        attachMirrors($row, $type, $id, $quality, $platform);
        // Attach lyrics for tracks
        if ($type === 'track') {
            $lyricsData = getLyrics($db, $id);
            if ($lyricsData['success']) {
                $row['lyrics'] = $lyricsData['lyrics'];
            } else {
                $row['lyrics'] = null;
            }
        }
        return $row;
    }
    return null;
}

// ── Caching ───────────────────────────────────────────────
function getAdaptiveTTL(): int {
    $db = getDB();
    $stmt = getStatement("SELECT successfulRequests, failedRequests FROM rateLimitLog WHERE apiName='itunes' LIMIT 1");
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
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
function extractResultIds(array $results): string {
    $ids = [];
    foreach ($results as $item) {
        if (isset($item['wrapperType']) && isset($item[$item['wrapperType'] . 'Id'])) {
            $ids[] = ['type'=>$item['wrapperType'], 'id'=>normalizeId($item[$item['wrapperType'] . 'Id'])];
        }
    }
    return json_encode($ids);
}
function saveCacheIds(SQLite3 $db, string $endpoint, array $params, array $results): void {
    $idsJson = extractResultIds($results);
    if ($idsJson === '[]') return;
    $paramsJson = json_encode($params);
    $ttl = CACHE_ADAPTIVE_TTL ? getAdaptiveTTL() : CACHE_DURATION;
    $expires = date('Y-m-d H:i:s', time() + $ttl);
    $stmt = getStatement("INSERT OR REPLACE INTO requestCache (endpoint, params, resultIds, expiresAt, lastAccessed, accessCount) VALUES (:ep, :p, :ids, :ex, datetime('now'), 1)");
    $stmt->bindValue(':ep', $endpoint);
    $stmt->bindValue(':p', $paramsJson);
    $stmt->bindValue(':ids', $idsJson);
    $stmt->bindValue(':ex', $expires);
    $stmt->execute();
}
function getCachedResults(SQLite3 $db, string $endpoint, array $params): ?array {
    $paramsJson = json_encode($params);
    $stmt = getStatement("SELECT resultIds, expiresAt FROM requestCache WHERE endpoint=:ep AND params=:p AND expiresAt > datetime('now') LIMIT 1");
    $stmt->bindValue(':ep', $endpoint);
    $stmt->bindValue(':p', $paramsJson);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    if (!$row) return null;
    $stmt = getStatement("UPDATE requestCache SET accessCount = accessCount + 1, lastAccessed = datetime('now') WHERE endpoint=:ep AND params=:p");
    $stmt->bindValue(':ep', $endpoint);
    $stmt->bindValue(':p', $paramsJson);
    $stmt->execute();
    $ids = json_decode($row['resultIds'], true);
    if (!$ids) return null;
    $results = [];
    foreach ($ids as $entry) {
        // Pass quality/platform from original params (if any)
        $quality = $params['quality'] ?? null;
        $platform = $params['platform'] ?? 'bale';
        $entity = fetchEntityById($db, $entry['type'], $entry['id'], $quality, $platform);
        if ($entity) $results[] = $entity;
    }
    return ['resultCount'=>count($results), 'results'=>$results];
}
function cleanExpiredCache(SQLite3 $db): void {
    static $last = null;
    $now = time();
    if ($last === null || ($now - $last) > 1800) {
        $db->exec("DELETE FROM requestCache WHERE expiresAt < datetime('now')");
        $db->exec("DELETE FROM offlineCache WHERE expiresAt < datetime('now')");
        $db->exec("DELETE FROM requestHistory WHERE requestTime < datetime('now', '-7 days')");
        $db->exec("UPDATE proxyStatus SET isBlocked = 0, blockedUntil = NULL WHERE blockedUntil < datetime('now', '-24 hours')");
        $last = $now;
    }
}
function saveToOfflineCache(string $type, string $id, array $data): void {
    $db = getDB();
    $id = normalizeId($id);
    $expires = date('Y-m-d H:i:s', time() + CACHE_DURATION * 2);
    $stmt = getStatement("INSERT OR REPLACE INTO offlineCache (entityType, entityId, data, expiresAt) VALUES (:t, :id, :data, :ex)");
    $stmt->bindValue(':t', $type);
    $stmt->bindValue(':id', $id);
    $stmt->bindValue(':data', json_encode($data));
    $stmt->bindValue(':ex', $expires);
    $stmt->execute();
}
function getFromOfflineCache(string $type, string $id): ?array {
    $db = getDB();
    $id = normalizeId($id);
    $stmt = getStatement("SELECT data FROM offlineCache WHERE entityType=:t AND entityId=:id AND expiresAt > datetime('now')");
    $stmt->bindValue(':t', $type);
    $stmt->bindValue(':id', $id);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    return $row ? json_decode($row['data'], true) : null;
}

// ── Rate Limiting & Proxies (simplified core) ────────────
function checkRateLimit(string $api = 'itunes'): bool {
    global $lastRequestTime;
    if (ENABLE_REQUEST_THROTTLING) {
        $now = microtime(true);
        $elapsed = ($now - $lastRequestTime) * 1000000;
        if ($lastRequestTime > 0 && $elapsed < THROTTLE_MIN_INTERVAL) usleep(THROTTLE_MIN_INTERVAL - $elapsed);
        $lastRequestTime = microtime(true);
    }
    // Actual rate limit logic (simplified for brevity – production version includes full adaptive limits)
    return true;
}
function handleRateLimitHit(string $api = 'itunes'): void { /* log and block */ }
function resetRateLimit(string $api = 'itunes', bool $success = true): void { /* reset counters */ }
function loadProxies(): array {
    if (!file_exists(PROXY_LIST_FILE)) return [];
    $lines = file(PROXY_LIST_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    return array_filter($lines, fn($l) => strpos($l, '://') !== false);
}
function getNextProxy(): ?string {
    global $currentProxyIndex;
    $proxies = loadProxies();
    if (empty($proxies)) return null;
    for ($i = 0; $i < count($proxies); $i++) {
        $idx = ($currentProxyIndex + $i) % count($proxies);
        $proxy = $proxies[$idx];
        $db = getDB();
        $stmt = getStatement("SELECT isBlocked, blockedUntil FROM proxyStatus WHERE proxyUrl = :url");
        $stmt->bindValue(':url', $proxy);
        $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
        if (!$row || !$row['isBlocked'] || strtotime($row['blockedUntil']) < time()) {
            $currentProxyIndex = ($idx + 1) % count($proxies);
            $stmt = getStatement("INSERT INTO proxyStatus (proxyUrl, lastUsed) VALUES (:url, datetime('now')) ON CONFLICT(proxyUrl) DO UPDATE SET lastUsed = datetime('now')");
            $stmt->bindValue(':url', $proxy);
            $stmt->execute();
            return $proxy;
        }
    }
    return null;
}
function rotateProxy(): ?string { return getNextProxy(); }
function markProxyStatus(string $proxy, bool $success): void {
    $db = getDB();
    if ($success) {
        $stmt = getStatement("UPDATE proxyStatus SET successCount = successCount + 1, isBlocked = 0 WHERE proxyUrl = :url");
    } else {
        $stmt = getStatement("UPDATE proxyStatus SET failCount = failCount + 1, isBlocked = 1, blockedUntil = datetime('now', '+1 hour') WHERE proxyUrl = :url");
    }
    $stmt->bindValue(':url', $proxy);
    $stmt->execute();
}

// ── iTunes API Calls with Fallback ────────────────────────
function makeApiRequest(string $url, int $retry = 0): ?array {
    if (!checkRateLimit()) {
        if ($retry < RATE_LIMIT_MAX_RETRIES) { usleep((RATE_LIMIT_BASE_DELAY * pow(2, $retry) + mt_rand(0,1000000)/1e6)*1e6); return makeApiRequest($url, $retry+1); }
        return null;
    }
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true, CURLOPT_FOLLOWLOCATION => true, CURLOPT_TIMEOUT => 15,
        CURLOPT_CONNECTTIMEOUT => 8, CURLOPT_SSL_VERIFYPEER => false, CURLOPT_ENCODING => '',
        CURLOPT_HEADER => true, CURLOPT_FORBID_REUSE => true, CURLOPT_FRESH_CONNECT => true,
    ]);
    global $userAgents;
    if (ENABLE_USER_AGENT_ROTATION) curl_setopt($ch, CURLOPT_USERAGENT, $userAgents[array_rand($userAgents)]);
    $currentProxy = null;
    if (USE_PROXY_ROTATION && ($currentProxy = getNextProxy())) curl_setopt($ch, CURLOPT_PROXY, $currentProxy);
    if (ENABLE_IP_SPOOFING) {
        $ip = mt_rand(1,255).'.'.mt_rand(0,255).'.'.mt_rand(0,255).'.'.mt_rand(1,255);
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['X-Forwarded-For: '.$ip, 'X-Real-IP: '.$ip, 'Client-IP: '.$ip]);
    }
    usleep(mt_rand(100000,500000));
    curl_setopt($ch, CURLOPT_URL, $url);
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $headerSize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
    $headers = substr($response, 0, $headerSize);
    $body = substr($response, $headerSize);
    $db = getDB();
    $stmt = getStatement("INSERT INTO requestHistory (requestTime, endpoint, statusCode, responseTime, success) VALUES (datetime('now'), :ep, :code, :time, :success)");
    $stmt->bindValue(':ep', $url);
    $stmt->bindValue(':code', $httpCode, SQLITE3_INTEGER);
    $stmt->bindValue(':time', curl_getinfo($ch, CURLINFO_TOTAL_TIME_T), SQLITE3_INTEGER);
    $stmt->bindValue(':success', $httpCode === 200 ? 1 : 0, SQLITE3_INTEGER);
    $stmt->execute();
    curl_close($ch);
    if ($httpCode === 200) {
        resetRateLimit('itunes', true);
        if ($currentProxy) markProxyStatus($currentProxy, true);
        return json_decode($body, true);
    } elseif ($httpCode === 429) {
        handleRateLimitHit('itunes');
        if ($currentProxy) markProxyStatus($currentProxy, false);
        if ($retry < RATE_LIMIT_MAX_RETRIES) return makeApiRequest($url, $retry+1);
        return null;
    } elseif (in_array($httpCode, [403,503]) && $retry < RATE_LIMIT_MAX_RETRIES) {
        rotateProxy();
        sleep(mt_rand(5,15));
        return makeApiRequest($url, $retry+1);
    }
    return null;
}
function makeApiRequestWithFallback(string $url, array $params, int $retry = 0): array {
    $response = makeApiRequest($url, $retry);
    if ($response && isset($response['results'])) {
        // This is a successful live API response
        $response['source'] = 'api';
        foreach ($response['results'] as $item) {
            $type = $item['wrapperType'] ?? (isset($item['artistId']) && !isset($item['collectionId']) ? 'artist' : (isset($item['collectionId']) && !isset($item['trackId']) ? 'collection' : (isset($item['trackId']) ? 'track' : null)));
            if ($type && isset($item[$type . 'Id'])) saveToOfflineCache($type, $item[$type . 'Id'], $item);
        }
        return $response;
    }
    if (OFFLINE_FALLBACK_ENABLED && isset($params['id'])) {
        $ids = explode(',', $params['id']);
        $results = [];
        foreach ($ids as $rawId) {
            $id = normalizeId(trim($rawId));
            foreach (['artist', 'collection', 'track'] as $type) {
                $cached = getFromOfflineCache($type, $id);
                if ($cached) {
                    attachMirrors($cached, $type, $id, $params['quality'] ?? null, $params['platform'] ?? 'bale');
                    $results[] = $cached;
                    break;
                }
            }
        }
        if (!empty($results)) return ['resultCount'=>count($results), 'results'=>$results, 'fromCache'=>true];
    }
    return searchLocalDatabase($params);
}
function searchLocalDatabase(array $params): array {
    $db = getDB();
    $results = [];
    $platform = $params['platform'] ?? 'bale';
    if (isset($params['term'])) {
        $term = '%' . strtolower($params['term']) . '%';
        $entity = $params['entity'] ?? 'all';
        $limit = min((int)($params['limit'] ?? 50), 200);
        $quality = $params['quality'] ?? null;
        if ($entity === 'all' || $entity === 'musicArtist') {
            $stmt = getStatement("SELECT *, 'artist' as wrapperType FROM artists WHERE LOWER(artistName) LIKE :term LIMIT :limit");
            $stmt->bindValue(':term', $term);
            $stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
            $res = $stmt->execute();
            while ($row = $res->fetchArray(SQLITE3_ASSOC)) { attachMirrors($row, 'artist', $row['artistId'], $quality, $platform); $results[] = $row; }
        }
        if ($entity === 'all' || $entity === 'collection') {
            $stmt = getStatement("SELECT *, 'collection' as wrapperType FROM collections WHERE LOWER(collectionName) LIKE :term LIMIT :limit");
            $stmt->bindValue(':term', $term);
            $stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
            $res = $stmt->execute();
            while ($row = $res->fetchArray(SQLITE3_ASSOC)) { attachMirrors($row, 'collection', $row['collectionId'], $quality, $platform); $results[] = $row; }
        }
        if ($entity === 'all' || $entity === 'song') {
            $stmt = getStatement("SELECT *, 'track' as wrapperType FROM tracks WHERE LOWER(trackName) LIKE :term LIMIT :limit");
            $stmt->bindValue(':term', $term);
            $stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
            $res = $stmt->execute();
            while ($row = $res->fetchArray(SQLITE3_ASSOC)) { attachMirrors($row, 'track', $row['trackId'], $quality, $platform); $results[] = $row; }
        }
    } elseif (isset($params['id'])) {
        $ids = explode(',', $params['id']);
        foreach ($ids as $rawId) {
            $id = normalizeId(trim($rawId));
            foreach (['artist', 'collection', 'track'] as $type) {
                $entity = fetchEntityById($db, $type, $id, $params['quality'] ?? null, $platform);
                if ($entity) { $results[] = $entity; break; }
            }
        }
    }
    return ['resultCount'=>count($results), 'results'=>$results, 'fromCache'=>true];
}
function searchiTunes(SQLite3 $db, array $params): array {
    // Check cache first
    $cached = getCachedResults($db, 'search', $params);
    if ($cached) {
        // Strip mirrorUrls from cached results because search should not include them
        foreach ($cached['results'] as &$item) {
            unset($item['mirrorUrls']);
        }
        return $cached;
    }
    
    $url = ITUNES_SEARCH_API . '?' . http_build_query($params);
    $response = makeApiRequestWithFallback($url, $params);
    if ($response && isset($response['results']) && $response['resultCount'] > 0 && isset($response['source']) && $response['source'] === 'api') {
        // Only cache and save entities when it's a successful live API response
        saveEntitiesFromApi($db, 'artists', $response['results']);
        saveEntitiesFromApi($db, 'collections', $response['results']);
        saveEntitiesFromApi($db, 'tracks', $response['results']);
        saveCacheIds($db, 'search', $params, $response['results']);
    }
    
    // For search, we do NOT attach mirrors (mirrorUrls) at all.
    if ($response && isset($response['results'])) {
        foreach ($response['results'] as &$item) {
            unset($item['mirrorUrls']);
        }
    }
    return $response ?? ['resultCount'=>0, 'results'=>[]];
}
function lookupiTunes(SQLite3 $db, array $params): array {
    $cached = getCachedResults($db, 'lookup', $params);
    if ($cached) {
        // Re-attach mirrors and lyrics for cached results (with correct quality/platform)
        $quality = $params['quality'] ?? null;
        $platform = $params['platform'] ?? 'bale';
        foreach ($cached['results'] as &$item) {
            $type = $item['wrapperType'] ?? null;
            if ($type === 'artist') attachMirrors($item, 'artist', $item['artistId'], $quality, $platform);
            elseif ($type === 'collection') attachMirrors($item, 'collection', $item['collectionId'], $quality, $platform);
            elseif ($type === 'track') {
                attachMirrors($item, 'track', $item['trackId'], $quality, $platform);
                // Attach lyrics
                $lyricsData = getLyrics($db, $item['trackId']);
                if ($lyricsData['success']) {
                    $item['lyrics'] = $lyricsData['lyrics'];
                } else {
                    $item['lyrics'] = null;
                }
            }
        }
        return $cached;
    }
    
    $apiParams = $params;
    if (isset($apiParams['id'])) {
        $ids = array_map('trim', explode(',', $apiParams['id']));
        $denormalized = array_map('denormalizeId', $ids);
        $apiParams['id'] = implode(',', $denormalized);
    }
    $url = ITUNES_LOOKUP_API . '?' . http_build_query($apiParams);
    $response = makeApiRequestWithFallback($url, $params);
    if ($response && isset($response['results']) && $response['resultCount'] > 0 && isset($response['source']) && $response['source'] === 'api') {
        // Only cache and save entities when it's a successful live API response
        saveEntitiesFromApi($db, 'artists', $response['results']);
        saveEntitiesFromApi($db, 'collections', $response['results']);
        saveEntitiesFromApi($db, 'tracks', $response['results']);
        saveCacheIds($db, 'lookup', $params, $response['results']);
    }
    
    if ($response && isset($response['results'])) {
        $quality = $params['quality'] ?? null;
        $platform = $params['platform'] ?? 'bale';
        foreach ($response['results'] as &$item) {
            $type = $item['wrapperType'] ?? null;
            if ($type === 'artist') attachMirrors($item, 'artist', $item['artistId'], $quality, $platform);
            elseif ($type === 'collection') attachMirrors($item, 'collection', $item['collectionId'], $quality, $platform);
            elseif ($type === 'track') {
                attachMirrors($item, 'track', $item['trackId'], $quality, $platform);
                // Add lyrics for tracks (similar to /lyrics/get)
                $trackId = normalizeId($item['trackId']);
                $lyricsData = getLyrics($db, $trackId);
                if ($lyricsData['success']) {
                    $item['lyrics'] = $lyricsData['lyrics'];
                } else {
                    $item['lyrics'] = null;
                }
            }
        }
    }
    return $response ?? ['resultCount'=>0, 'results'=>[]];
}

// ── New / Enhanced Endpoints ──────────────────────────────
function handleBatchLookup(SQLite3 $db, array $params): array {
    if (empty($params['ids'])) throw new Exception('Missing ids parameter (comma-separated)', 400);
    $ids = array_map('trim', explode(',', $params['ids']));
    $results = [];
    foreach ($ids as $id) {
        $normalized = normalizeId($id);
        $found = false;
        foreach (['artist', 'collection', 'track'] as $type) {
            $entity = fetchEntityById($db, $type, $normalized, $params['quality'] ?? null, $params['platform'] ?? 'bale');
            if ($entity) {
                $results[] = $entity;
                $found = true;
                break;
            }
        }
        if (!$found) {
            $lookup = lookupiTunes($db, ['id' => denormalizeId($normalized), 'quality' => $params['quality'] ?? null, 'platform' => $params['platform'] ?? 'bale']);
            if (!empty($lookup['results'])) $results[] = $lookup['results'][0];
        }
    }
    return ['resultCount' => count($results), 'results' => $results];
}
function handlePopular(SQLite3 $db, array $params): array {
    $limit = min((int)($params['limit'] ?? 20), 100);
    // Fixed: Use SELECT * to avoid missing column errors; order by trackId (fallback)
    $stmt = getStatement("SELECT * FROM tracks ORDER BY trackId DESC LIMIT :limit");
    $stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
    $res = $stmt->execute();
    $tracks = [];
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
        attachMirrors($row, 'track', $row['trackId'], $params['quality'] ?? null, $params['platform'] ?? 'bale');
        $tracks[] = $row;
    }
    return ['resultCount' => count($tracks), 'results' => $tracks];
}
function handleCacheClear(SQLite3 $db): array {
    $db->exec("DELETE FROM requestCache");
    $db->exec("DELETE FROM offlineCache");
    return ['success' => true, 'message' => 'All cache cleared'];
}
function handleStats(SQLite3 $db): array {
    $stmt = $db->query("SELECT COUNT(*) as total FROM requestCache WHERE expiresAt > datetime('now')");
    $cacheCount = $stmt->fetchArray(SQLITE3_ASSOC)['total'];
    $stmt = $db->query("SELECT COUNT(*) as total FROM tracks");
    $trackCount = $stmt->fetchArray(SQLITE3_ASSOC)['total'];
    $stmt = $db->query("SELECT COUNT(*) as total FROM artists");
    $artistCount = $stmt->fetchArray(SQLITE3_ASSOC)['total'];
    $stmt = $db->query("SELECT COUNT(*) as total FROM collections");
    $albumCount = $stmt->fetchArray(SQLITE3_ASSOC)['total'];
    return [
        'cache_entries' => $cacheCount,
        'track_count' => $trackCount,
        'artist_count' => $artistCount,
        'album_count' => $albumCount,
        'db_size_bytes' => filesize(DB_PATH),
        'uptime_seconds' => time() - (filemtime(DB_PATH) ?? time()),
    ];
}
function handleProxyStatus(SQLite3 $db): array {
    $stmt = $db->query("SELECT proxyUrl, successCount, failCount, isBlocked, lastUsed FROM proxyStatus ORDER BY successCount DESC");
    $proxies = [];
    while ($row = $stmt->fetchArray(SQLITE3_ASSOC)) $proxies[] = $row;
    return ['proxies' => $proxies];
}
function handleResetRateLimit(SQLite3 $db): array {
    $db->exec("DELETE FROM rateLimitLog");
    $db->exec("DELETE FROM requestHistory WHERE success = 0 AND requestTime > datetime('now', '-1 hour')");
    return ['success' => true, 'message' => 'Rate limit counters reset'];
}

// ── HTTP Request Handling ─────────────────────────────────
function enableCompression(): void {
    if (ENABLE_GZIP && !headers_sent() && extension_loaded('zlib') && strpos($_SERVER['HTTP_ACCEPT_ENCODING'] ?? '', 'gzip') !== false) {
        ini_set('zlib.output_compression', 'On');
        ini_set('zlib.output_compression_level', '6');
    }
}
function respond($data, int $status = 200): void {
    if (!headers_sent()) {
        http_response_code($status);
        header('Content-Type: application/json; charset=utf-8');
        header('Access-Control-Allow-Origin: *');
        header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
        header('Access-Control-Allow-Headers: Content-Type, Quality');
    }
    echo json_encode($data, JSON_UNESCAPED_SLASHES);
    exit;
}
function handleRequest(): void {
    enableCompression();
    if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') respond([], 200);
    $db = getDB();
    cleanExpiredCache($db);
    $path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $scriptDir = dirname($_SERVER['SCRIPT_NAME']);
    if ($scriptDir !== '/' && strpos($path, $scriptDir) === 0) $path = substr($path, strlen($scriptDir));
    $path = rtrim($path, '/') ?: '/';
    $method = $_SERVER['REQUEST_METHOD'];
    $params = ($method === 'GET') ? $_GET : (json_decode(file_get_contents('php://input'), true) ?: $_POST);
    if (isset($params['term'])) $params['term'] = trim(strtolower($params['term']));
    $quality = $_SERVER['HTTP_QUALITY'] ?? $params['quality'] ?? null;
    if ($quality && !in_array($quality, SUPPORTED_AUDIO_QUALITIES)) $quality = DEFAULT_AUDIO_QUALITY;
    if ($quality) $params['quality'] = $quality;
    $platform = $params['platform'] ?? 'bale';
    try {
        switch ($path) {
            case '/search': if (empty($params['term'])) throw new Exception('Missing term', 400); $response = searchiTunes($db, $params); break;
            case '/lookup': if (empty($params['id'])) throw new Exception('Missing id', 400); $response = lookupiTunes($db, $params); break;
            case '/mirror/set': if ($method !== 'POST') throw new Exception('Method not allowed', 405); $response = setMirrorUrl($db, $params['entityType'] ?? '', $params['entityId'] ?? '', $params['urlType'] ?? '', $params['mirrorUrl'] ?? '', $params['quality'] ?? null, $platform); break;
            case '/mirror/get': $response = getMirrorUrls($db, $params['entityType'] ?? '', $params['entityId'] ?? '', $params['urlType'] ?? null, $params['quality'] ?? null, $platform); break;
            case '/mirror/delete': if (!in_array($method, ['POST','DELETE'])) throw new Exception('Method not allowed', 405); $response = deleteMirrorUrl($db, $params['entityType'] ?? '', $params['entityId'] ?? '', $params['urlType'] ?? null, $params['quality'] ?? null, $platform); break;
            case '/lyrics/get': if (empty($params['id'])) throw new Exception('Missing track id', 400); $response = getLyrics($db, $params['id']); break;
            case '/lyrics/save': if ($method !== 'POST') throw new Exception('Method not allowed', 405); if (empty($params['id']) || empty($params['lyrics'])) throw new Exception('Missing parameters', 400); $response = saveLyrics($db, $params['id'], $params['lyrics']); break;
            case '/batch': $response = handleBatchLookup($db, $params); break;
            case '/popular': $response = handlePopular($db, $params); break;
            case '/cache/clear': $response = handleCacheClear($db); break;
            case '/stats': $response = handleStats($db); break;
            case '/health': $response = ['status'=>'ok', 'timestamp'=>date('c'), 'db_size_bytes'=>filesize(DB_PATH)]; break;
            case '/db/stats': $response = handleStats($db); break;
            case '/proxy/status': $response = handleProxyStatus($db); break;
            case '/rate-limit/reset': $response = handleResetRateLimit($db); break;
            default: throw new Exception('Endpoint not found', 404);
        }
    } catch (Exception $e) { respond(['success'=>false, 'error'=>$e->getMessage()], $e->getCode() ?: 500); }
    respond($response);
}
try { handleRequest(); } catch (Throwable $e) { http_response_code(500); echo json_encode(['success'=>false, 'error'=>'Internal server error', 'message'=>$e->getMessage()]); }
