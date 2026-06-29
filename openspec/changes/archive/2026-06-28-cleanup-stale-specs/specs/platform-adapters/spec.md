## MODIFIED Requirements

### Requirement: Platform code relocated

The system SHALL provide all platform-specific modules in
`infra/ssh/platform/` as the sole location. The `remote_machine/` package
SHALL NOT exist. The `PEngine` and `PEngineRepository` Protocols SHALL NOT
exist in `infra/ssh/platform/protocol.py`; platform modules
(`infra/ssh/platform/linux.py`, `infra/ssh/platform/windows.py`,
`infra/ssh/gateway.py`) SHALL import `Engine`, `EngineRepository`, and
`Deploy*` (`LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`)
from `yascheduler.domain` directly.

The `PProcessInfo` and `PNode` Protocols SHALL NOT exist in
`infra/ssh/platform/protocol.py`. The `ProcessInfo` frozen dataclass (fields
`pid: int`, `name: str`, `command: str`) SHALL be defined in
`infra/ssh/platform/protocol.py`. Platform modules
(`infra/ssh/platform/linux.py`, `infra/ssh/platform/windows.py`) and the
package `infra/ssh/platform/__init__.py` SHALL import `ProcessInfo` from
`.protocol` (or the package re-export), not from `.common`.
`infra/ssh/platform/common.py` SHALL NOT define `ProcessInfo`.

#### Scenario: Adapters accessible at new location
- **WHEN** the adapters module is imported from infra.ssh.platform.adapters
- **THEN** the adapter registry is accessible

#### Scenario: Platform checks accessible
- **WHEN** check_is_linux is imported from infra.ssh.platform.checks
- **THEN** the check function is accessible

#### Scenario: OS-specific methods accessible
- **WHEN** linux_setup_node is imported from infra.ssh.platform.linux
- **THEN** the function is accessible

#### Scenario: PEngine Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PEngine`
- **THEN** the `PEngine` Protocol class is absent; consumers import `Engine` from `yascheduler.domain`