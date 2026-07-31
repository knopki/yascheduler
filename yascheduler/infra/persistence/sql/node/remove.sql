DELETE FROM yascheduler_nodes
WHERE node_id = :node_id
RETURNING node_id;
