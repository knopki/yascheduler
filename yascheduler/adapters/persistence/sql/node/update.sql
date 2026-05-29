UPDATE yascheduler_nodes
SET ncpus=:ncpus, enabled=:enabled, cloud=:cloud, username=:username, port=:port
WHERE ip=:ip;
