SELECT
    node_id,
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
    status,
    created_at,
    updated_at
FROM yascheduler_nodes
WHERE enabled = FALSE AND hostname <> '';
