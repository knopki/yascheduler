## MODIFIED Requirements

### Requirement: PostgresNodeRepository implements NodeRepository

The system SHALL provide a `PostgresNodeRepository` class that satisfies
the `NodeRepository` Protocol with async methods: `get`, `list_enabled`,
`list_disabled`, `list_all`, `add`, `add_tmp`, `update`, `enable`,
`disable`, `remove`, `get_by_ips`, `count_by_cloud`, `count_by_status`.

`add_tmp(cloud: str) -> str` inserts a tmp-node row with a generated IP,
`enabled=FALSE`, the given cloud, and `username` left to the DB default
(`yascheduler_nodes.username DEFAULT 'root'`). It SHALL NOT bind a
`:username` parameter; the `node/insert_tmp.sql` query lists only
`(ip, enabled, cloud)` columns.

#### Scenario: Add and retrieve node
- **WHEN** `add(node)` is called followed by `get(ip)`
- **THEN** the returned Node matches the inserted values

#### Scenario: Enable and disable node
- **WHEN** `disable(ip)` is called on an enabled node, then `get(ip)`
- **THEN** `node.enabled` is False

#### Scenario: List enabled nodes
- **WHEN** `list_enabled()` is called with a mix of enabled and disabled nodes
- **THEN** returns only nodes with `enabled=True` and valid IPs (containing ".")

#### Scenario: List all nodes
- **WHEN** `list_all()` is called
- **THEN** returns all nodes regardless of enabled status

#### Scenario: Add temporary node
- **WHEN** `add_tmp(cloud)` is called
- **THEN** a node row is inserted with generated IP, the given cloud, and `username` defaulting to `'root'` (from the DB column default, not a caller-supplied value)

#### Scenario: Update node fields
- **WHEN** `update(node)` is called with modified fields
- **THEN** all mutable fields are persisted

#### Scenario: Get nodes by IPs
- **WHEN** `get_by_ips(["10.0.0.1", "10.0.0.2"])` is called
- **THEN** returns a dict keyed by IP for matching nodes

#### Scenario: Count by cloud
- **WHEN** `count_by_cloud()` is called
- **THEN** returns a mapping of cloud provider name to node count

#### Scenario: Count by status
- **WHEN** `count_by_status()` is called
- **THEN** returns a mapping of enabled (bool) to node count

#### Scenario: Remove node
- **WHEN** `remove(ip)` is called
- **THEN** the node row is deleted from the database