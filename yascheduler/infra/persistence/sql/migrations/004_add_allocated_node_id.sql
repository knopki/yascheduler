-- Migration 004: add allocated_node_id to yascheduler_tasks.
-- Additive + backfilling, applied in one transaction by the migration runner.
-- The FK is ON DELETE SET NULL so removing a node nulls the task's
-- allocated_node_id but preserves the task row and allocated_ip.
-- Backfill assumes ip is unique-or-NULL at migration time;
-- for a legacy dup-IP row the subquery returns one row arbitrarily
-- (best-effort; read path stays ip).
ALTER TABLE yascheduler_tasks
ADD COLUMN allocated_node_id INTEGER
REFERENCES yascheduler_nodes (node_id) ON DELETE SET NULL;

UPDATE yascheduler_tasks t
SET
    allocated_node_id = (
        SELECT n.node_id FROM yascheduler_nodes AS n
        WHERE n.ip = t.ip
    )
WHERE t.ip IS NOT NULL;
