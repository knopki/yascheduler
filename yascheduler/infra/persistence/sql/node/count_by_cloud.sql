SELECT
    cloud,
    COUNT(cloud) AS count
FROM yascheduler_nodes
WHERE cloud IS NOT NULL
GROUP BY cloud;
