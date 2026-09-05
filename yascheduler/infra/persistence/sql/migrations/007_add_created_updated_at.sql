-- Migration 007: add created_at/updated_at columns and a BEFORE UPDATE trigger
-- that sets updated_at = NOW() on every row update.
ALTER TABLE yascheduler_tasks
ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE yascheduler_tasks
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE OR REPLACE FUNCTION YASCHEDULER_TOUCH_UPDATED_AT() RETURNS TRIGGER
AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$
LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS yascheduler_tasks_touch_updated_at
ON yascheduler_tasks;
CREATE TRIGGER yascheduler_tasks_touch_updated_at
BEFORE UPDATE ON yascheduler_tasks
FOR EACH ROW EXECUTE FUNCTION YASCHEDULER_TOUCH_UPDATED_AT();
