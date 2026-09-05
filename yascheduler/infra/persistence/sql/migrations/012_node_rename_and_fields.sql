-- Migration 012: rename ip→hostname, add audit timestamps, jump host fields,
-- external_id (backfill for cloud rows), NODE_STATUS enum + status column,
-- port NOT NULL + CHECK constraints.

-- Step 1: Rename ip to hostname
ALTER TABLE yascheduler_nodes RENAME COLUMN ip TO hostname;

-- Step 2: Widen hostname to VARCHAR(255)
ALTER TABLE yascheduler_nodes ALTER COLUMN hostname TYPE VARCHAR(255);

-- Step 3: Add created_at
ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Step 4: Add updated_at
ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Step 5: Install trigger on yascheduler_nodes (function already created in
-- migration 007).
DROP TRIGGER IF EXISTS yascheduler_nodes_touch_updated_at
ON yascheduler_nodes;
CREATE TRIGGER yascheduler_nodes_touch_updated_at
BEFORE UPDATE ON yascheduler_nodes
FOR EACH ROW EXECUTE FUNCTION YASCHEDULER_TOUCH_UPDATED_AT();

-- Step 6: Add jump_host (nullable)
ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS jump_host VARCHAR(255);

-- Step 7: Add jump_port + CHECK constraint
ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS jump_port INTEGER NOT NULL DEFAULT 22;
ALTER TABLE yascheduler_nodes
ADD CONSTRAINT node_jump_port_range
CHECK (jump_port > 0 AND jump_port < 65536);

-- Step 8: Add jump_username
ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS jump_username VARCHAR(255) NOT NULL DEFAULT 'root';

-- Step 9: Add external_id (nullable)
ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS external_id VARCHAR(255);

-- Step 10: Backfill external_id for cloud nodes only
UPDATE yascheduler_nodes
SET external_id = hostname
WHERE cloud IS NOT NULL AND hostname <> '';

-- Step 11: Create NODE_STATUS enum (idempotent via DO block)
DO $$
BEGIN
    IF to_regtype('node_status') IS NULL THEN
        CREATE TYPE NODE_STATUS AS ENUM ('OTHER');
    END IF;
END $$;

-- Step 12: Add status column with enum default
ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS status NODE_STATUS NOT NULL DEFAULT 'OTHER';

-- Step 13: Add port NOT NULL
ALTER TABLE yascheduler_nodes ALTER COLUMN port SET NOT NULL;

-- Step 14: Add port CHECK constraint
ALTER TABLE yascheduler_nodes
ADD CONSTRAINT node_port_range
CHECK (port > 0 AND port < 65536);
