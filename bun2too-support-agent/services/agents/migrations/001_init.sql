-- Phase 1 target schema for PostgresCaseStore. Applied automatically by infra/docker-compose.yml.
create table cases (
  tenant text not null,
  id text primary key,
  idempotency_key text not null,
  status text not null,
  channel text not null,
  trace_id text not null,
  classification jsonb,
  tickets jsonb not null default '[]',
  resolution jsonb,
  pending_question text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant, idempotency_key)
);

create table case_events (
  case_id text not null references cases(id),
  seq integer not null,
  tenant text not null,
  at timestamptz not null default now(),
  status text not null,
  actor text not null,
  reason text not null,
  data jsonb not null default '{}',
  primary key (case_id, seq)
);

create table case_messages (
  case_id text not null references cases(id),
  seq integer not null,
  tenant text not null,
  body bytea not null,
  at timestamptz not null default now(),
  primary key (case_id, seq)
);

create table ticket_outbox (
  id bigserial primary key,
  tenant text not null,
  case_id text not null references cases(id),
  system text not null,
  action text not null,
  payload jsonb not null,
  attempts integer not null default 0,
  next_attempt_at timestamptz not null default now(),
  delivered_at timestamptz
);

alter table cases enable row level security;
alter table case_events enable row level security;
alter table case_messages enable row level security;
alter table ticket_outbox enable row level security;

create policy tenant_isolation on cases using (tenant = current_setting('relay.tenant'));
create policy tenant_isolation on case_events using (tenant = current_setting('relay.tenant'));
create policy tenant_isolation on case_messages using (tenant = current_setting('relay.tenant'));
create policy tenant_isolation on ticket_outbox using (tenant = current_setting('relay.tenant'));
