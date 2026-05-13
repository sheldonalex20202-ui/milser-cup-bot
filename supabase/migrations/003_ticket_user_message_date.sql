alter table bot_prod.tickets
    add column if not exists user_message_date_utc timestamptz;
