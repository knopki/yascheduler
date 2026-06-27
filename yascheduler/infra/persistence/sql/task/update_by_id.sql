UPDATE yascheduler_tasks
SET label = :label, status = :status, ip = :ip, metadata = :metadata
WHERE task_id = :task_id
RETURNING task_id;