INSERT INTO yascheduler_tasks (label, metadata, ip, status, allocated_node_id)
VALUES (:label, :metadata, :ip, :status, :node_id)
RETURNING task_id, label, ip, status, metadata, allocated_node_id;