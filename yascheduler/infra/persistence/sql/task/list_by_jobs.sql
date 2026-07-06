SELECT
    task_id,
    title,
    status,
    metadata,
    allocated_node_id,
    created_at,
    updated_at
FROM yascheduler_tasks
WHERE task_id IN (SELECT unnest(cast(:task_ids AS int[])))
ORDER BY task_id;
