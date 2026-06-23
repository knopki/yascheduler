SELECT
    enabled,
    COUNT(ip) AS count
FROM yascheduler_nodes
GROUP BY enabled
ORDER BY enabled;
