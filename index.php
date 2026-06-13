<?php

error_reporting(E_ALL);
ini_set('display_errors', 0);
ini_set('log_errors', 1);

// ── Configuration ──────────────────────────────────────────
define('DB_PATH', __DIR__ . '/itunes.db');
define('CACHE_DURATION', 21600);          // 6 hours
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

// Quality settings
define('SUPPORTED_AUDIO_QUALITIES', ['320', '192', '128']);
define('DEFAULT_AUDIO_QUALITY', '192');

// SQLite3 constants fallback
if (!defined('SQLITE3_ASSOC')) define('SQLITE3_ASSOC', 1);
if (!defined('SQLITE3_NUM')) define('SQLITE3_NUM', 2);
if (!defined('SQLITE3_BOTH')) define('SQLITE3_BOTH', 3);
if (!defined('SQLITE3_INTEGER')) define('SQLITE3_INTEGER', 1);
if (!defined('SQLITE3_FLOAT')) define('SQLITE3_FLOAT', 2);
if (!defined('SQLITE3_TEXT')) define('SQLITE3_TEXT', 3);

$db = null;
$statements = [];
$lastRequestTime = 0;
$currentProxyIndex = 0;
$userAgents = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
];

// ── Database & Statement helpers ──────────────────────────
function normalizeId($id): string {
    if (is_numeric($id) || (is_string($id) && ctype_digit($id))) {
        return 'it_' . $id;
    }
    return (string)$id;
}

function denormalizeId($id): string {
    if (is_string($id) && strpos($id, 'it_') === 0) {
        return substr($id, 3);
    }
    return (string)$id;
}

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
    if (!isset($statements[$hash])) {
        $statements[$hash] = getDB()->prepare($sql);
    }
    return $statements[$hash];
}

// ── Schema ────────────────────────────────────────────────
function initDatabase(SQLite3 $db): void {
    static $initialized = false;
    if ($initialized) return;

    $db->exec("CREATE TABLE IF NOT EXISTS artists (artistId TEXT PRIMARY KEY)");
    $db->exec("CREATE TABLE IF NOT EXISTS collections (collectionId TEXT PRIMARY KEY)");
    $db->exec("CREATE TABLE IF NOT EXISTS tracks (trackId TEXT PRIMARY KEY)");

    $db->exec("CREATE TABLE IF NOT EXISTS entityMirrors (
        entityType TEXT NOT NULL,
        entityId TEXT NOT NULL,
        urlType TEXT NOT NULL,
        mirrorUrl TEXT NOT NULL,
        quality TEXT,
        platform TEXT NOT NULL DEFAULT 'bale',
        updatedAt TEXT,
        PRIMARY KEY (entityType, entityId, urlType, quality, platform)
    )");

    $db->exec("CREATE INDEX IF NOT EXISTS idx_mirrors_quality ON entityMirrors(entityType, entityId, urlType, quality, platform)");
    $db->exec("CREATE INDEX IF NOT EXISTS idx_mirrors_lookup ON entityMirrors(entityType, entityId)");

    $db->exec("CREATE TABLE IF NOT EXISTS requestCache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT NOT NULL,
        params TEXT NOT NULL,
        resultIds TEXT NOT NULL,
        expiresAt DATETIME NOT NULL,
        lastAccessed DATETIME,
        accessCount INTEGER DEFAULT 0,
        UNIQUE(endpoint, params)
    )");

    $db->exec("CREATE TABLE IF NOT EXISTS rateLimitLog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        apiName TEXT NOT NULL,
        lastRequestTime DATETIME NOT NULL,
        requestCount INTEGER DEFAULT 1,
        successfulRequests INTEGER DEFAULT 0,
        failedRequests INTEGER DEFAULT 0,
        blockedUntil DATETIME,
        UNIQUE(apiName)
    )");

    $db->exec("CREATE TABLE IF NOT EXISTS requestHistory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requestTime DATETIME NOT NULL,
        endpoint TEXT NOT NULL,
        statusCode INTEGER,
        responseTime INTEGER,
        userAgent TEXT,
        success INTEGER DEFAULT 0
    )");

    $db->exec("CREATE TABLE IF NOT EXISTS proxyStatus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proxyUrl TEXT NOT NULL UNIQUE,
        lastUsed DATETIME,
        successCount INTEGER DEFAULT 0,
        failCount INTEGER DEFAULT 0,
        isBlocked INTEGER DEFAULT 0,
        blockedUntil DATETIME,
        responseTimeAvg REAL DEFAULT 0
    )");

    $db->exec("CREATE TABLE IF NOT EXISTS requestPattern (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hour INTEGER NOT NULL,
        minute INTEGER NOT NULL,
        requestCount INTEGER DEFAULT 0,
        successRate REAL DEFAULT 1.0,
        UNIQUE(hour, minute)
    )");

    $db->exec("CREATE TABLE IF NOT EXISTS offlineCache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entityType TEXT NOT NULL,
        entityId TEXT NOT NULL,
        data TEXT NOT NULL,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        expiresAt DATETIME,
        UNIQUE(entityType, entityId)
    )");

    $db->exec('CREATE INDEX IF NOT EXISTS idx_cache_lookup ON requestCache(endpoint, params)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_cache_expires ON requestCache(expiresAt)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_offline_expires ON offlineCache(expiresAt)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_offline_entity ON offlineCache(entityType, entityId)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_request_history ON requestHistory(requestTime)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_request_pattern ON requestPattern(hour, minute)');
    
    $result = $db->query("PRAGMA table_info(requestCache)");
    $hasLastAccessed = false;
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        if ($row['name'] === 'lastAccessed') {
            $hasLastAccessed = true;
            break;
        }
    }
    $result->finalize();

    if (!$hasLastAccessed) {
        try {
            $db->exec("ALTER TABLE requestCache ADD COLUMN lastAccessed DATETIME");
            $db->exec("ALTER TABLE requestCache ADD COLUMN accessCount INTEGER DEFAULT 0");
        } catch (Exception $e) {
            // Column may have been added already
        }
    }

    migrateSchemaToTextPK($db);
    migrateMirrorQualitySupport($db);
    migrateMirrorPlatformSupport($db);
    $initialized = true;
}

function migrateMirrorPlatformSupport(SQLite3 $db): void {
    $result = $db->query("PRAGMA table_info(entityMirrors)");
    $hasPlatform = false;
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        if ($row['name'] === 'platform') {
            $hasPlatform = true;
            break;
        }
    }
    $result->finalize();

    if (!$hasPlatform) {
        error_log("Migrating entityMirrors to support platform");
        $db->exec("BEGIN IMMEDIATE TRANSACTION");
        try {
            $db->exec("CREATE TABLE entityMirrors_new (
                entityType TEXT NOT NULL,
                entityId TEXT NOT NULL,
                urlType TEXT NOT NULL,
                mirrorUrl TEXT NOT NULL,
                quality TEXT,
                platform TEXT NOT NULL DEFAULT 'bale',
                updatedAt TEXT,
                PRIMARY KEY (entityType, entityId, urlType, quality, platform)
            )");
            $db->exec("INSERT INTO entityMirrors_new (entityType, entityId, urlType, mirrorUrl, quality, updatedAt)
                       SELECT entityType, entityId, urlType, mirrorUrl, quality, updatedAt FROM entityMirrors");
            $db->exec("DROP TABLE entityMirrors");
            $db->exec("ALTER TABLE entityMirrors_new RENAME TO entityMirrors");
            $db->exec("CREATE INDEX IF NOT EXISTS idx_mirrors_quality ON entityMirrors(entityType, entityId, urlType, quality, platform)");
            $db->exec("CREATE INDEX IF NOT EXISTS idx_mirrors_lookup ON entityMirrors(entityType, entityId)");
            $db->exec("COMMIT");
        } catch (Exception $e) {
            $db->exec("ROLLBACK");
            error_log("Migration failed for entityMirrors platform: " . $e->getMessage());
        }
    }
}

