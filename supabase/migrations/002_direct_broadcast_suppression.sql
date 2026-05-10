alter table bot_prod.tickets
    add column if not exists suppressed_direct_message_id bigint,
    add column if not exists suppressed_direct_until_utc timestamptz;

create index if not exists idx_bot_prod_tickets_direct_suppression
    on bot_prod.tickets (user_chat_id, user_direct_messages_topic_id, suppressed_direct_message_id)
    where source_type = 'direct' and suppressed_direct_message_id is not null;
