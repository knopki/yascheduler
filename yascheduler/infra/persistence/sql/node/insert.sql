INSERT INTO yascheduler_nodes (ip, ncpus, enabled, cloud, username, port)
VALUES (:ip, :ncpus, :enabled, :cloud, :username, :port)
RETURNING node_id;
