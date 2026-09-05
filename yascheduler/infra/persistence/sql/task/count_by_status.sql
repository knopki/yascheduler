SELECT
    status,
    COUNT(task_id) AS count
FROM yascheduler_tasks
GROUP BY status
ORDER BY status;
