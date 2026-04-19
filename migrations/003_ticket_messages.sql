CREATE TABLE IF NOT EXISTS ticket_messages (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id                INTEGER NOT NULL,
    msg_type                 TEXT NOT NULL,
    support_group_message_id INTEGER NOT NULL,
    created_at_utc           TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ticket_messages_msg_id
    ON ticket_messages(support_group_message_id);

CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_type
    ON ticket_messages(ticket_id, msg_type);
