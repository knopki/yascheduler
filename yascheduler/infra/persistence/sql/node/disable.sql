UPDATE yascheduler_nodes SET enabled = FALSE
WHERE node_id = :node_id
RETURNING node_id;
