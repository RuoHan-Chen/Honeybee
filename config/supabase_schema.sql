-- Honeybee — Supabase/Postgres schema.
-- Mirrors the SQLite placeholder schema (src/store/sqlite_repo.py) so SupabaseRepository
-- is a drop-in Repository backend. Run this once in the Supabase SQL Editor.
--
-- JSON columns use jsonb. Timestamps are stored as timestamptz.

create table if not exists markets (
    market_id          text primary key,
    slug               text,
    url                text,
    question           text,
    category           text,
    vertical           text,
    yes_price          double precision,
    no_price           double precision,
    spread             double precision,
    liquidity          double precision,
    volume_24h         double precision,
    end_date           timestamptz,
    order_book_enabled boolean default true,
    discovered_at      timestamptz,
    flagged_reason     text,
    discovery_score    double precision default 0
);

create table if not exists market_snapshots (
    id          bigint generated always as identity primary key,
    market_id   text not null,
    timestamp   timestamptz not null,
    yes_price   double precision,
    no_price    double precision,
    spread      double precision,
    liquidity   double precision,
    volume_24h  double precision
);
create index if not exists idx_snap_market on market_snapshots(market_id);

create table if not exists trail_events (
    id          bigint generated always as identity primary key,
    decision_id text not null,
    market_id   text not null,
    agent       text not null,
    timestamp   timestamptz not null,
    text        text not null,
    payload     jsonb not null default '{}'::jsonb
);
create index if not exists idx_trail_decision on trail_events(decision_id);
create index if not exists idx_trail_market   on trail_events(market_id);

create table if not exists research_records (
    decision_id      text primary key,
    market_id        text not null,
    vertical         text,
    model            text,
    prior_fair_value double precision,
    fair_value       double precision,
    confidence       double precision,
    rationale        text,
    token_cost_usd   double precision default 0,
    abstain          boolean default false,
    created_at       timestamptz
);
create index if not exists idx_research_market on research_records(market_id);

create table if not exists source_attributions (
    id               bigint generated always as identity primary key,
    decision_id      text not null,
    source_name      text not null,
    fair_value_delta double precision default 0,
    note             text
);
create index if not exists idx_attr_decision on source_attributions(decision_id);

create table if not exists data_source_uses (
    id                 bigint generated always as identity primary key,
    market_id          text not null,
    decision_id        text not null,
    source_name        text not null,
    source_url         text,
    source_type        text,
    datapoints         jsonb default '{}'::jsonb,
    acquisition_method text default 'free',
    cost_usd           double precision default 0,
    fetched_at         timestamptz,
    influenced_price   boolean default false,
    influenced_note    text
);
create index if not exists idx_dsu_decision on data_source_uses(decision_id);

create table if not exists risk_decisions (
    decision_id       text primary key,
    market_id         text not null,
    market_price      double precision,
    fair_value        double precision,
    edge              double precision,
    kelly_inputs      jsonb default '{}'::jsonb,
    size_usd          double precision,
    limit_price       double precision,
    risk_checks       jsonb default '{}'::jsonb,
    slippage_estimate double precision default 0,
    side              text,
    executed          boolean default false,
    reason            text,
    created_at        timestamptz
);

create table if not exists fills (
    id          bigint generated always as identity primary key,
    market_id   text not null,
    decision_id text not null,
    side        text,
    size_usd    double precision,
    avg_price   double precision,
    tx_ref      text,
    paper       boolean default true,
    timestamp   timestamptz
);
create index if not exists idx_fill_decision on fills(decision_id);

create table if not exists outcomes (
    id             bigint generated always as identity primary key,
    market_id      text not null,
    decision_id    text not null,
    resolved_value double precision,
    realized_pnl   double precision,
    was_calibrated boolean default false,
    recorded_at    timestamptz
);

create table if not exists daily_pnl (
    day      text primary key,
    realised double precision not null default 0
);

create table if not exists tasks (
    id             text primary key,
    task_type      text not null,
    decision_id    text not null,
    market_id      text default '',
    input_payload  jsonb not null default '{}'::jsonb,
    output_payload jsonb not null default '{}'::jsonb,
    status         text not null default 'pending',
    created_at     timestamptz not null,
    claimed_at     timestamptz,
    completed_at   timestamptz,
    worker_pid     integer,
    error          text default ''
);
create index if not exists idx_tasks_type_status on tasks(task_type, status);
create index if not exists idx_tasks_decision     on tasks(decision_id);

-- Atomic task claim (replaces SQLite's BEGIN IMMEDIATE). Locks the oldest
-- pending row of the given type and flips it to 'claimed' in one statement.
create or replace function claim_task(p_task_type text, p_worker_pid integer)
returns setof tasks
language plpgsql
as $$
declare
    claimed_id text;
begin
    select id into claimed_id
    from tasks
    where task_type = p_task_type and status = 'pending'
    order by created_at
    for update skip locked
    limit 1;

    if claimed_id is null then
        return;
    end if;

    return query
    update tasks
    set status = 'claimed', claimed_at = now(), worker_pid = p_worker_pid
    where id = claimed_id
    returning *;
end;
$$;

-- Atomic upsert for daily_pnl accumulation.
create or replace function add_daily_pnl(p_day text, p_realised double precision)
returns void
language sql
as $$
    insert into daily_pnl (day, realised) values (p_day, p_realised)
    on conflict (day) do update set realised = daily_pnl.realised + excluded.realised;
$$;