function migrateSchemaToTextPK(SQLite3 $db): void {
    $tables = [
        'artists' => 'artistId',
        'collections' => 'collectionId',
        'tracks' => 'trackId'
    ];

    foreach ($tables as $table => $idCol) {
        $result = $db->query("PRAGMA table_info($table)");
        $idType = '';
        while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
            if ($row['name'] === $idCol) {
                $idType = strtoupper($row['type']);
                break;
            }
        }

        if ($idType === 'INTEGER') {
            error_log("Migrating $table PK to TEXT");

            // Get other columns first to avoid locking issues while reading during transaction
            $res = $db->query("PRAGMA table_info($table)");
            $cols = [];
            while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
                if ($row['name'] !== $idCol) {
                    $cols[] = $row['name'];
                }
            }
            $res->finalize();

            $db->exec("BEGIN IMMEDIATE TRANSACTION");
            try {
                $db->exec("CREATE TABLE {$table}_new ($idCol TEXT PRIMARY KEY)");
                foreach ($cols as $col) {
                    $db->exec("ALTER TABLE {$table}_new ADD COLUMN `$col` TEXT");
                }

                $colList = implode(', ', array_merge([$idCol], $cols));
                $selectCols = implode(', ', $cols);
                $db->exec("INSERT INTO {$table}_new ($colList) SELECT 'it_' || $idCol" . ($selectCols ? ", $selectCols" : "") . " FROM $table");

                $db->exec("DROP TABLE $table");
                $db->exec("ALTER TABLE {$table}_new RENAME TO $table");
                $db->exec("COMMIT");
            } catch (Exception $e) {
                $db->exec("ROLLBACK");
                error_log("Migration failed for $table: " . $e->getMessage());
            }
        }
    }

    // Also migrate entityMirrors entityId
    $result = $db->query("PRAGMA table_info(entityMirrors)");
    $idType = '';
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        if ($row['name'] === 'entityId') {
            $idType = strtoupper($row['type']);
            break;
        }
    }
    $result->finalize();
    if ($idType === 'INTEGER') {
        error_log("Migrating entityMirrors entityId to TEXT");
        $db->exec("BEGIN IMMEDIATE TRANSACTION");
        try {
            $db->exec("CREATE TABLE entityMirrors_new (
                entityType TEXT NOT NULL,
                entityId TEXT NOT NULL,
                urlType TEXT NOT NULL,
                mirrorUrl TEXT NOT NULL,
                quality TEXT,
                platform TEXT NOT NULL DEFAULT 'bale',
                updatedAt TEXT,
                PRIMARY KEY (entityType, entityId, urlType, quality, platform)
            )");
            $db->exec("INSERT INTO entityMirrors_new (entityType, entityId, urlType, mirrorUrl, quality, updatedAt)
                       SELECT entityType, 'it_' || entityId, urlType, mirrorUrl, quality, updatedAt FROM entityMirrors");
            $db->exec("DROP TABLE entityMirrors");
            $db->exec("ALTER TABLE entityMirrors_new RENAME TO entityMirrors");
            $db->exec("CREATE INDEX IF NOT EXISTS idx_mirrors_quality ON entityMirrors(entityType, entityId, urlType, quality, platform)");
            $db->exec("CREATE INDEX IF NOT EXISTS idx_mirrors_lookup ON entityMirrors(entityType, entityId)");
            $db->exec("COMMIT");
        } catch (Exception $e) {
            $db->exec("ROLLBACK");
            error_log("Migration failed for entityMirrors: " . $e->getMessage());
        }
    }

    // Offline Cache migration
    $result = $db->query("PRAGMA table_info(offlineCache)");
    $idType = '';
    while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
        if ($row['name'] === 'entityId') {
            $idType = strtoupper($row['type']);
            break;
        }
    }
    $result->finalize();

    if ($idType === 'INTEGER') {
        error_log("Migrating offlineCache entityId to TEXT");
        $db->exec("BEGIN IMMEDIATE TRANSACTION");
        try {
            $db->exec("CREATE TABLE offlineCache_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entityType TEXT NOT NULL,
                entityId TEXT NOT NULL,
                data TEXT NOT NULL,
                createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
                expiresAt DATETIME,
                UNIQUE(entityType, entityId)
            )");
            $db->exec("INSERT INTO offlineCache_new (entityType, entityId, data, createdAt, expiresAt)
                       SELECT entityType, 'it_' || entityId, data, createdAt, expiresAt FROM offlineCache");
            $db->exec("DROP TABLE offlineCache");
            $db->exec("ALTER TABLE offlineCache_new RENAME TO offlineCache");
            $db->exec('CREATE INDEX IF NOT EXISTS idx_offline_expires ON offlineCache(expiresAt)');
            $db->exec('CREATE INDEX IF NOT EXISTS idx_offline_entity ON offlineCache(entityType, entityId)');
            $db->exec("COMMIT");
        } catch (Exception $e) {
            $db->exec("ROLLBACK");
            error_log("Migration failed for offlineCache: " . $e->getMessage());
        }
    }
}

function migrateMirrorQualitySupport(SQLite3 $db): void {
    $stmt = $db->prepare("SELECT COUNT(*) as count FROM entityMirrors WHERE urlType = 'audioUrl' AND quality IS NULL");
    $result = $stmt->execute();
    $row = $result->fetchArray(SQLITE3_ASSOC);
    $result->finalize();
    
    if ($row && $row['count'] > 0) {
        $stmt = $db->prepare("UPDATE entityMirrors SET quality = :quality WHERE urlType = 'audioUrl' AND quality IS NULL");
        $stmt->bindValue(':quality', DEFAULT_AUDIO_QUALITY, SQLITE3_TEXT);
        $stmt->execute();
        
        $db->exec("DELETE FROM entityMirrors WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM entityMirrors 
            GROUP BY entityType, entityId, urlType, COALESCE(quality, '')
        )");
    }
}

// ── Advanced Rate Limit Management ──────────────────────────
function checkRateLimit(string $apiName = 'itunes'): bool {
    global $lastRequestTime;
    $db = getDB();
    
    if (ENABLE_REQUEST_THROTTLING) {
        $currentTime = microtime(true);
        $timeSinceLastRequest = ($currentTime - $lastRequestTime) * 1000000;
        if ($lastRequestTime > 0 && $timeSinceLastRequest < THROTTLE_MIN_INTERVAL) {
            $sleepTime = THROTTLE_MIN_INTERVAL - $timeSinceLastRequest;
            usleep((int)$sleepTime);
        }
        $lastRequestTime = microtime(true);
    }

    $stmt = getStatement("SELECT lastRequestTime, requestCount, successfulRequests, failedRequests, blockedUntil FROM rateLimitLog WHERE apiName = :api");
    $stmt->bindValue(':api', $apiName, SQLITE3_TEXT);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);

    if ($row && $row['blockedUntil']) {
        $blockedUntil = strtotime($row['blockedUntil']);
        if ($blockedUntil > time()) {
            $waitTime = $blockedUntil - time() + mt_rand(1, 5);
            sleep($waitTime);
            return false;
        }
    }

    if (!$row) {
        $stmt = getStatement("INSERT INTO rateLimitLog (apiName, lastRequestTime, requestCount, successfulRequests, failedRequests) VALUES (:api, datetime('now'), 1, 0, 0)");
        $stmt->bindValue(':api', $apiName, SQLITE3_TEXT);
        $stmt->execute();
        logRequestPattern($db);
        return true;
    }

    $lastTime = strtotime($row['lastRequestTime']);
    $count = $row['requestCount'];
    $successCount = $row['successfulRequests'];
    $failCount = $row['failedRequests'];
    $currentTime = time();
    $timeDiff = $currentTime - $lastTime;

    $totalRequests = $successCount + $failCount;
    $successRate = $totalRequests > 0 ? $successCount / $totalRequests : 1.0;

    $maxRequestsPerMinute = ITUNES_RATE_LIMIT_PER_MINUTE;
    if ($successRate < 0.7) {
        $maxRequestsPerMinute = (int)($maxRequestsPerMinute * 0.5);
    } elseif ($successRate < 0.9) {
        $maxRequestsPerMinute = (int)($maxRequestsPerMinute * 0.8);
    }

    if ($timeDiff < 60) {
        if ($count >= $maxRequestsPerMinute) {
            $waitTime = 60 - $timeDiff + mt_rand(1, 10);
            usleep($waitTime * 1000000);
            
            $stmt = getStatement("UPDATE rateLimitLog SET failedRequests = failedRequests + 1, lastRequestTime = datetime('now') WHERE apiName = :api");
            $stmt->bindValue(':api', $apiName, SQLITE3_TEXT);
            $stmt->execute();
            return false;
        }
    } else {
        $stmt = getStatement("UPDATE rateLimitLog SET lastRequestTime = datetime('now'), requestCount = 0, successfulRequests = 0, failedRequests = 0 WHERE apiName = :api");
        $stmt->bindValue(':api', $apiName, SQLITE3_TEXT);
        $stmt->execute();
    }

    $stmt = getStatement("UPDATE rateLimitLog SET requestCount = requestCount + 1, lastRequestTime = datetime('now') WHERE apiName = :api");
    $stmt->bindValue(':api', $apiName, SQLITE3_TEXT);
    $stmt->execute();

    $smartDelay = calculateSmartDelay($count, $timeDiff, $successRate);
    usleep($smartDelay);

    logRequestPattern($db);
    return true;
}

