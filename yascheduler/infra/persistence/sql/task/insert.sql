INSERT INTO yascheduler_tasks (title, metadata, status, allocated_node_id)
VALUES (:title, :metadata, :status, :node_id)
RETURNING
    task_id, title, status, metadata,
    allocated_node_id, created_at, updated_at;
