CREATE TABLE IF NOT EXISTS webhook_events (
    id TEXT NOT NULL PRIMARY KEY,
    page_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_events_page_received ON webhook_events (page_id, received_at);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    page_id TEXT NOT NULL,
    meta_message_id TEXT NOT NULL,
    sender_id TEXT,
    recipient_id TEXT,
    timestamp_ms INTEGER,
    body_text TEXT,
    attachments TEXT NOT NULL,
    is_echo INTEGER NOT NULL DEFAULT 0,
    raw_event_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE (page_id, meta_message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_page_time ON messages (page_id, timestamp_ms);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    page_id TEXT NOT NULL,
    meta_comment_id TEXT NOT NULL,
    meta_post_id TEXT,
    author_id TEXT,
    body_text TEXT,
    verb TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    event_timestamp INTEGER NOT NULL DEFAULT 0,
    raw_event_id TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE (page_id, meta_comment_id)
);
