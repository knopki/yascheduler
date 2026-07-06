SELECT
    task_id,
    title,
    status,
    metadata,
    allocated_node_id,
    created_at,
    updated_at
FROM yascheduler_tasks
WHERE status IN (SELECT unnest(cast(:statuses AS task_status[])))
ORDER BY task_id
LIMIT :lim;
