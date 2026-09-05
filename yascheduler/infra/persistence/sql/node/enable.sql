UPDATE yascheduler_nodes SET enabled = TRUE
WHERE node_id = :node_id
RETURNING node_id;
