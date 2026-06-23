INSERT INTO yascheduler_nodes (ip, enabled, cloud, username)
VALUES ('prov' || SUBSTR(MD5(RANDOM()::TEXT), 0, 11), FALSE, :cloud, :username)
RETURNING ip;