function calculateSmartDelay(int $requestCount, int $timeSinceLastRequest, float $successRate): int {
    $baseDelay = mt_rand(100000, 300000);
    
    if ($requestCount > 10) {
        $exponentialFactor = min(pow(1.5, $requestCount - 10), 10);
        $baseDelay = (int)($baseDelay * $exponentialFactor);
    }
    
    if ($successRate < 0.7) {
        $baseDelay = (int)($baseDelay * 2.5);
    } elseif ($successRate < 0.9) {
        $baseDelay = (int)($baseDelay * 1.5);
    }
    
    $jitter = mt_rand(0, (int)($baseDelay * 0.25));
    $maxDelay = RATE_LIMIT_MAX_DELAY * 1000000;
    return min($baseDelay + $jitter, $maxDelay);
}

function handleRateLimitHit(string $apiName = 'itunes'): void {
    $db = getDB();
    
    $stmt = getStatement("SELECT failedRequests FROM rateLimitLog WHERE apiName = :api");
    $stmt->bindValue(':api', $apiName, SQLITE3_TEXT);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    
    $failCount = $row ? $row['failedRequests'] + 1 : 1;
    $blockDuration = min(pow(2, $failCount), 3600);
    $blockUntil = date('Y-m-d H:i:s', time() + $blockDuration);
    
    $stmt = getStatement("UPDATE rateLimitLog SET failedRequests = :fail, blockedUntil = :block WHERE apiName = :api");
    $stmt->bindValue(':fail', $failCount, SQLITE3_INTEGER);
    $stmt->bindValue(':block', $blockUntil, SQLITE3_TEXT);
    $stmt->bindValue(':api', $apiName, SQLITE3_TEXT);
    $stmt->execute();
    
    if (USE_PROXY_ROTATION) {
        rotateProxy();
    }
}

function resetRateLimit(string $apiName = 'itunes', bool $success = true): void {
    $db = getDB();
    
    if ($success) {
        $stmt = getStatement("UPDATE rateLimitLog SET successfulRequests = successfulRequests + 1, blockedUntil = NULL WHERE apiName = :api");
    } else {
        $stmt = getStatement("UPDATE rateLimitLog SET lastRequestTime = datetime('now') WHERE apiName = :api");
    }
    $stmt->bindValue(':api', $apiName, SQLITE3_TEXT);
    $stmt->execute();
}

function logRequestPattern(SQLite3 $db): void {
    $hour = (int)date('H');
    $minute = (int)date('i');
    
    $stmt = getStatement("INSERT INTO requestPattern (hour, minute, requestCount) VALUES (:hour, :min, 1) ON CONFLICT(hour, minute) DO UPDATE SET requestCount = requestCount + 1");
    $stmt->bindValue(':hour', $hour, SQLITE3_INTEGER);
    $stmt->bindValue(':min', $minute, SQLITE3_INTEGER);
    $stmt->execute();
}

// ── Proxy Management ──────────────────────────────────────
function loadProxies(): array {
    $proxies = [];
    if (file_exists(PROXY_LIST_FILE)) {
        $lines = file(PROXY_LIST_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        foreach ($lines as $line) {
            $line = trim($line);
            if (!empty($line) && strpos($line, '://') !== false) {
                $proxies[] = $line;
            }
        }
    }
    return $proxies;
}

function getNextProxy(): ?string {
    global $currentProxyIndex;
    $proxies = loadProxies();
    
    if (empty($proxies)) {
        return null;
    }
    
    $db = getDB();
    $startIndex = $currentProxyIndex;
    
    for ($i = 0; $i < count($proxies); $i++) {
        $index = ($startIndex + $i) % count($proxies);
        $proxy = $proxies[$index];
        
        $stmt = getStatement("SELECT isBlocked, blockedUntil FROM proxyStatus WHERE proxyUrl = :url");
        $stmt->bindValue(':url', $proxy, SQLITE3_TEXT);
        $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
        
        if (!$row || !$row['isBlocked'] || strtotime($row['blockedUntil']) < time()) {
            $currentProxyIndex = ($index + 1) % count($proxies);
            
            $stmt = getStatement("INSERT INTO proxyStatus (proxyUrl, lastUsed) VALUES (:url, datetime('now')) ON CONFLICT(proxyUrl) DO UPDATE SET lastUsed = datetime('now')");
            $stmt->bindValue(':url', $proxy, SQLITE3_TEXT);
            $stmt->execute();
            
            return $proxy;
        }
    }
    
    return null;
}

function rotateProxy(): ?string {
    $newProxy = getNextProxy();
    if ($newProxy) {
        return $newProxy;
    }
    return null;
}

function markProxyStatus(string $proxyUrl, bool $success): void {
    $db = getDB();
    
    if ($success) {
        $stmt = getStatement("UPDATE proxyStatus SET successCount = successCount + 1, isBlocked = 0 WHERE proxyUrl = :url");
    } else {
        $stmt = getStatement("UPDATE proxyStatus SET failCount = failCount + 1, isBlocked = 1, blockedUntil = datetime('now', '+1 hour') WHERE proxyUrl = :url");
    }
    $stmt->bindValue(':url', $proxyUrl, SQLITE3_TEXT);
    $stmt->execute();
}

// ── Dynamic column addition ──────────────────────────────
function ensureColumns(SQLite3 $db, string $table, array $data): void {
    static $existingColumns = [];

    // Whitelist for table names
    $allowedTables = ['artists', 'collections', 'tracks', 'entityMirrors', 'requestCache', 'rateLimitLog', 'requestHistory', 'proxyStatus', 'requestPattern', 'offlineCache'];
    if (!in_array($table, $allowedTables)) {
        return;
    }

    if (!isset($existingColumns[$table])) {
        $existingCols = [];
        $res = $db->query("PRAGMA table_info($table)");
        while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
            $existingCols[$row['name']] = true;
        }
        $res->finalize();
        $existingColumns[$table] = $existingCols;
    }

    foreach ($data as $col => $value) {
        if (!isset($existingColumns[$table][$col])) {
            // Validate column name (alphanumeric and underscores only)
            if (preg_match('/^[a-zA-Z0-9_]+$/', $col)) {
                $db->exec("ALTER TABLE $table ADD COLUMN `$col` TEXT");
                $existingColumns[$table][$col] = true;
            }
        }
    }
}

