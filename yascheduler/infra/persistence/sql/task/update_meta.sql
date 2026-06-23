UPDATE yascheduler_tasks
SET metadata = :metadata
WHERE task_id = :task_id;
