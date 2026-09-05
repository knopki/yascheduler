SELECT task_id FROM yascheduler_tasks
WHERE allocated_node_id = :node_id AND status = :status
ORDER BY task_id;
