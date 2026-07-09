-- Migration 011: add the task_status_field_invariants CHECK constraint.
-- Enforces the exhaustive per-status field contract on yascheduler_tasks:
--   TO_DO   -> allocated_node_id IS NULL AND error IS NULL
--   RUNNING -> allocated_node_id IS NOT NULL AND error IS NULL
--              AND remote_folder IS NOT NULL
--   DONE    -> unconstrained on those three fields
-- No defensive pre-clean UPDATE: the audit confirmed no production path creates
-- the forbidden states, so ADD CONSTRAINT succeeds on existing data; if that
-- assumption ever breaks the constraint fails fast at migration time, surfacing
-- the offending row rather than masking it.
ALTER TABLE yascheduler_tasks
ADD CONSTRAINT task_status_field_invariants
CHECK (
    (status = 'TO_DO' AND allocated_node_id IS NULL AND error IS NULL)
    OR (
        status = 'RUNNING'
        AND allocated_node_id IS NOT NULL
        AND error IS NULL
        AND remote_folder IS NOT NULL
    )
    OR (status = 'DONE')
);
