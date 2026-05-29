SELECT
    ip,
    ncpus,
    enabled,
    cloud,
    username,
    port
FROM yascheduler_nodes
WHERE ip IN (SELECT unnest(cast(:ips AS text [])));
