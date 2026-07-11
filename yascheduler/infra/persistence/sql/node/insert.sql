INSERT INTO yascheduler_nodes (
    hostname,
    ncpus,
    enabled,
    cloud,
    username,
    port,
    jump_host,
    jump_port,
    jump_username,
    external_id,
    status
)
VALUES (
    :hostname,
    :ncpus,
    :enabled,
    :cloud,
    :username,
    :port,
    :jump_host,
    :jump_port,
    :jump_username,
    :external_id,
    :status
)
RETURNING node_id, created_at, updated_at;
