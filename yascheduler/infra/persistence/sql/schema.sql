-- Bootstrap the yascheduler_migrations tracker.
-- Runs BEFORE CREATE TABLE IF NOT EXISTS yascheduler_nodes because the
-- presence of yascheduler_nodes is the signal distinguishing a fresh DB
-- (seed to latest) from a legacy DB (no seed, run all migrations).
-- last_migration is the single manual edit point when a migration is added.
DO $$
DECLARE
  last_migration CONSTANT TEXT := '009';
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

-- task_status enum: created idempotently (CREATE TYPE has no IF NOT EXISTS).
DO $$
BEGIN
    IF to_regtype('task_status') IS NULL THEN
        CREATE TYPE TASK_STATUS AS ENUM ('TO_DO', 'RUNNING', 'DONE');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS yascheduler_tasks (
    task_id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    title VARCHAR(256),
    metadata JSONB,
    status TASK_STATUS NOT NULL DEFAULT 'TO_DO',
    allocated_node_id INTEGER REFERENCES yascheduler_nodes (
        node_id
    ) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Only install the trigger if the updated_at column exists (safe for legacy DBs
-- where CREATE TABLE IF NOT EXISTS is a no-op on pre-existing tables).
DO $schema_block$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'yascheduler_tasks' AND column_name = 'updated_at'
    ) THEN
        CREATE OR REPLACE FUNCTION YASCHEDULER_TOUCH_UPDATED_AT() RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $func$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $func$;

        DROP TRIGGER IF EXISTS yascheduler_tasks_touch_updated_at
        ON yascheduler_tasks;
        CREATE TRIGGER yascheduler_tasks_touch_updated_at
        BEFORE UPDATE ON yascheduler_tasks
        FOR EACH ROW EXECUTE FUNCTION YASCHEDULER_TOUCH_UPDATED_AT();
    END IF;
END;
$schema_block$;
