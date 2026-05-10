ALTER TABLE tickets ADD COLUMN suppressed_direct_message_id INTEGER;
ALTER TABLE tickets ADD COLUMN suppressed_direct_until_utc TEXT;

CREATE INDEX IF NOT EXISTS idx_tickets_direct_suppression
    ON tickets(user_chat_id, user_message_thread_id, suppressed_direct_message_id)
    WHERE source_type = 'direct' AND suppressed_direct_message_id IS NOT NULL;