// ── Save entities ─────────────────────────────────────────
function saveEntities(SQLite3 $db, string $table, array $entities): void {
    if (empty($entities)) return;

    // Support single entity object
    if (isset($entities['wrapperType']) || isset($entities['artistId']) || isset($entities['collectionId']) || isset($entities['trackId'])) {
        if (!isset($entities[0])) $entities = [$entities];
    }

    $db->exec('BEGIN TRANSACTION');
    foreach ($entities as $entity) {
        if (!is_array($entity)) continue;

        // Normalize IDs in entity data
        foreach (['artistId', 'collectionId', 'trackId'] as $idKey) {
            if (isset($entity[$idKey])) $entity[$idKey] = normalizeId($entity[$idKey]);
        }

        ensureColumns($db, $table, $entity);

        $columns = [];
        foreach (array_keys($entity) as $col) {
             if (preg_match('/^[a-zA-Z0-9_]+$/', $col)) {
                 $columns[] = $col;
             }
        }

        if (empty($columns)) continue;

        $placeholders = array_map(fn($c) => ":$c", $columns);
        $sql = "INSERT OR REPLACE INTO $table (`" . implode('`,`', $columns) . "`) VALUES (" . implode(',', $placeholders) . ")";
        $stmt = $db->prepare($sql);
        foreach ($columns as $col) {
            $val = $entity[$col];
            $type = is_int($val) ? SQLITE3_INTEGER : (is_float($val) ? SQLITE3_FLOAT : SQLITE3_TEXT);
            $stmt->bindValue(":$col", $val, $type);
        }
        $stmt->execute();
    }
    $db->exec('COMMIT');
}

// ── Process API results ──────────────────────────────────
function processResults(SQLite3 $db, array $results): void {
    $artists = $collections = $tracks = [];
    foreach ($results as $item) {
        $wrapper = $item['wrapperType'] ?? '';
        if (($wrapper === 'artist' || (isset($item['artistId']) && !isset($item['collectionId'], $item['trackId']))) && isset($item['artistId'])) {
            $artists[] = $item;
        }
        if (($wrapper === 'collection' || isset($item['collectionId'])) && isset($item['collectionId'], $item['collectionName'])) {
            $collections[] = $item;
        }
        if (($wrapper === 'track' || isset($item['trackId'])) && isset($item['trackId'], $item['trackName'])) {
            $tracks[] = $item;
        }
        if (count($artists) >= BATCH_SIZE) { saveEntities($db, 'artists', $artists); $artists = []; }
        if (count($collections) >= BATCH_SIZE) { saveEntities($db, 'collections', $collections); $collections = []; }
        if (count($tracks) >= BATCH_SIZE) { saveEntities($db, 'tracks', $tracks); $tracks = []; }
    }
    if ($artists) saveEntities($db, 'artists', $artists);
    if ($collections) saveEntities($db, 'collections', $collections);
    if ($tracks) saveEntities($db, 'tracks', $tracks);
}

// ── Cache helpers with adaptive TTL ───────────────────────
function getAdaptiveTTL(): int {
    $db = getDB();
    
    $stmt = getStatement("SELECT successfulRequests, failedRequests FROM rateLimitLog WHERE apiName = 'itunes' LIMIT 1");
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    
    $baseTTL = CACHE_DURATION;
    
    if ($row) {
        $total = $row['successfulRequests'] + $row['failedRequests'];
        if ($total > 0) {
            $successRate = $row['successfulRequests'] / $total;
            
            if ($successRate < 0.5) {
                $baseTTL = CACHE_DURATION * 4;
            } elseif ($successRate < 0.7) {
                $baseTTL = CACHE_DURATION * 2;
            } elseif ($successRate < 0.9) {
                $baseTTL = (int)(CACHE_DURATION * 1.5);
            }
        }
    }
    
    $hour = (int)date('H');
    if ($hour >= 2 && $hour <= 5) {
        $baseTTL = (int)($baseTTL * 0.7);
    } elseif ($hour >= 18 && $hour <= 23) {
        $baseTTL = (int)($baseTTL * 1.3);
    }
    
    return $baseTTL;
}

function extractResultIds(array $results): string {
    $ids = [];
    foreach ($results as $item) {
        $type = null; $id = null;
        if (($item['wrapperType'] ?? '') === 'artist' && isset($item['artistId'])) {
            $type = 'artist'; $id = $item['artistId'];
        } elseif (($item['wrapperType'] ?? '') === 'collection' && isset($item['collectionId'])) {
            $type = 'collection'; $id = $item['collectionId'];
        } elseif (($item['wrapperType'] ?? '') === 'track' && isset($item['trackId'])) {
            $type = 'track'; $id = $item['trackId'];
        }
        if ($type && $id) $ids[] = ['type' => $type, 'id' => $id];
    }
    return json_encode($ids);
}

function saveCacheIds(SQLite3 $db, string $endpoint, array $params, array $results): void {
    $idsJson = extractResultIds($results);
    if ($idsJson === '[]') return;
    $paramsJson = json_encode($params);
    $cacheDuration = CACHE_ADAPTIVE_TTL ? getAdaptiveTTL() : CACHE_DURATION;
    $expires = date('Y-m-d H:i:s', time() + $cacheDuration);
    
    $stmt = getStatement("INSERT OR REPLACE INTO requestCache (endpoint, params, resultIds, expiresAt, lastAccessed, accessCount) VALUES (:ep, :p, :ids, :ex, datetime('now'), 1)");
    $stmt->bindValue(':ep', $endpoint, SQLITE3_TEXT);
    $stmt->bindValue(':p', $paramsJson, SQLITE3_TEXT);
    $stmt->bindValue(':ids', $idsJson, SQLITE3_TEXT);
    $stmt->bindValue(':ex', $expires, SQLITE3_TEXT);
    $stmt->execute();
}

