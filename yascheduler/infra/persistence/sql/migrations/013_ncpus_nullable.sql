-- Migration 013: backfill ncpus=0 → NULL, add node_ncpus_positive CHECK.

-- Step 1: Backfill legacy magic-0 sentinel rows to NULL (honest "no limit")
UPDATE yascheduler_nodes SET ncpus = NULL
WHERE ncpus = 0;

-- Step 2: Add positive-only CHECK constraint
ALTER TABLE yascheduler_nodes
ADD CONSTRAINT node_ncpus_positive
CHECK (ncpus IS NULL OR ncpus > 0);
