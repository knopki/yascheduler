INSERT INTO yascheduler_nodes (ip, enabled, cloud)
VALUES ('prov' || SUBSTR(MD5(RANDOM()::TEXT), 0, 11), FALSE, :cloud)
RETURNING ip;
