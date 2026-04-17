CREATE TABLE IF NOT EXISTS ingest_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    update_id INTEGER NOT NULL UNIQUE,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    normalized_json TEXT NOT NULL,
    sheets_row_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    synced_at_utc TEXT,
    UNIQUE(chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_ingest_events_status_id
    ON ingest_events(status, id);

CREATE TABLE IF NOT EXISTS discussion_thread_mappings (
    discussion_chat_id INTEGER NOT NULL,
    message_thread_id INTEGER NOT NULL,
    channel_chat_id INTEGER,
    channel_post_id INTEGER,
    root_message_id INTEGER,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (discussion_chat_id, message_thread_id)
);
