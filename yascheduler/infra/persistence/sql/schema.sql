-- Bootstrap the yascheduler_migrations tracker (three-case logic).
-- Runs BEFORE CREATE TABLE IF NOT EXISTS yascheduler_nodes because the
-- presence of yascheduler_nodes is the signal distinguishing a fresh DB
-- (seed to latest) from a legacy DB (no seed, run all migrations).
-- last_migration is the single manual edit point when a migration is added.
DO $$
DECLARE
  last_migration CONSTANT TEXT := '001';
BEGIN
  IF to_regclass('yascheduler_migrations') IS NULL THEN
    EXECUTE 'CREATE TABLE yascheduler_migrations (
      migration_id TEXT PRIMARY KEY,
      created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )';
    IF to_regclass('yascheduler_nodes') IS NULL THEN
      INSERT INTO yascheduler_migrations (migration_id) VALUES (last_migration);
    END IF;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS yascheduler_nodes (
    ip VARCHAR(15) UNIQUE,
    port INTEGER DEFAULT 22,
    username VARCHAR(255) DEFAULT 'root',
    ncpus SMALLINT DEFAULT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    cloud VARCHAR(32) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS yascheduler_tasks (
    task_id SERIAL PRIMARY KEY,
    label VARCHAR(256),
    metadata JSONB,
    ip VARCHAR(15),
    status SMALLINT
);