function getCachedResults(SQLite3 $db, string $endpoint, array $params): ?array {
    $paramsJson = json_encode($params);
    $stmt = getStatement("SELECT resultIds, expiresAt FROM requestCache WHERE endpoint=:ep AND params=:p AND expiresAt > datetime('now') LIMIT 1");
    $stmt->bindValue(':ep', $endpoint, SQLITE3_TEXT);
    $stmt->bindValue(':p', $paramsJson, SQLITE3_TEXT);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    if (!$row) return null;
    
    // Update access count
    $stmt = getStatement("UPDATE requestCache SET accessCount = accessCount + 1, lastAccessed = datetime('now') WHERE endpoint=:ep AND params=:p");
    $stmt->bindValue(':ep', $endpoint, SQLITE3_TEXT);
    $stmt->bindValue(':p', $paramsJson, SQLITE3_TEXT);
    $stmt->execute();
    
    if (CACHE_ADAPTIVE_TTL) {
        $timeLeft = strtotime($row['expiresAt']) - time();
        if ($timeLeft < 3600) {
            $newExpiry = date('Y-m-d H:i:s', time() + getAdaptiveTTL());
            $stmt = getStatement("UPDATE requestCache SET expiresAt = :ex WHERE endpoint=:ep AND params=:p");
            $stmt->bindValue(':ex', $newExpiry, SQLITE3_TEXT);
            $stmt->bindValue(':ep', $endpoint, SQLITE3_TEXT);
            $stmt->bindValue(':p', $paramsJson, SQLITE3_TEXT);
            $stmt->execute();
        }
    }
    
    $ids = json_decode($row['resultIds'], true);
    if (!$ids) return null;
    $results = [];
    foreach ($ids as $entry) {
        $entity = fetchEntityById($db, $entry['type'], $entry['id']);
        if ($entity) $results[] = $entity;
    }
    return ['resultCount' => count($results), 'results' => $results];
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

// ── Offline Cache Management ──────────────────────────────
function saveToOfflineCache(string $entityType, string $entityId, array $data): void {
    $db = getDB();
    $entityId = normalizeId($entityId);
    $expiresAt = date('Y-m-d H:i:s', time() + CACHE_DURATION * 2);
    
    $stmt = getStatement("INSERT OR REPLACE INTO offlineCache (entityType, entityId, data, expiresAt) VALUES (:type, :id, :data, :expires)");
    $stmt->bindValue(':type', $entityType, SQLITE3_TEXT);
    $stmt->bindValue(':id', $entityId, SQLITE3_TEXT);
    $stmt->bindValue(':data', json_encode($data), SQLITE3_TEXT);
    $stmt->bindValue(':expires', $expiresAt, SQLITE3_TEXT);
    $stmt->execute();
}

function getFromOfflineCache(string $entityType, string $entityId): ?array {
    $db = getDB();
    $entityId = normalizeId($entityId);
    $stmt = getStatement("SELECT data FROM offlineCache WHERE entityType=:type AND entityId=:id AND expiresAt > datetime('now')");
    $stmt->bindValue(':type', $entityType, SQLITE3_TEXT);
    $stmt->bindValue(':id', $entityId, SQLITE3_TEXT);
    $result = $stmt->execute();
    $row = $result->fetchArray(SQLITE3_ASSOC);
    
    if ($row) {
        return json_decode($row['data'], true);
    }
    return null;
}

// ── Mirror URL helpers with quality support ───────────────────────────────────

/**
 * Get the best available audio quality URL from mirrors
 * @param array $mirrors Array of mirrors
 * @return array|null Returns array with 'url' and 'quality' keys or null if none found
 */
function getBestAvailableQuality(array $mirrors): ?array {
    $priorities = ['320', '192', '128'];
    
    foreach ($priorities as $quality) {
        // Check for audioUrl_320 format
        $key = 'audioUrl_' . $quality;
        if (isset($mirrors[$key]) && !empty($mirrors[$key]['url'])) {
            return [
                'url' => $mirrors[$key]['url'],
                'quality' => $quality
            ];
        }
    }
    
    // Check for legacy audioUrl without quality
    if (isset($mirrors['audioUrl']) && !empty($mirrors['audioUrl']['url'])) {
        return [
            'url' => $mirrors['audioUrl']['url'],
            'quality' => $mirrors['audioUrl']['quality'] ?? DEFAULT_AUDIO_QUALITY
        ];
    }
    
    return null;
}

/**
 * Get the specific quality audio URL if requested
 * @param array $mirrors Array of mirrors
 * @param string $requestedQuality Requested quality (320, 192, 128)
 * @return array|null Returns array with 'url' and 'quality' keys or null if not found
 */
function getQualityAudioUrl(array $mirrors, string $requestedQuality): ?array {
    $key = 'audioUrl_' . $requestedQuality;
    if (isset($mirrors[$key]) && !empty($mirrors[$key]['url'])) {
        return [
            'url' => $mirrors[$key]['url'],
            'quality' => $requestedQuality
        ];
    }
    return null;
}

function getAudioUrlTypeWithQuality(string $urlType, ?string $quality = null): string {
    if ($urlType !== 'audioUrl' || !$quality) {
        return $urlType;
    }
    
    if (!in_array($quality, SUPPORTED_AUDIO_QUALITIES)) {
        $quality = DEFAULT_AUDIO_QUALITY;
    }
    
    return $urlType . '_' . $quality;
}

function extractQualityFromUrlType(string $urlType): ?string {
    if (strpos($urlType, 'audioUrl_') === 0) {
        $quality = substr($urlType, 9);
        if (in_array($quality, SUPPORTED_AUDIO_QUALITIES)) {
            return $quality;
        }
    }
    return null;
}

/**
 * Attach mirrors to entity with proper audioUrl handling
 * @param array &$entity Entity reference to attach mirrors to
 * @param string $type Entity type (artist, collection, track)
 * @param string $id Entity ID
 * @param string|null $requestedQuality Optional requested quality parameter
 */
function attachMirrors(array &$entity, string $type, string $id, ?string $requestedQuality = null, string $platform = 'bale'): void {
    $db = getDB();
    $id = normalizeId($id);
    
    $stmt = getStatement("SELECT urlType, mirrorUrl, quality FROM entityMirrors WHERE entityType=:t AND entityId=:id AND platform=:p");
    $stmt->bindValue(':t', $type, SQLITE3_TEXT);
    $stmt->bindValue(':id', $id, SQLITE3_TEXT);
    $stmt->bindValue(':p', $platform, SQLITE3_TEXT);
    $res = $stmt->execute();
    
    $mirrors = [];
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
        $urlType = $row['urlType'];
        $mirrorData = ['url' => $row['mirrorUrl']];
        
        $quality = extractQualityFromUrlType($urlType);
        if ($quality) {
            $mirrorData['quality'] = $quality;
        } elseif ($row['quality']) {
            $mirrorData['quality'] = $row['quality'];
        }
        
        $mirrors[$urlType] = $mirrorData;
    }
    
    // Handle audioUrl based on requested quality parameter

    if ($requestedQuality && in_array($requestedQuality, SUPPORTED_AUDIO_QUALITIES)) {
        // Specific quality requested - must be equal to audioUrl with that quality if exists
        $specificAudio = getQualityAudioUrl($mirrors, $requestedQuality);
        if ($specificAudio) {
            $mirrors['audioUrl'] = $specificAudio;
        } else {
            // If requested quality doesn't exist, use highest available
            $bestAudio = getBestAvailableQuality($mirrors);
            if ($bestAudio) {
                $mirrors['audioUrl'] = $bestAudio;
            }
        }
    } else {
        // No specific quality requested - audioUrl must be highest available quality
        $bestAudio = getBestAvailableQuality($mirrors);
        if ($bestAudio) {
            $mirrors['audioUrl'] = $bestAudio;
        }
    }
    
    $entity['mirrorUrls'] = $mirrors ?: new stdClass();
    
    // Preserve original artwork URLs
    foreach ($mirrors as $urlType => $data) {
        if ($urlType === 'artworkUrl') {
            if (isset($entity['artworkUrl30'])) $entity['artworkUrl30'] = $data['url'];
            if (isset($entity['artworkUrl60'])) $entity['artworkUrl60'] = $data['url'];
            if (isset($entity['artworkUrl100'])) $entity['artworkUrl100'] = $data['url'];
        }
    }
}

