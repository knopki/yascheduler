## REMOVED Requirements

### Requirement: ConfigLocal migrated to stdlib dataclass

## MODIFIED Requirements

### Requirement: SSH private-key discovery as a pure function

The system SHALL provide `list_private_keys(keys_dir: Path) -> Sequence[PurePath]` in `yascheduler/infra/ssh/keys.py` that scans the given directory for SSH private-key files and returns their paths. The function SHALL be a module-level function taking an explicit `keys_dir` argument (not a method on a config dataclass).

`LocalSettings` carries a `keys_dir: Path` field consumed by the call sites below.

The four production call sites SHALL obtain private keys as follows:
- `infra/cloud/manager.py`, `entrypoints/cli/manage_node.py`, and `entrypoints/cli/check_status.py` SHALL import `list_private_keys` from `yascheduler.infra.ssh.keys` and call `list_private_keys(config.local.keys_dir)` (intra-infra or entrypoints→infra — R3-legal).
- `application/orchestrator.py` SHALL NOT import from `yascheduler.infra` (application is below infra in the layers contract). The orchestrator SHALL receive `list_private_keys_fn: Callable[[Path], Sequence[PurePath]]` as a constructor parameter, store it, and pass it (together with `self._config.local.keys_dir`) to `run_in_executor` at the `_connect_machine_consumer` call site. The composition root `yascheduler/entrypoints/di.py` SHALL import `list_private_keys` and inject it as `list_private_keys_fn=list_private_keys` when constructing the `Orchestrator`.

#### Scenario: list_private_keys returns key paths from keys_dir
- **WHEN** `list_private_keys(keys_dir)` is called with a directory containing SSH private-key files
- **THEN** it returns a sequence of `PurePath` for each discovered key file

#### Scenario: list_private_keys called from orchestrator
- **WHEN** the orchestrator connects to a machine
- **THEN** it passes the injected `list_private_keys_fn` (a `Callable[[Path], Sequence[PurePath]]` received in the constructor) together with `self._config.local.keys_dir` to `run_in_executor` at the `_connect_machine_consumer` call site; `application/orchestrator.py` imports nothing from `yascheduler.infra`

#### Scenario: list_private_keys called from cloud manager
- **WHEN** the cloud provisioner connects to a newly created VM
- **THEN** it calls `list_private_keys(config.local.keys_dir)` to obtain client keys

#### Scenario: list_private_keys called from manage_node CLI
- **WHEN** the `yasetnode` command connects to a remote host
- **THEN** it calls `list_private_keys(config.local.keys_dir)` to obtain client keys

#### Scenario: list_private_keys called from check_status CLI
- **WHEN** the `yastatus` command connects to a remote host to display output
- **THEN** it calls `list_private_keys(config.local.keys_dir)` to obtain client keys

#### Scenario: composition root injects list_private_keys into orchestrator
- **WHEN** `make_daemon` constructs the `Orchestrator`
- **THEN** it imports `list_private_keys` from `yascheduler.infra.ssh.keys` and passes `list_private_keys_fn=list_private_keys` to the `Orchestrator(...)` constructor (entrypoints→infra, R3-legal)

#### Scenario: orchestrator has no infra import
- **WHEN** `yascheduler/application/orchestrator.py` is inspected
- **THEN** it has no runtime import from `yascheduler.infra` (the layers contract `application → infra` violation is not introduced)
