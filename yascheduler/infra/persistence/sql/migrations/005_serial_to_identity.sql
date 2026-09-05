-- Migration 005: convert yascheduler_nodes.node_id and
-- yascheduler_tasks.task_id from SERIAL PRIMARY KEY to INTEGER PRIMARY KEY
-- GENERATED ALWAYS AS IDENTITY (serial-to-generated-identity).
--
-- SERIAL is PostgreSQL-specific and silently accepts explicit PK inserts.
-- GENERATED ALWAYS AS IDENTITY (SQL:2003, PG10+) binds the sequence to the
-- column and rejects explicit PK inserts without OVERRIDING SYSTEM VALUE,
-- guarding against a class of future bugs. ALTER COLUMN ... ADD GENERATED AS
-- IDENTITY on an existing column requires PG12+; the de-facto repo floor is
-- PG16 (testcontainer postgres:16-alpine).
--
-- Mechanics (corrected from design.md D3 after empirical testing): 1. DROP
-- DEFAULT removes the nextval(seq) default SERIAL installed. 2. The old SERIAL
-- sequence (<table>_<col>_seq) is still OWNED BY the column; ADD GENERATED
-- ALWAYS AS IDENTITY would create a NEW sequence with a different name (e.g.
-- <table>_<col>_seq1), and pg_get_serial_sequence would still return the old
-- unused sequence — so setval would seed the wrong sequence and the next insert
-- collides. To avoid this, disown and DROP the old SERIAL sequence first, so
-- ADD GENERATED ALWAYS AS IDENTITY creates a fresh sequence reusing the
-- canonical <table>_<col>_seq name. 3. ADD GENERATED ALWAYS AS IDENTITY creates
-- the identity sequence bound to the column. 4. setval(MAX+1, false) seeds the
-- identity sequence above the current MAX so the next insert returns MAX+1
-- (RESTART WITH only accepts an integer literal, not an expression, so setval
-- is the correct pattern). On an empty table COALESCE(MAX,0)=0 →
-- setval(...,1,false) → first insert id=1. Not idempotent by design; the
-- yascheduler_migrations tracker guards re-application.
ALTER TABLE yascheduler_nodes
ALTER COLUMN node_id DROP DEFAULT;
ALTER SEQUENCE yascheduler_nodes_node_id_seq OWNED BY NONE;
DROP SEQUENCE yascheduler_nodes_node_id_seq;
ALTER TABLE yascheduler_nodes
ALTER COLUMN node_id ADD GENERATED ALWAYS AS IDENTITY;
SELECT setval(
    pg_get_serial_sequence('yascheduler_nodes', 'node_id'),
    (SELECT coalesce(max(node_id), 0) FROM yascheduler_nodes) + 1,
    false
);

ALTER TABLE yascheduler_tasks
ALTER COLUMN task_id DROP DEFAULT;
ALTER SEQUENCE yascheduler_tasks_task_id_seq OWNED BY NONE;
DROP SEQUENCE yascheduler_tasks_task_id_seq;
ALTER TABLE yascheduler_tasks
ALTER COLUMN task_id ADD GENERATED ALWAYS AS IDENTITY;
SELECT setval(
    pg_get_serial_sequence('yascheduler_tasks', 'task_id'),
    (SELECT coalesce(max(task_id), 0) FROM yascheduler_tasks) + 1,
    false
);
