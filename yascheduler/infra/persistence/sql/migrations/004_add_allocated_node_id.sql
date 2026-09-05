-- Migration 004: add allocated_node_id to yascheduler_tasks.
-- Additive + backfilling, applied in one transaction by the migration runner.
-- The FK is ON DELETE SET NULL so removing a node nulls the task's
-- allocated_node_id but preserves the task row and allocated_ip.
-- Backfill matches task.ip -> node.ip (best-effort; at this point the read
-- path still uses ip directly). ip='' is excluded: after migration 003 every
-- prov* node shares ip='' (the match would return >1 row and crash the scalar
-- subquery), and ip='' is the unallocated sentinel on legacy TO_DO tasks --
-- backfilling them would violate the task_status_field_invariants CHECK added
-- in migration 011. LIMIT 1 guards any genuine duplicate real IP.
ALTER TABLE yascheduler_tasks
ADD COLUMN allocated_node_id INTEGER
REFERENCES yascheduler_nodes (node_id) ON DELETE SET NULL;

UPDATE yascheduler_tasks t
SET
    allocated_node_id = (
        SELECT n.node_id FROM yascheduler_nodes AS n
        WHERE n.ip = t.ip
        ORDER BY n.node_id
        LIMIT 1
    )
WHERE t.ip IS NOT NULL AND t.ip <> '';
