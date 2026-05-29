SELECT
    task_id,
    label,
    ip,
    status,
    metadata
FROM yascheduler_tasks
WHERE task_id = :task_id;