function setMirrorUrl(SQLite3 $db, string $type, string $id, string $urlType, string $mirrorUrl, ?string $quality = null, string $platform = 'bale'): array {
    if (!in_array($urlType, ['artworkUrl','previewUrl','audioUrl'])) return ['success' => false, 'error' => 'Invalid urlType'];
    if (!filter_var($mirrorUrl, FILTER_VALIDATE_URL) && strpos($mirrorUrl, 'tg://') !== 0) return ['success' => false, 'error' => 'Invalid URL'];
    
    $id = normalizeId($id);
    ensureEntityExists($db, $type, $id);

    $actualUrlType = getAudioUrlTypeWithQuality($urlType, $quality);
    $qualityValue = ($urlType === 'audioUrl') ? $quality : null;
    
    $stmt = getStatement("INSERT OR REPLACE INTO entityMirrors (entityType, entityId, urlType, mirrorUrl, quality, platform, updatedAt)
                          VALUES (:t,:id,:ut,:url,:q,:p, datetime('now'))");
    $stmt->bindValue(':t', $type, SQLITE3_TEXT);
    $stmt->bindValue(':id', $id, SQLITE3_TEXT);
    $stmt->bindValue(':ut', $actualUrlType, SQLITE3_TEXT);
    $stmt->bindValue(':url', $mirrorUrl, SQLITE3_TEXT);
    $stmt->bindValue(':q', $qualityValue, SQLITE3_TEXT);
    $stmt->bindValue(':p', $platform, SQLITE3_TEXT);
    $stmt->execute();
    
    return ['success' => true, 'message' => "Mirror $urlType set" . ($quality ? " for quality $quality" : "") . " on platform $platform"];
}

function getMirrorUrls(SQLite3 $db, string $type, string $id, ?string $urlType = null, ?string $quality = null, string $platform = 'bale'): array {
    $id = normalizeId($id);
    $sql = "SELECT urlType, mirrorUrl, quality FROM entityMirrors WHERE entityType=:t AND entityId=:id AND platform=:p";
    $stmt = getStatement($sql);
    $stmt->bindValue(':t', $type, SQLITE3_TEXT);
    $stmt->bindValue(':id', $id, SQLITE3_TEXT);
    $stmt->bindValue(':p', $platform, SQLITE3_TEXT);
    $res = $stmt->execute();
    
    $mirrors = [];
    while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
        $rowUrlType = $row['urlType'];
        
        if ($urlType && $quality) {
            $expectedUrlType = getAudioUrlTypeWithQuality($urlType, $quality);

            if ($rowUrlType !== $expectedUrlType) {
                continue;
            }else{
            }
        }
        $displayUrlType = $rowUrlType;
        $mirrors[$displayUrlType] = ['url' => $row['mirrorUrl']];
        if ($row['quality']) {
            if ($row['quality'] == $quality){
                $mirrors['audioUrl'] = ['url' => $row['mirrorUrl']];
                $mirrors['audioUrl']['quality'] = $row['quality'];
            }
            $mirrors[$displayUrlType]['quality'] = $row['quality'];
        }
    }
    
    // CRITICAL FIX: ALWAYS add the highest quality audioUrl when requesting generic audioUrl
    if(!$quality){
    // This ensures audioUrl field is always present;
        $bestAudio = getBestAvailableQuality($mirrors);
        if ($bestAudio) {
            $mirrors['audioUrl'] = $bestAudio;
        } elseif (!isset($mirrors['audioUrl'])) {
            // If no audio URLs exist at all, return empty but still include the field
            $mirrors['audioUrl'] = null;
        }
    
    
    // Ensure audioUrl is always present even when not specifically requested
    if (!isset($mirrors['audioUrl']) && !$urlType) {
        $bestAudio = getBestAvailableQuality($mirrors);
        if ($bestAudio) {
            $mirrors['audioUrl'] = $bestAudio;
        }
    }
    }
    
    return [
        'success' => true, 
        'entityType' => $type, 
        'entityId' => $id, 
        'mirrors' => !empty($mirrors) ? $mirrors : new stdClass()
    ];
}

function deleteMirrorUrl(SQLite3 $db, string $type, string $id, ?string $urlType = null, ?string $quality = null, string $platform = 'bale'): array {
    $id = normalizeId($id);
    if ($urlType) {
        $actualUrlType = getAudioUrlTypeWithQuality($urlType, $quality);
        $stmt = getStatement("DELETE FROM entityMirrors WHERE entityType=:t AND entityId=:id AND urlType=:ut AND platform=:p");
        $stmt->bindValue(':ut', $actualUrlType, SQLITE3_TEXT);
    } else {
        $stmt = getStatement("DELETE FROM entityMirrors WHERE entityType=:t AND entityId=:id AND platform=:p");
    }
    $stmt->bindValue(':t', $type, SQLITE3_TEXT);
    $stmt->bindValue(':id', $id, SQLITE3_TEXT);
    $stmt->bindValue(':p', $platform, SQLITE3_TEXT);
    $stmt->execute();
    
    $message = $urlType ? "Mirror '$urlType'" . ($quality ? " for quality $quality" : "") . " deleted" : 'All mirrors deleted';
    return ['success' => true, 'message' => $message];
}

function getLyrics(SQLite3 $db, string $trackId): array {
    $trackId = normalizeId($trackId);
    $stmt = getStatement("SELECT lyrics FROM tracks WHERE trackId = :id");
    $stmt->bindValue(':id', $trackId, SQLITE3_TEXT);
    $res = $stmt->execute();
    $row = $res->fetchArray(SQLITE3_ASSOC);

    if ($row && !empty($row['lyrics'])) {
        return ['success' => true, 'trackId' => $trackId, 'lyrics' => json_decode($row['lyrics'], true)];
    }
    return ['success' => false, 'error' => 'Lyrics not found'];
}

function saveLyrics(SQLite3 $db, string $trackId, $lyrics): array {
    $trackId = normalizeId($trackId);
    ensureEntityExists($db, 'track', $trackId);

    $lyricsJson = is_string($lyrics) ? $lyrics : json_encode($lyrics);

    // Test if it's valid JSON
    if (json_decode($lyricsJson) === null) {
        return ['success' => false, 'error' => 'Invalid JSON for lyrics'];
    }

    ensureColumns($db, 'tracks', ['lyrics' => '']);

    $stmt = getStatement("UPDATE tracks SET lyrics = :lyrics WHERE trackId = :id");
    $stmt->bindValue(':lyrics', $lyricsJson, SQLITE3_TEXT);
    $stmt->bindValue(':id', $trackId, SQLITE3_TEXT);
    $stmt->execute();

    return ['success' => true, 'message' => 'Lyrics saved successfully'];
}

// ── Fetch single entity from DB ───────────────────────────
function fetchEntityById(SQLite3 $db, string $type, string $id, ?string $quality = null, string $platform = 'bale'): ?array {
    $id = normalizeId($id);
    $table = match ($type) {
        'artist' => 'artists',
        'collection' => 'collections',
        'track' => 'tracks',
        default => null
    };
    if (!$table) return null;
    $idCol = $type . 'Id';
    $stmt = getStatement("SELECT * FROM $table WHERE $idCol = :id");
    $stmt->bindValue(':id', $id, SQLITE3_TEXT);
    $row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
    if ($row) {
        attachMirrors($row, $type, $id, $quality, $platform);
        return $row;
    }
    return null;
}

function ensureEntityExists(SQLite3 $db, string $type, string $id): void {
    $id = normalizeId($id);
    $table = match ($type) {
        'artist' => 'artists',
        'collection' => 'collections',
        'track' => 'tracks',
        default => null
    };
    if (!$table) return;

    $idCol = $type . 'Id';
    $stmt = $db->prepare("INSERT OR IGNORE INTO $table ($idCol) VALUES (:id)");
    $stmt->bindValue(':id', $id, SQLITE3_TEXT);
    $stmt->execute();
}

