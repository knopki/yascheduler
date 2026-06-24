## MODIFIED Requirements

### Requirement: add_tmp_node integration

Tests SHALL verify `PostgresNodeRepository.add_tmp(cloud)` generates a
provisional IP starting with "prov" and inserts a disabled node. The
`username` column falls back to its DB default (`'root'`); the test SHALL
NOT pass a `username` argument and SHALL NOT assert a caller-supplied
username on the retrieved row.

#### Scenario: Temporary node creation
- **WHEN** `uow.nodes.add_tmp("az")` is called
- **THEN** the returned IP starts with "prov" and `uow.nodes.get(ip)` shows `enabled=False, cloud="az", username="root"` (the DB default)