create schema if not exists bot_prod;

create table if not exists bot_prod.ingest_events (
    id bigserial primary key,
    update_id bigint not null unique,
    chat_id bigint not null,
    message_id bigint not null,
    source_type text not null check (source_type in ('comment', 'direct')),
    status text not null default 'pending' check (status in ('pending', 'synced', 'failed')),
    attempts integer not null default 0 check (attempts >= 0),
    last_error text,
    normalized_json jsonb not null,
    sheets_row_json jsonb not null,
    created_at_utc timestamptz not null default now(),
    synced_at_utc timestamptz,
    unique (chat_id, message_id)
);

create index if not exists idx_bot_prod_ingest_events_status_id
    on bot_prod.ingest_events (status, id);

create table if not exists bot_prod.discussion_thread_mappings (
    discussion_chat_id bigint not null,
    message_thread_id bigint not null,
    channel_chat_id bigint,
    channel_post_id bigint,
    root_message_id bigint,
    updated_at_utc timestamptz not null default now(),
    primary key (discussion_chat_id, message_thread_id)
);

create table if not exists bot_prod.ticket_counters (
    counter_key text primary key,
    shift text not null check (shift in ('D', 'N')),
    shift_start_utc timestamptz not null,
    shift_end_utc timestamptz not null,
    last_seq integer not null default 0 check (last_seq >= 0),
    updated_at_utc timestamptz not null default now()
);

create table if not exists bot_prod.tickets (
    id bigserial primary key,
    ticket_code text not null default '',
    status text not null default 'new' check (status in ('preview', 'new', 'reacted', 'answered', 'closed')),
    source_type text not null check (source_type in ('comment', 'direct')),
    user_id bigint not null,
    username text,
    first_name text,
    user_chat_id bigint not null,
    user_message_id bigint not null,
    user_message_thread_id bigint,
    user_direct_messages_topic_id bigint,
    user_message_text text,
    support_group_message_id bigint,
    answer_message_id bigint,
    created_at_utc timestamptz not null default now(),
    reacted_at_utc timestamptz,
    reacted_by_user_id bigint,
    answered_at_utc timestamptz,
    closed_at_utc timestamptz,
    closed_by_user_id bigint,
    sheets_synced boolean not null default false,
    sheets_row_number integer,
    unique (user_chat_id, user_message_id)
);

create unique index if not exists ux_bot_prod_tickets_ticket_code
    on bot_prod.tickets (ticket_code)
    where ticket_code <> '';

create index if not exists idx_bot_prod_tickets_status
    on bot_prod.tickets (status);

create index if not exists idx_bot_prod_tickets_open_user
    on bot_prod.tickets (user_id, user_chat_id, id desc)
    where status <> 'closed';

create index if not exists idx_bot_prod_tickets_support_msg
    on bot_prod.tickets (support_group_message_id)
    where support_group_message_id is not null;

create index if not exists idx_bot_prod_tickets_open_direct_topic
    on bot_prod.tickets (user_chat_id, user_direct_messages_topic_id, id desc)
    where source_type = 'direct' and status <> 'closed';

create table if not exists bot_prod.ticket_messages (
    id bigserial primary key,
    ticket_id bigint not null references bot_prod.tickets (id) on delete cascade,
    msg_type text not null,
    support_group_message_id bigint not null unique,
    created_at_utc timestamptz not null default now()
);

create index if not exists idx_bot_prod_ticket_messages_ticket_type
    on bot_prod.ticket_messages (ticket_id, msg_type);

create table if not exists bot_prod.ticket_alerts (
    id bigserial primary key,
    ticket_id bigint not null references bot_prod.tickets (id) on delete cascade,
    alert_type text not null check (alert_type in ('primary_reaction', 'secondary_reaction', 'close')),
    sent_at_utc timestamptz not null default now(),
    support_group_message_id bigint,
    unique (ticket_id, alert_type)
);

create index if not exists idx_bot_prod_ticket_alerts_ticket
    on bot_prod.ticket_alerts (ticket_id);

create table if not exists bot_prod.outbox_jobs (
    id bigserial primary key,
    job_type text not null,
    status text not null default 'pending' check (status in ('pending', 'processing', 'done', 'failed')),
    dedup_key text unique,
    payload jsonb not null,
    attempts integer not null default 0 check (attempts >= 0),
    max_attempts integer not null default 10 check (max_attempts > 0),
    next_attempt_at_utc timestamptz not null default now(),
    last_error text,
    created_at_utc timestamptz not null default now(),
    updated_at_utc timestamptz not null default now()
);

create index if not exists idx_bot_prod_outbox_jobs_ready
    on bot_prod.outbox_jobs (status, next_attempt_at_utc, id)
    where status in ('pending', 'failed');

create or replace function bot_prod.next_ticket_code(
    p_counter_key text,
    p_shift text,
    p_shift_start_utc timestamptz,
    p_shift_end_utc timestamptz
)
returns text
language plpgsql
as $$
declare
    v_seq integer;
begin
    insert into bot_prod.ticket_counters (
        counter_key,
        shift,
        shift_start_utc,
        shift_end_utc,
        last_seq,
        updated_at_utc
    )
    values (
        p_counter_key,
        p_shift,
        p_shift_start_utc,
        p_shift_end_utc,
        1,
        now()
    )
    on conflict (counter_key)
    do update set
        last_seq = bot_prod.ticket_counters.last_seq + 1,
        updated_at_utc = now()
    returning last_seq into v_seq;

    return p_counter_key || '-' || lpad(v_seq::text, 2, '0');
end;
$$;

alter table bot_prod.ingest_events enable row level security;
alter table bot_prod.discussion_thread_mappings enable row level security;
alter table bot_prod.ticket_counters enable row level security;
alter table bot_prod.tickets enable row level security;
alter table bot_prod.ticket_messages enable row level security;
alter table bot_prod.ticket_alerts enable row level security;
alter table bot_prod.outbox_jobs enable row level security;

revoke all on schema bot_prod from anon, authenticated;
revoke all on all tables in schema bot_prod from anon, authenticated;
revoke all on all functions in schema bot_prod from anon, authenticated;