// ── iTunes API call with advanced rate limit handling ─────
function makeApiRequest(string $url, int $retryCount = 0): ?array {
    global $lastRequestTime;
    
    if (!checkRateLimit()) {
        if ($retryCount < RATE_LIMIT_MAX_RETRIES) {
            $delay = RATE_LIMIT_BASE_DELAY * pow(2, $retryCount) + mt_rand(0, 1000000) / 1000000;
            usleep($delay * 1000000);
            return makeApiRequest($url, $retryCount + 1);
        }
        return null;
    }
    
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT => 15,
        CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_SSL_VERIFYPEER => false,
        CURLOPT_ENCODING => '',
        CURLOPT_HEADER => true,
        CURLOPT_FORBID_REUSE => true,
        CURLOPT_FRESH_CONNECT => true,
    ]);
    
    global $userAgents;
    if (ENABLE_USER_AGENT_ROTATION) {
        $userAgent = $userAgents[array_rand($userAgents)];
        curl_setopt($ch, CURLOPT_USERAGENT, $userAgent);
    }
    
    $currentProxy = null;
    if (USE_PROXY_ROTATION) {
        $currentProxy = getNextProxy();
        if ($currentProxy) {
            curl_setopt($ch, CURLOPT_PROXY, $currentProxy);
            
            if (preg_match('/@/', $currentProxy)) {
                curl_setopt($ch, CURLOPT_PROXYUSERPWD, substr($currentProxy, strpos($currentProxy, '://') + 3, strrpos($currentProxy, '@') - strpos($currentProxy, '://') - 3));
            }
        }
    }
    
    if (ENABLE_IP_SPOOFING) {
        $ip = mt_rand(1, 255) . '.' . mt_rand(0, 255) . '.' . mt_rand(0, 255) . '.' . mt_rand(1, 255);
        curl_setopt($ch, CURLOPT_HTTPHEADER, [
            'X-Forwarded-For: ' . $ip,
            'X-Real-IP: ' . $ip,
            'Client-IP: ' . $ip,
            'Forwarded: for=' . $ip,
        ]);
    }
    
    $randomDelay = mt_rand(100000, 500000);
    usleep($randomDelay);
    
    curl_setopt($ch, CURLOPT_URL, $url);
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $headerSize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
    $headers = substr($response, 0, $headerSize);
    $body = substr($response, $headerSize);
    
    $db = getDB();
    $stmt = getStatement("INSERT INTO requestHistory (requestTime, endpoint, statusCode, responseTime, userAgent, success) VALUES (datetime('now'), :ep, :code, :time, :ua, :success)");
    $stmt->bindValue(':ep', $url, SQLITE3_TEXT);
    $stmt->bindValue(':code', $httpCode, SQLITE3_INTEGER);
    $stmt->bindValue(':time', curl_getinfo($ch, CURLINFO_TOTAL_TIME_T), SQLITE3_INTEGER);
    $stmt->bindValue(':ua', curl_getinfo($ch, CURLINFO_EFFECTIVE_URL), SQLITE3_TEXT);
    $stmt->bindValue(':success', $httpCode === 200 ? 1 : 0, SQLITE3_INTEGER);
    $stmt->execute();
    
    curl_close($ch);
    
    switch ($httpCode) {
        case 200:
            resetRateLimit('itunes', true);
            if ($currentProxy) markProxyStatus($currentProxy, true);
            return json_decode($body, true);
            
        case 429:
            handleRateLimitHit('itunes');
            if ($currentProxy) markProxyStatus($currentProxy, false);
            
            $retryAfter = 0;
            if (preg_match('/Retry-After: (\d+)/i', $headers, $matches)) {
                $retryAfter = (int)$matches[1];
            }
            
            if ($retryAfter > 0) sleep($retryAfter);
            
            if ($retryCount < RATE_LIMIT_MAX_RETRIES) {
                $delay = RATE_LIMIT_BASE_DELAY * pow(3, $retryCount) + mt_rand(0, 2000000) / 1000000;
                usleep($delay * 1000000);
                
                if (USE_PROXY_ROTATION) rotateProxy();
                return makeApiRequest($url, $retryCount + 1);
            }
            return null;
            
        case 403:
        case 503:
            if ($currentProxy) markProxyStatus($currentProxy, false);
            if ($retryCount < RATE_LIMIT_MAX_RETRIES) {
                rotateProxy();
                $delay = mt_rand(5, 15);
                sleep($delay);
                return makeApiRequest($url, $retryCount + 1);
            }
            return null;
            
        default:
            if ($retryCount < RATE_LIMIT_MAX_RETRIES) {
                $delay = RATE_LIMIT_BASE_DELAY * ($retryCount + 1) + mt_rand(0, 1000000) / 1000000;
                usleep($delay * 1000000);
                return makeApiRequest($url, $retryCount + 1);
            }
            return null;
    }
}

// ── Search / Lookup with fallback to local DB ──────────────
function makeApiRequestWithFallback(string $url, array $params = [], int $retryCount = 0): array {
    $result = makeApiRequest($url, $retryCount);
    
    if ($result && isset($result['results'])) {
        foreach ($result['results'] as $item) {
            $type = null;
            if (isset($item['wrapperType'])) {
                $type = $item['wrapperType'];
            } elseif (isset($item['artistId']) && !isset($item['collectionId'])) {
                $type = 'artist';
            } elseif (isset($item['collectionId']) && !isset($item['trackId'])) {
                $type = 'collection';
            } elseif (isset($item['trackId'])) {
                $type = 'track';
            }
            
            if ($type && isset($item[$type . 'Id'])) {
                saveToOfflineCache($type, $item[$type . 'Id'], $item);
            }
        }
        return $result;
    }
    
    if (OFFLINE_FALLBACK_ENABLED && isset($params['id'])) {
        $ids = explode(',', $params['id']);
        $results = [];
        
        foreach ($ids as $idStr) {
            $id = normalizeId(trim($idStr));
            foreach (['artist', 'collection', 'track'] as $type) {
                $cached = getFromOfflineCache($type, $id);
                if ($cached) {
                    attachMirrors($cached, $type, $id);
                    $results[] = $cached;
                    break;
                }
            }
        }
        
        if (!empty($results)) {
            return ['resultCount' => count($results), 'results' => $results, 'fromCache' => true];
        }
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
        $limit = min(intval($params['limit'] ?? 50), 200);
        
        if ($entity === 'all' || $entity === 'musicArtist' || $entity === 'artist') {
            $stmt = getStatement("SELECT *, 'artist' as wrapperType FROM artists WHERE LOWER(artistName) LIKE :term LIMIT :limit");
            $stmt->bindValue(':term', $term, SQLITE3_TEXT);
            $stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
            $res = $stmt->execute();
            while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
                attachMirrors($row, 'artist', $row['artistId'], null, $platform);
                $results[] = $row;
            }
        }
        
        if ($entity === 'all' || $entity === 'album' || $entity === 'collection') {
            $stmt = getStatement("SELECT *, 'collection' as wrapperType FROM collections WHERE LOWER(collectionName) LIKE :term LIMIT :limit");
            $stmt->bindValue(':term', $term, SQLITE3_TEXT);
            $stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
            $res = $stmt->execute();
            while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
                attachMirrors($row, 'collection', $row['collectionId'], null, $platform);
                $results[] = $row;
            }
        }
        
        if ($entity === 'all' || $entity === 'musicTrack' || $entity === 'song' || $entity === 'track') {
            $stmt = getStatement("SELECT *, 'track' as wrapperType FROM tracks WHERE LOWER(trackName) LIKE :term LIMIT :limit");
            $stmt->bindValue(':term', $term, SQLITE3_TEXT);
            $stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
            $res = $stmt->execute();
            while ($row = $res->fetchArray(SQLITE3_ASSOC)) {
                attachMirrors($row, 'track', $row['trackId'], null, $platform);
                $results[] = $row;
            }
        }
    } elseif (isset($params['id'])) {
        $ids = explode(',', $params['id']);
        foreach ($ids as $idStr) {
            $id = normalizeId(trim($idStr));
            foreach (['artist', 'collection', 'track'] as $type) {
                $entity = fetchEntityById($db, $type, $id, null, $platform);
                if ($entity) {
                    $results[] = $entity;
                    break;
                }
            }
        }
    }
    
    return ['resultCount' => count($results), 'results' => $results, 'fromCache' => true];
}

function searchiTunes(SQLite3 $db, array $params): array {
    if (isset($params['term'])) {
        $params['term'] = trim(strtolower($params['term']));
    }
    
    $cached = getCachedResults($db, 'search', $params);
    if ($cached) return $cached;
    
    $url = ITUNES_SEARCH_API . '?' . http_build_query($params);
    $response = makeApiRequestWithFallback($url, $params);
    
    if ($response && isset($response['results']) && $response['resultCount'] > 0) {
        if (!isset($response['fromCache'])) {
            processResults($db, $response['results']);
            saveCacheIds($db, 'search', $params, $response['results']);
        }
        $platform = $params['platform'] ?? 'bale';
        foreach ($response['results'] as &$item) {
            $quality = $params['quality'] ?? null;
            enrichItemWithMirrors($item, $quality, $platform);
        }
    }
    
    return $response ?? ['resultCount' => 0, 'results' => []];
}

function lookupiTunes(SQLite3 $db, array $params): array {
    $cached = getCachedResults($db, 'lookup', $params);
    if ($cached) return $cached;
    
    $apiParams = $params;
    if (isset($apiParams['id'])) {
        $ids = explode(',', $apiParams['id']);
        $denormalizedIds = array_map('denormalizeId', array_map('trim', $ids));
        $apiParams['id'] = implode(',', $denormalizedIds);
    }

    $url = ITUNES_LOOKUP_API . '?' . http_build_query($apiParams);
    $response = makeApiRequestWithFallback($url, $params);
    
    if ($response && isset($response['results']) && $response['resultCount'] > 0) {
        if (!isset($response['fromCache'])) {
            processResults($db, $response['results']);
            saveCacheIds($db, 'lookup', $params, $response['results']);
        }
        $platform = $params['platform'] ?? 'bale';
        foreach ($response['results'] as &$item) {
            $quality = $params['quality'] ?? null;
            enrichItemWithMirrors($item, $quality, $platform);
        }
    }
    
    return $response ?? ['resultCount' => 0, 'results' => []];
}

