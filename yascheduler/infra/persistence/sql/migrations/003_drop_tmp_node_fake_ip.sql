ALTER TABLE yascheduler_nodes DROP CONSTRAINT yascheduler_nodes_ip_key;

UPDATE yascheduler_nodes SET ip = ''
WHERE ip LIKE 'prov%';
