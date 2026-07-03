-- Bootstrap the yascheduler_migrations tracker (three-case logic).
-- Runs BEFORE CREATE TABLE IF NOT EXISTS yascheduler_nodes because the
-- presence of yascheduler_nodes is the signal distinguishing a fresh DB
-- (seed to latest) from a legacy DB (no seed, run all migrations).
-- last_migration is the single manual edit point when a migration is added.
-- Migration 004 (add-allocated-node-id) added allocated_node_id to
-- yascheduler_tasks; the snapshot below includes it so a fresh DB has it
-- without running the migration. Migration 005 (serial-to-generated-identity)
-- converted the two PK columns to GENERATED ALWAYS AS IDENTITY; the snapshot
-- below declares them that way so a fresh DB has identity columns directly.
DO $$
DECLARE
  last_migration CONSTANT TEXT := '005';
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
    node_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    ip VARCHAR(15),
    port INTEGER DEFAULT 22,
    username VARCHAR(255) DEFAULT 'root',
    ncpus SMALLINT DEFAULT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    cloud VARCHAR(32) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS yascheduler_tasks (
    task_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    label VARCHAR(256),
    metadata JSONB,
    ip VARCHAR(15),
    status SMALLINT,
    allocated_node_id INTEGER REFERENCES yascheduler_nodes(node_id) ON DELETE SET NULL
);
