-- Migration 010: extract typed columns out of the metadata JSONB column.
-- Additive first (seven new columns), backfill from metadata, then enforce
-- NOT NULL + DEFAULT on the JSONB catch-alls, and finally DROP metadata.
-- Runs against the post-009 schema (see 009_drop_allocated_ip.sql).
ALTER TABLE yascheduler_tasks
ADD COLUMN engine VARCHAR(64),
ADD COLUMN remote_folder VARCHAR(1024),
ADD COLUMN local_folder VARCHAR(1024),
ADD COLUMN webhook_url VARCHAR(2048),
ADD COLUMN error TEXT,
ADD COLUMN webhook_custom_params JSONB,
ADD COLUMN extra JSONB;

UPDATE yascheduler_tasks
SET
    engine = COALESCE(metadata ->> 'engine', ''),
    remote_folder = metadata ->> 'remote_folder',
    local_folder = metadata ->> 'local_folder',
    webhook_url = metadata ->> 'webhook_url',
    error = metadata ->> 'error',
    webhook_custom_params = COALESCE(
        metadata -> 'webhook_custom_params', '{}'::JSONB
    ),
    extra = COALESCE(
        metadata - 'engine' - 'remote_folder' - 'local_folder'
        - 'webhook_url' - 'error' - 'webhook_custom_params',
        '{}'::JSONB
    );

ALTER TABLE yascheduler_tasks
ALTER COLUMN engine SET NOT NULL,
ALTER COLUMN webhook_custom_params SET NOT NULL,
ALTER COLUMN webhook_custom_params SET DEFAULT '{}'::JSONB,
ALTER COLUMN extra SET NOT NULL,
ALTER COLUMN extra SET DEFAULT '{}'::JSONB,
DROP COLUMN metadata;
