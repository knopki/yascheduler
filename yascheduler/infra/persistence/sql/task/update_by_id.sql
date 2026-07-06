UPDATE yascheduler_tasks
SET
    title = :title,
    engine = :engine,
    remote_folder = :remote_folder,
    local_folder = :local_folder,
    webhook_url = :webhook_url,
    error = :error,
    webhook_custom_params = :webhook_custom_params,
    extra = :extra,
    status = :status,
    allocated_node_id = :node_id
WHERE task_id = :task_id
RETURNING task_id;
