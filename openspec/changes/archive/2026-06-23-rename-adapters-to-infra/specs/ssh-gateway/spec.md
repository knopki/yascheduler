## MODIFIED Requirements

### Requirement: SSHMachineGateway owns shared SSH infrastructure

The system SHALL provide all SSH infrastructure constants and helpers in
`infra/ssh/helpers.py`, including `ADAPTERS` registry, `DEFAULT_CONN_OPTS`,
`MySSHClient`, `MAX_SESSIONS`, `my_backoff_exc`, `_detect_platform`,
`_init_paths`, and `_resolve_tunnel`. `SSHMachineGateway` SHALL import these
from `infra/ssh/helpers.py`, not from `remote_machine/`.

#### Scenario: Gateway imports helpers from own package
- **WHEN** `gateway.py` imports `ADAPTERS`, `DEFAULT_CONN_OPTS`, `_detect_platform`
- **THEN** they are imported from `infra/ssh/helpers.py`

#### Scenario: Helpers functional equivalence
- **WHEN** `_detect_platform(conn, adapters)` is called from the new location
- **THEN** it returns the same adapter and platform list as the old implementation
