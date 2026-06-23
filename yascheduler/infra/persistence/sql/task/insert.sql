INSERT INTO yascheduler_tasks (label, metadata, ip, status)
VALUES (:label, :metadata, :ip, :status)
RETURNING task_id, label, ip, status, metadata;
