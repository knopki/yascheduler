-- Migration 009: drop the allocated_ip column from yascheduler_tasks.
ALTER TABLE yascheduler_tasks DROP COLUMN IF EXISTS ip;
