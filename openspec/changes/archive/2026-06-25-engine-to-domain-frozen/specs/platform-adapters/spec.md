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

#### Scenario: Adapters accessible at new location
- **WHEN** the adapters module is imported from adapters.ssh.platform.adapters
- **THEN** the adapter registry is accessible

#### Scenario: Platform checks accessible
- **WHEN** check_is_linux is imported from adapters.ssh.platform.checks
- **THEN** the check function is accessible

#### Scenario: OS-specific methods accessible
- **WHEN** linux_setup_node is imported from adapters.ssh.platform.linux
- **THEN** the function is accessible

#### Scenario: PEngine Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PEngine`
- **THEN** the `PEngine` Protocol class is absent; consumers import `Engine` from `yascheduler.domain`

#### Scenario: PEngineRepository Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PEngineRepository`
- **THEN** the `PEngineRepository` Protocol class is absent; consumers import `EngineRepository` from `yascheduler.domain`

#### Scenario: Platform modules import Deploy types from domain
- **WHEN** `infra/ssh/platform/linux.py` or `infra/ssh/platform/windows.py` is inspected for `Deploy*` imports
- **THEN** the import is `from yascheduler.domain import LocalArchiveDeploy, LocalFilesDeploy, RemoteArchiveDeploy` (not `from yascheduler.config import ...`)