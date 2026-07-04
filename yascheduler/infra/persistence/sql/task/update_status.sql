UPDATE yascheduler_tasks
SET status = :status
WHERE task_id = :task_id
RETURNING task_id;
