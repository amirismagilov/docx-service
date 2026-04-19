-- Industrial DOCX Service v1: relational schema draft
-- PostgreSQL 14+

create extension if not exists "pgcrypto";

create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  owner_team text,
  active_version_id uuid,
  published_version_id uuid,
  created_at_utc timestamptz not null default now(),
  updated_at_utc timestamptz not null default now()
);

create table if not exists document_versions (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  state text not null check (state in ('draft', 'published', 'archived')),
  schema_json text,
  source_file_name text,
  template_object_key text,
  compiled_metadata_json jsonb,
  created_at_utc timestamptz not null default now(),
  published_at_utc timestamptz
);

alter table documents
  add constraint if not exists fk_documents_active_version
  foreign key (active_version_id) references document_versions(id);

alter table documents
  add constraint if not exists fk_documents_published_version
  foreign key (published_version_id) references document_versions(id);

create table if not exists conditional_blocks (
  id uuid primary key default gen_random_uuid(),
  document_version_id uuid not null references document_versions(id) on delete cascade,
  find_template text not null,
  occurrence_index integer not null check (occurrence_index >= 0),
  condition_field text not null,
  equals_value text not null,
  branch text not null default 'if' check (branch in ('if')),
  created_at_utc timestamptz not null default now()
);

create table if not exists signature_assets (
  id uuid primary key default gen_random_uuid(),
  document_version_id uuid not null references document_versions(id) on delete cascade,
  name text not null,
  mime_type text not null check (mime_type in ('image/png', 'image/jpeg')),
  object_key text not null,
  size_bytes bigint not null check (size_bytes > 0),
  created_at_utc timestamptz not null default now()
);

create table if not exists signature_slots (
  id uuid primary key default gen_random_uuid(),
  document_version_id uuid not null references document_versions(id) on delete cascade,
  signature_asset_id uuid not null references signature_assets(id),
  anchor_text text not null,
  occurrence_index integer not null check (occurrence_index >= 0),
  offset_x_pt numeric(10, 2) not null default 0,
  offset_y_pt numeric(10, 2) not null default 0,
  width_pt numeric(10, 2) not null default 120,
  height_pt numeric(10, 2) not null default 40,
  created_at_utc timestamptz not null default now()
);

create table if not exists generation_requests (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id),
  version_id uuid not null references document_versions(id),
  client_id uuid,
  request_id text not null,
  idempotency_key text,
  mode text not null check (mode in ('sync', 'async')),
  status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'expired')),
  payload_masked_json jsonb not null,
  payload_hash_sha256 text not null,
  error_code text,
  error_message text,
  created_at_utc timestamptz not null default now(),
  started_at_utc timestamptz,
  finished_at_utc timestamptz,
  latency_ms integer,
  queue_wait_ms integer
);

create table if not exists generation_results (
  id uuid primary key default gen_random_uuid(),
  generation_request_id uuid not null unique references generation_requests(id) on delete cascade,
  storage_uri text not null,
  file_name text not null,
  mime_type text not null,
  size_bytes bigint not null check (size_bytes >= 0),
  sha256 text not null,
  retention_until_utc timestamptz,
  created_at_utc timestamptz not null default now()
);

create table if not exists audit_events (
  id uuid primary key default gen_random_uuid(),
  event_type text not null,
  severity text not null check (severity in ('info', 'warn', 'error', 'security')),
  actor_type text not null check (actor_type in ('service', 'user', 'system')),
  actor_id text not null,
  tenant_id text,
  document_id uuid,
  version_id uuid,
  generation_request_id uuid,
  request_id text not null,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at_utc timestamptz not null default now()
);

create index if not exists ix_generation_requests_document_time
  on generation_requests (document_id, created_at_utc desc);
create index if not exists ix_generation_requests_client_time
  on generation_requests (client_id, created_at_utc desc);
create index if not exists ix_generation_requests_status_time
  on generation_requests (status, created_at_utc desc);
create index if not exists ix_audit_events_type_time
  on audit_events (event_type, created_at_utc desc);
