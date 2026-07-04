SELECT
    node_id,
    ip,
    ncpus,
    enabled,
    cloud,
    username,
    port
FROM yascheduler_nodes
WHERE node_id = ANY(:node_ids);
