-- PostgreSQL schema for generation store and audit/statistics.
-- Apply before setting DOCX_SERVICE_GENERATION_STORE=postgres

create table if not exists generation_requests (
  id text primary key,
  document_id text not null,
  version_id text not null,
  mode text not null,
  status text not null,
  request_id text not null,
  idempotency_key text,
  payload_json text not null,
  payload_masked_json text not null,
  payload_hash_sha256 text not null,
  error_code text,
  error_message text,
  file_name text,
  mime_type text,
  storage_path text,
  size_bytes bigint,
  sha256 text,
  created_at_utc text not null,
  started_at_utc text,
  finished_at_utc text,
  latency_ms integer
);

create index if not exists ix_generation_requests_document_time
  on generation_requests (document_id, created_at_utc);
create index if not exists ix_generation_requests_status_time
  on generation_requests (status, created_at_utc);
create index if not exists ix_generation_requests_idempotency
  on generation_requests (document_id, version_id, idempotency_key);

create table if not exists audit_events (
  id text primary key,
  generation_request_id text,
  event_type text not null,
  severity text not null,
  actor_id text not null,
  request_id text not null,
  metadata_json text not null,
  created_at_utc text not null
);

create index if not exists ix_audit_events_type_time
  on audit_events (event_type, created_at_utc);
