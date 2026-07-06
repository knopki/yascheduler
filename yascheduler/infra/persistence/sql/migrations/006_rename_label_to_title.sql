-- Migration 006: rename yascheduler_tasks.label → title.
-- `label` is a PostgreSQL keyword (legal but awkward); `title` is a
-- non-reserved keyword and reads as a column name without quoting.
ALTER TABLE yascheduler_tasks RENAME COLUMN label TO title;
