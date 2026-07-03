SELECT
    task_id,
    label,
    ip,
    status,
    metadata,
    allocated_node_id
FROM yascheduler_tasks
WHERE status IN (SELECT unnest(cast(:statuses AS int [])))
ORDER BY task_id
LIMIT :lim;