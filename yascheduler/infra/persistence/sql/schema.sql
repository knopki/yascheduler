CREATE TABLE IF NOT EXISTS yascheduler_nodes (
    ip VARCHAR(15) UNIQUE,
    port INTEGER DEFAULT 22,
    username VARCHAR(255) DEFAULT 'root',
    ncpus SMALLINT DEFAULT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    cloud VARCHAR(32) DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS yascheduler_tasks (
    task_id SERIAL PRIMARY KEY,
    label VARCHAR(256),
    metadata JSONB,
    ip VARCHAR(15),
    status SMALLINT
);

ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS username VARCHAR(255) DEFAULT 'root';

ALTER TABLE yascheduler_nodes
ADD COLUMN IF NOT EXISTS port INTEGER DEFAULT 22;
