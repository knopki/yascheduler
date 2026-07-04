UPDATE yascheduler_nodes
SET
    ip = :ip,
    ncpus = :ncpus,
    enabled = :enabled,
    cloud = :cloud,
    username = :username,
    port = :port
WHERE node_id = :node_id;
