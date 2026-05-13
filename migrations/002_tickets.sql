CREATE TABLE IF NOT EXISTS tickets (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_code             TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'new',
    source_type             TEXT NOT NULL,
    user_id                 INTEGER NOT NULL,
    username                TEXT,
    first_name              TEXT,
    user_chat_id            INTEGER NOT NULL,
    user_message_id         INTEGER NOT NULL,
    user_message_thread_id  INTEGER,
    user_message_date_utc   TEXT,
    user_message_text       TEXT,
    support_group_message_id INTEGER,
    answer_message_id       INTEGER,
    created_at_utc          TEXT NOT NULL,
    reacted_at_utc          TEXT,
    reacted_by_user_id      INTEGER,
    answered_at_utc         TEXT,
    closed_at_utc           TEXT,
    closed_by_user_id       INTEGER,
    sheets_synced           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tickets_status
    ON tickets(status);

CREATE INDEX IF NOT EXISTS idx_tickets_support_msg
    ON tickets(support_group_message_id)
    WHERE support_group_message_id IS NOT NULL;
