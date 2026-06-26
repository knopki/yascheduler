## Purpose

Pure-function SSH private-key discovery from a keys directory, consumed by the
orchestrator (as an injected callable), the cloud provisioner, and the
node-management CLI. Complementary `ConfigLocal` dataclass migration covering
the removed `get_private_keys` method and the stdlib frozen-dataclass
representation.

## Requirements

### Requirement: SSH private-key discovery as a pure function

The system SHALL provide `list_private_keys(keys_dir: Path) -> Sequence[PurePath]` in `yascheduler/infra/ssh/keys.py` that scans the given directory for SSH private-key files and returns their paths. The function SHALL NOT be a method on a config dataclass; it SHALL be a module-level function taking an explicit `keys_dir` argument. The function SHALL preserve the existing discovery behavior of the removed `ConfigLocal.get_private_keys()` method (same directory scan, same file matching).

`ConfigLocal` SHALL retain a `keys_dir: Path` field but SHALL NOT carry a `get_private_keys()` method.

The four production call sites SHALL obtain private keys as follows:
- `infra/cloud/manager.py` and `entrypoints/cli/manage_node.py` and `entrypoints/cli/check_status.py` SHALL import `list_private_keys` from `yascheduler.infra.ssh.keys` and call `list_private_keys(config.local.keys_dir)` (intra-infra or entrypoints→infra — R3-legal).
- `application/orchestrator.py` SHALL NOT import from `yascheduler.infra` (application is below infra in the layers contract). The orchestrator SHALL receive `list_private_keys_fn: Callable[[Path], Sequence[PurePath]]` as a constructor parameter, store it, and pass it (together with `self._config.local.keys_dir`) to `run_in_executor` at the `_connect_machine_consumer` call site (same shape as the prior `self._config.local.get_private_keys` bound-method reference, now taking the keys_dir argument explicitly). The composition root `yascheduler/entrypoints/di.py` SHALL import `list_private_keys` and inject it as `list_private_keys_fn=list_private_keys` when constructing the `Orchestrator`.

#### Scenario: list_private_keys returns key paths from keys_dir
- **WHEN** `list_private_keys(keys_dir)` is called with a directory containing SSH private-key files
- **THEN** it returns a sequence of `PurePath` for each discovered key file, matching the prior `ConfigLocal.get_private_keys()` behavior

#### Scenario: list_private_keys called from orchestrator
- **WHEN** the orchestrator connects to a machine
- **THEN** it passes the injected `list_private_keys_fn` (a `Callable[[Path], Sequence[PurePath]]` received in the constructor) together with `self._config.local.keys_dir` to `run_in_executor` at the `_connect_machine_consumer` call site; `application/orchestrator.py` imports nothing from `yascheduler.infra`

#### Scenario: list_private_keys called from cloud manager
- **WHEN** the cloud provisioner connects to a newly created VM
- **THEN** it calls `list_private_keys(config.local.keys_dir)` to obtain client keys, not `config.local.get_private_keys()`

#### Scenario: list_private_keys called from manage_node CLI
- **WHEN** the `yasetnode` command connects to a remote host
- **THEN** it calls `list_private_keys(config.local.keys_dir)` to obtain client keys, not `config.local.get_private_keys()`

#### Scenario: list_private_keys called from check_status CLI
- **WHEN** the `yastatus` command connects to a remote host to display output
- **THEN** it calls `list_private_keys(config.local.keys_dir)` to obtain client keys, not `config.local.get_private_keys()`

#### Scenario: composition root injects list_private_keys into orchestrator
- **WHEN** `make_daemon` constructs the `Orchestrator`
- **THEN** it imports `list_private_keys` from `yascheduler.infra.ssh.keys` and passes `list_private_keys_fn=list_private_keys` to the `Orchestrator(...)` constructor (entrypoints→infra, R3-legal)

#### Scenario: orchestrator has no infra import
- **WHEN** `yascheduler/application/orchestrator.py` is inspected after the change
- **THEN** it has no runtime import from `yascheduler.infra` (the layers contract `application → infra` violation is not introduced)

#### Scenario: ConfigLocal has no get_private_keys method
- **WHEN** `ConfigLocal` is inspected after migration
- **THEN** it has no `get_private_keys` attribute; only the `keys_dir: Path` field remains

### Requirement: ConfigLocal migrated to stdlib dataclass

`ConfigLocal` SHALL be a stdlib `@dataclass(frozen=True)` instead of an attrs `@define(frozen=True)`. Field validation previously expressed via attrs `validators.instance_of` and `validators.ge` SHALL move into a `__post_init__` method that raises `ValueError` on violation. `ConfigLocal` SHALL remain importable from `yascheduler.config` (the package is not removed in this change).

#### Scenario: ConfigLocal is a frozen stdlib dataclass
- **WHEN** `ConfigLocal` is inspected
- **THEN** it is decorated with `@dataclass(frozen=True)` from the stdlib `dataclasses` module, not `@define` from `attrs`

#### Scenario: ConfigLocal validates field constraints
- **WHEN** a `ConfigLocal` is constructed with `allocate_limit=0`
- **THEN** `__post_init__` raises `ValueError` (preserving the prior attrs `validators.ge(1)` behavior)

#### Scenario: ConfigLocal import path unchanged
- **WHEN** a consumer imports `from yascheduler.config import ConfigLocal`
- **THEN** the symbol resolves without ImportError