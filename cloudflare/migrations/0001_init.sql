CREATE TABLE IF NOT EXISTS settings (
  id INTEGER PRIMARY KEY CHECK (id=1),
  enabled INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1
);
INSERT OR IGNORE INTO settings(id,enabled,version) VALUES(1,1,1);
CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY,
  machine_hash TEXT NOT NULL DEFAULT '',
  windows_user TEXT NOT NULL DEFAULT '',
  hostname TEXT NOT NULL DEFAULT '',
  app_version TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','approved','blocked')),
  last_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);
