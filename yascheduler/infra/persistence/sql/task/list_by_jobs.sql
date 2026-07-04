SELECT
    task_id,
    label,
    ip,
    status,
    metadata,
    allocated_node_id
FROM yascheduler_tasks
WHERE task_id IN (SELECT unnest(cast(:task_ids AS int [])))
ORDER BY task_id;
