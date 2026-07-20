## MODIFIED Requirements

### Requirement: Public API stability

The system SHALL preserve the existing public API surface of the
`yascheduler` package across changes. Public API is defined as: exported
symbols resolvable via `from yascheduler import <name>`, constructor and
method signatures (parameter positions and names, return shapes), and
documented behavior.

Backward-compatible extensions (adding keyword-only optional parameters,
refining internal implementation, adding new public symbols) are
permitted; breaking changes (removing or repositioning parameters,
changing return shapes, removing exported symbols) SHALL be treated as a
new capability requiring explicit spec coverage.

Key stability rules:
- The package facade exports (`Yascheduler`, `CONFIG_FILE`,
  `LOG_FILE`, `PID_FILE`, `__version__`) SHALL remain resolvable.
- The deep import path `from yascheduler.client import Yascheduler` SHALL
  remain resolvable via the compat shim.
- The AiiDA scheduler entrypoint SHALL remain registered under the
  entry-point name `yascheduler` in `[project.entry-points."aiida.schedulers"]`.

#### Scenario: Yascheduler symbol resolves with backward-compatible signature
- **WHEN** a downstream consumer imports `from yascheduler import Yascheduler`
- **THEN** the symbol resolves and the zero-arg and positional constructors remain valid

#### Scenario: Deep import path resolves via compat shim
- **WHEN** a downstream consumer imports `from yascheduler.client import Yascheduler`
- **THEN** the symbol resolves without ImportError

#### Scenario: AiiDA plugin still loads under its entry-point name
- **WHEN** the AiiDA scheduler plugin is discovered via `importlib.metadata.entry_points(group="aiida.schedulers")`
- **THEN** the entry-point named `yascheduler` resolves to the object path `yascheduler.entrypoints.aiida_plugin:YaScheduler`

### Requirement: Yascheduler facade public contract

The `Yascheduler` facade SHALL expose the query methods (`queue_get_tasks`,
`queue_get_tasks_async`, `queue_get_task`, `queue_get_task_async`) and the
submission method (`queue_submit_task`) with the public contract below.
Each query method SHALL return Mappings with EXACTLY the keys
`{task_id, label, status, metadata, node}`.

- `queue_get_tasks(jobs, status)`, `queue_get_tasks_async(jobs, status)`,
  `queue_get_task(task_id)`, and `queue_get_task_async(task_id)` signatures
  SHALL NOT change; their public `task_id`/`jobs` parameters stay `int` /
  `list[int]`.
  - Each query method SHALL return Mappings (a `Sequence[Mapping]` for the
    list variants `queue_get_tasks` / `queue_get_tasks_async`, an
    `Optional[Mapping]` for the single-task variants `queue_get_task` /
    `queue_get_task_async`) with EXACTLY the keys
    `{task_id, label, status, metadata, node}`. The nested `node` key
    carries the allocated node's transport identity; the flat `ip` and
    `cloud` keys are NOT part of the shape.
  - The `task_id` value in each returned Mapping SHALL be a bare `int` (NOT a
    `TaskId`).
- `queue_submit_task(...) -> int` SHALL stay `int`.
- `status` SHALL be a `domain.TaskStatus` enum member (preserves `.name`
  access and cross-class IntEnum equality; NOT a plain `int`).
- `label` SHALL be the raw `task.label` string.
- `metadata` SHALL be a flat dict reconstructed from the typed `Task` fields
  plus `extra`: the six typed fields (`engine`, `remote_folder`,
  `local_folder`, `webhook_url`, `webhook_custom_params`, `error`) with `None`
  values omitted, then `**task.extra` merged.
- `node` SHALL be an object built from `nodes_by_id.get(task.allocated_node_id)`,
  or `null` when the task has no allocated node. When non-null, the object
  has exactly `{hostname, port, username, cloud}`:
  - `hostname`: the raw `node.hostname` string.
  - `port`: the raw `node.port` int.
  - `username`: the raw `node.username` string.
  - `cloud`: the raw `node.cloud` string, or `null` for static nodes.

The public contract applies identically across the package facade
(`from yascheduler import Yascheduler`), the entrypoints layer facade
(`from yascheduler.entrypoints import Yascheduler`), and the compat shim
(`from yascheduler.client import Yascheduler`).

#### Scenario: metadata dict is reconstructed from typed fields plus extra
- **WHEN** the extraction helper is called on a Task with `engine="cp2k"`, `remote_folder="/r"`, `local_folder=None`, `webhook_url=None`, `webhook_custom_params={"parent": 42}`, `error=None`, `extra={"input.in": "ATOMS"}`
- **THEN** the returned Mapping's `metadata` value is `{"engine": "cp2k", "remote_folder": "/r", "webhook_custom_params": {"parent": 42}, "input.in": "ATOMS"}` (None-valued `local_folder`/`webhook_url`/`error` omitted; `extra` merged in)

#### Scenario: metadata dict omits all None typed fields
- **WHEN** the extraction helper is called on a Task with `remote_folder=None`, `local_folder=None`, `webhook_url=None`, `error=None`, `extra={}`
- **THEN** the returned Mapping's `metadata` value contains only the non-None typed fields (e.g. `{"engine": "cp2k", "webhook_custom_params": {}}`)

#### Scenario: Zero-arg construction remains valid
- **WHEN** `Yascheduler()` is called with no arguments
- **THEN** the client is constructed successfully and `queue_get_tasks_async` is invokable

#### Scenario: deps_factory is keyword-only
- **WHEN** `Yascheduler(config_path, logger, make_cli_deps)` is called with `deps_factory` as a positional argument
- **THEN** `TypeError` is raised (the parameter is keyword-only via `*,`)

#### Scenario: task_id in returned Mapping is bare int
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a non-empty result
- **THEN** each Mapping has exactly the keys `{task_id, label, status, metadata, node}`; the flat `ip` and `cloud` keys are ABSENT (replaced by the nested `node` key)

#### Scenario: task_id value is bare int not TaskId
- **WHEN** the `task_id` value in a returned Mapping is inspected
- **THEN** it is a bare `int` (NOT a `TaskId` instance)

#### Scenario: queue_get_task single-task returns Optional Mapping
- **WHEN** `queue_get_task(42)` is called and the task exists
- **THEN** it returns a Mapping with exactly `{task_id, label, status, metadata, node}` (NOT a list); `queue_get_task(99999)` for a missing task returns `None`

#### Scenario: node object shape when allocated
- **WHEN** the extraction helper is called on a Task with `allocated_node_id=NodeId(7)` and `nodes_by_id={NodeId(7): Node(node_id=NodeId(7), hostname="10.0.0.1", port=22, username="u", cloud="hetzner", ...)}`
- **THEN** the `node` value is `{"hostname": "10.0.0.1", "port": 22, "username": "u", "cloud": "hetzner"}`

#### Scenario: node is null when not allocated
- **WHEN** the extraction helper is called on a Task with `allocated_node_id=None`
- **THEN** the `node` value is `None` (null)

#### Scenario: queue_submit_task returns bare int
- **WHEN** `queue_submit_task(...)` is called
- **THEN** it returns a bare `int` (NOT a `TaskId`)