function enrichItemWithMirrors(array &$item, ?string $requestedQuality = null, string $platform = 'bale'): void {
    $wrapper = $item['wrapperType'] ?? '';
    if ($wrapper === 'artist' && isset($item['artistId'])) {
        attachMirrors($item, 'artist', $item['artistId'], $requestedQuality, $platform);
    } elseif ($wrapper === 'collection' && isset($item['collectionId'])) {
        attachMirrors($item, 'collection', $item['collectionId'], $requestedQuality, $platform);
    } elseif ($wrapper === 'track' && isset($item['trackId'])) {
        attachMirrors($item, 'track', $item['trackId'], $requestedQuality, $platform);
    }
}

// ── HTTP request handling ────────────────────────────────
function enableCompression(): void {
    if (ENABLE_GZIP && !headers_sent() && extension_loaded('zlib') && strpos($_SERVER['HTTP_ACCEPT_ENCODING'] ?? '', 'gzip') !== false) {
        ini_set('zlib.output_compression', 'On');
        ini_set('zlib.output_compression_level', '6');
    }
}

function respond($data, int $statusCode = 200): void {
    if (!headers_sent()) {
        http_response_code($statusCode);
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
    
    if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
        respond([], 200);
    }

    $db = getDB();
    cleanExpiredCache($db);

    $path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    $scriptDir = dirname($_SERVER['SCRIPT_NAME']);
    if ($scriptDir !== '/' && strpos($path, $scriptDir) === 0) {
        $path = substr($path, strlen($scriptDir));
    }
    $path = rtrim($path, '/') ?: '/';
    $method = $_SERVER['REQUEST_METHOD'];

    $params = [];
    if ($method === 'GET') {
        $params = $_GET;
    } else {
        $input = file_get_contents('php://input');
        $decoded = json_decode($input, true);
        $params = is_array($decoded) ? $decoded : $_POST;
    }

    if (isset($params['term'])) {
        $params['term'] = trim(strtolower($params['term']));
    }
    
    // Extract quality parameter (from GET, POST, or Quality header)
    $quality = null;
    if (isset($_SERVER['HTTP_QUALITY'])) {
        $quality = $_SERVER['HTTP_QUALITY'];
    } elseif (isset($params['quality'])) {
        $quality = $params['quality'];
    }
    
    // Validate quality parameter
    if ($quality && !in_array($quality, SUPPORTED_AUDIO_QUALITIES)) {
        $quality = DEFAULT_AUDIO_QUALITY;
    }
    
    // Pass quality to search/lookup functions
    if ($quality) {
        $params['quality'] = $quality;
    }

    $platform = $params['platform'] ?? 'bale';

    try {
        switch ($path) {
            case '/search':
                if (empty($params['term'])) throw new Exception('Missing term', 400);
                $response = searchiTunes($db, $params);
                break;
                
            case '/lookup':
                if (empty($params['id'])) throw new Exception('Missing id', 400);
                $response = lookupiTunes($db, $params);
                break;
                
            case '/artist':
                if (empty($params['id'])) throw new Exception('Missing id', 400);
                $id = normalizeId($params['id']);
                $artist = fetchEntityById($db, 'artist', $id, $quality, $platform);
                if (!$artist) {
                    $lookup = lookupiTunes($db, ['id' => $id, 'quality' => $quality, 'platform' => $platform]);
                    $artist = $lookup['results'][0] ?? null;
                    if ($artist) attachMirrors($artist, 'artist', $id, $quality, $platform);
                }
                if (!$artist) throw new Exception('Artist not found', 404);
                $response = ['resultCount' => 1, 'results' => [$artist]];
                break;
                
            case '/album':
                if (empty($params['id'])) throw new Exception('Missing id', 400);
                $id = normalizeId($params['id']);
                $album = fetchEntityById($db, 'collection', $id, $quality, $platform);
                if (!$album) {
                    $lookup = lookupiTunes($db, ['id' => $id, 'quality' => $quality, 'platform' => $platform]);
                    $album = $lookup['results'][0] ?? null;
                    if ($album) attachMirrors($album, 'collection', $id, $quality, $platform);
                }
                if (!$album) throw new Exception('Album not found', 404);
                $response = ['resultCount' => 1, 'results' => [$album]];
                break;
                
            case '/track':
                if (empty($params['id'])) throw new Exception('Missing id', 400);
                $id = normalizeId($params['id']);
                $track = fetchEntityById($db, 'track', $id, $quality, $platform);
                if (!$track) {
                    $lookup = lookupiTunes($db, ['id' => $id, 'quality' => $quality, 'platform' => $platform]);
                    $track = $lookup['results'][0] ?? null;
                    if ($track) attachMirrors($track, 'track', $id, $quality, $platform);
                }
                if (!$track) throw new Exception('Track not found', 404);
                $response = ['resultCount' => 1, 'results' => [$track]];
                break;
                
            case '/mirror/set':
                if ($method !== 'POST') throw new Exception('Method not allowed', 405);
                $response = setMirrorUrl($db, $params['entityType'] ?? '', $params['entityId'] ?? '',
                                         $params['urlType'] ?? '', $params['mirrorUrl'] ?? '', 
                                         $params['quality'] ?? null, $platform);
                break;
                
            case '/mirror/get':
                $response = getMirrorUrls($db, $params['entityType'] ?? '', $params['entityId'] ?? '',
                                         $params['urlType'] ?? $params['url_type'] ?? null, $params['quality'] ?? null, $platform);
                break;
                
            case '/mirror/delete':
                if (!in_array($method, ['POST', 'DELETE'])) throw new Exception('Method not allowed', 405);
                $response = deleteMirrorUrl($db, $params['entityType'] ?? '', $params['entityId'] ?? '',
                                           $params['urlType'] ?? null, $params['quality'] ?? null, $platform);
                break;

            case '/artist/save':
            case '/artist/set':
                if ($method !== 'POST') throw new Exception('Method not allowed', 405);
                saveEntities($db, 'artists', $params);
                $response = ['success' => true, 'message' => 'Artist(s) saved'];
                break;

            case '/album/save':
            case '/album/set':
            case '/collection/save':
            case '/collection/set':
                if ($method !== 'POST') throw new Exception('Method not allowed', 405);
                saveEntities($db, 'collections', $params);
                $response = ['success' => true, 'message' => 'Album(s) saved'];
                break;

            case '/track/save':
            case '/track/set':
                if ($method !== 'POST') throw new Exception('Method not allowed', 405);
                saveEntities($db, 'tracks', $params);
                $response = ['success' => true, 'message' => 'Track(s) saved'];
                break;

            case '/lyrics/get':
                if (empty($params['id']) && empty($params['trackId'])) throw new Exception('Missing track id', 400);
                $response = getLyrics($db, $params['id'] ?? $params['trackId']);
                break;

            case '/lyrics/save':
            case '/lyrics/set':
                if ($method !== 'POST') throw new Exception('Method not allowed', 405);
                if ((empty($params['id']) && empty($params['trackId'])) || empty($params['lyrics'])) throw new Exception('Missing parameters', 400);
                $response = saveLyrics($db, $params['id'] ?? $params['trackId'], $params['lyrics']);
                break;
                
            default:
                throw new Exception('Endpoint not found', 404);
        }
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage()], $e->getCode() ?: 500);
    }

    respond($response);
}

// ── Run ──────────────────────────────────────────────────
try {
    handleRequest();
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['success' => false, 'error' => 'Internal server error', 'message' => $e->getMessage()]);
}