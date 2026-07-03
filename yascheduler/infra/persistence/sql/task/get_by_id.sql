SELECT
    task_id,
    label,
    ip,
    status,
    metadata,
    allocated_node_id
FROM yascheduler_tasks
WHERE task_id = :task_id;