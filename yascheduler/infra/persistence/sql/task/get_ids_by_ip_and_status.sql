SELECT task_id FROM yascheduler_tasks
WHERE ip = :ip AND status = :status
ORDER BY task_id;
