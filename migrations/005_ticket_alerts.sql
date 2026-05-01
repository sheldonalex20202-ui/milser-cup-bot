CREATE TABLE IF NOT EXISTS ticket_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    alert_type TEXT NOT NULL,
    sent_at_utc TEXT NOT NULL,
    support_group_message_id INTEGER,
    UNIQUE(ticket_id, alert_type)
);

CREATE INDEX IF NOT EXISTS idx_ticket_alerts_ticket
    ON ticket_alerts(ticket_id);
