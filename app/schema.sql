CREATE TABLE IF NOT EXISTS webhook_events (
    id CHAR(64) NOT NULL PRIMARY KEY,
    page_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    payload JSON NOT NULL,
    received_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_events_page_received (page_id, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    page_id VARCHAR(64) NOT NULL,
    meta_message_id VARCHAR(255) NOT NULL,
    sender_id VARCHAR(64),
    recipient_id VARCHAR(64),
    timestamp_ms BIGINT,
    body_text LONGTEXT,
    attachments JSON NOT NULL,
    is_echo BOOLEAN NOT NULL DEFAULT FALSE,
    raw_event_id CHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_messages_meta (page_id, meta_message_id),
    INDEX idx_messages_page_time (page_id, timestamp_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS comments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    page_id VARCHAR(64) NOT NULL,
    meta_comment_id VARCHAR(255) NOT NULL,
    meta_post_id VARCHAR(255),
    author_id VARCHAR(64),
    body_text LONGTEXT,
    verb VARCHAR(32) NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    event_timestamp BIGINT NOT NULL DEFAULT 0,
    raw_event_id CHAR(64) NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_comments_meta (page_id, meta_comment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
