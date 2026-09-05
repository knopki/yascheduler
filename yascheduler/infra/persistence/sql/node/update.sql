UPDATE yascheduler_nodes
SET
    hostname = :hostname,
    ncpus = :ncpus,
    enabled = :enabled,
    cloud = :cloud,
    username = :username,
    port = :port,
    jump_host = :jump_host,
    jump_port = :jump_port,
    jump_username = :jump_username,
    external_id = :external_id,
    status = :status
WHERE node_id = :node_id
RETURNING node_id;
