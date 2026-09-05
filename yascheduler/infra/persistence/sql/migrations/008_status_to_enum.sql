-- Migration 008: convert yascheduler_tasks.status from SMALLINT to a
-- PostgreSQL enum `task_status` with labels 'TO_DO', 'RUNNING', 'DONE'.
DO $$
BEGIN
    IF to_regtype('task_status') IS NULL THEN
        CREATE TYPE TASK_STATUS AS ENUM ('TO_DO', 'RUNNING', 'DONE');
    END IF;
END $$;

ALTER TABLE yascheduler_tasks
ALTER COLUMN status TYPE TASK_STATUS
USING CASE status
    WHEN 0 THEN 'TO_DO'::TASK_STATUS
    WHEN 1 THEN 'RUNNING'::TASK_STATUS
    WHEN 2 THEN 'DONE'::TASK_STATUS
END;

ALTER TABLE yascheduler_tasks
ALTER COLUMN status SET DEFAULT 'TO_DO';
