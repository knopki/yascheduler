UPDATE yascheduler_tasks
SET label = :label, status = :status, ip = :ip, metadata = :metadata, allocated_node_id = :node_id
WHERE task_id = :task_id
RETURNING task_id;