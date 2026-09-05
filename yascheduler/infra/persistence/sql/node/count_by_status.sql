SELECT
    enabled,
    COUNT(node_id) AS count
FROM yascheduler_nodes
GROUP BY enabled
ORDER BY enabled;
