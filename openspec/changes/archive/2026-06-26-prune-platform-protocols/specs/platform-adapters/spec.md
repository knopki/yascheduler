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

#### Scenario: PProcessInfo Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PProcessInfo`
- **THEN** the `PProcessInfo` Protocol class is absent

#### Scenario: PNode Protocol removed
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `PNode`
- **THEN** the `PNode` Protocol class is absent

#### Scenario: ProcessInfo defined in protocol module
- **WHEN** `infra/ssh/platform/protocol.py` is inspected for `ProcessInfo`
- **THEN** a frozen dataclass `ProcessInfo` with fields `pid: int`, `name: str`, `command: str` is defined there

#### Scenario: Platform modules import ProcessInfo from protocol
- **WHEN** `infra/ssh/platform/linux.py` or `infra/ssh/platform/windows.py` is inspected for the `ProcessInfo` import
- **THEN** the import is `from .protocol import ProcessInfo` (not `from .common import ProcessInfo`)

#### Scenario: Package init imports ProcessInfo from protocol
- **WHEN** `infra/ssh/platform/__init__.py` is inspected for the `ProcessInfo` import
- **THEN** `ProcessInfo` is imported from `.protocol` and remains in `__all__`

#### Scenario: common.py does not define ProcessInfo
- **WHEN** `infra/ssh/platform/common.py` is inspected for `ProcessInfo`
- **THEN** no `ProcessInfo` class is defined there

#### Scenario: PProcessInfo and PNode absent from package re-export
- **WHEN** `infra/ssh/platform/__init__.py` is inspected for `PProcessInfo` or `PNode`
- **THEN** neither name appears in the `from .protocol import (...)` block nor in `__all__`