SELECT
    node_id,
    ip,
    ncpus,
    enabled,
    cloud,
    username,
    port
FROM yascheduler_nodes
ORDER BY node_id;
