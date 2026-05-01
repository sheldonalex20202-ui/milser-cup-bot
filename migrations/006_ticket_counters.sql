CREATE TABLE IF NOT EXISTS ticket_counters (
    counter_key TEXT PRIMARY KEY,
    shift TEXT NOT NULL,
    shift_start_utc TEXT NOT NULL,
    shift_end_utc TEXT NOT NULL,
    last_seq INTEGER NOT NULL DEFAULT 0,
    updated_at_utc TEXT NOT NULL
);
