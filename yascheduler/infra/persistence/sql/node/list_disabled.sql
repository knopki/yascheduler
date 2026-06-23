SELECT
    ip,
    ncpus,
    enabled,
    cloud,
    username,
    port
FROM yascheduler_nodes
WHERE enabled = FALSE;
