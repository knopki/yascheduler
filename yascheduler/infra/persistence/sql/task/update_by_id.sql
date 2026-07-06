UPDATE yascheduler_tasks
SET
    title = :title,
    status = :status,
    metadata = :metadata,
    allocated_node_id = :node_id
WHERE task_id = :task_id
RETURNING task_id;
