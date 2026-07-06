# Delta: package-facades

## MODIFIED Requirements

### Requirement: Yascheduler client query method public contract

The `Yascheduler` class SHALL preserve its public query API across the
introduction of the `TaskId` domain value object and the removal of
`allocated_ip`. The class is defined in `yascheduler/entrypoints/client.py`
and re-exported via `from yascheduler import Yascheduler` (package facade) and
`from yascheduler.client import Yascheduler` (compat shim); the public
contract is keyed on the resolvable symbol, not the file path.

- `Yascheduler()` zero-arg construction SHALL remain valid.
- `Yascheduler(config_path, logger)` positional callsites SHALL remain valid.
- `Yascheduler(config_path, logger, *, deps_factory=None)` SHALL add
  `deps_factory` as a keyword-only optional parameter (lazy default
  `make_cli_deps`), used as a test-injection seam.
- `queue_get_tasks(jobs, status)`, `queue_get_tasks_async(jobs, status)`,
  `queue_get_task(task_id)`, and `queue_get_task_async(task_id)` signatures
  SHALL NOT change; their public `task_id`/`jobs` parameters stay `int` /
  `list[int]`.
- Each query method SHALL return Mappings (a `Sequence[Mapping]` for the
  list variants `queue_get_tasks` / `queue_get_tasks_async`, an
  `Optional[Mapping]` for the single-task variants `queue_get_task` /
  `queue_get_task_async`) with EXACTLY the keys
  `{task_id, label, status, metadata, node}`. The flat `ip` and `cloud` keys
  are REMOVED and replaced by a nested `node` key. This is a **BREAKING**
  change to the facade dict shape (was `{task_id, label, ip, status, metadata,
  cloud}`).
- The `task_id` value in each returned Mapping SHALL be a bare `int` (NOT a
  `TaskId`). The private `_task_to_dict(t: Task, nodes_by_id: dict[NodeId,
  Node])` helper is the sole extraction site: it builds the dict with
  `"task_id": t.task_id.value` so the public dict preserves the `int` shape.
  The `Yascheduler` facade is the **sole** `int`/`TaskId` marshalling boundary,
  in both directions: on input (`queue_get_task(task_id: int)` /
  `queue_get_tasks(jobs: list[int])`) it wraps `TaskId(task_id)` /
  `[TaskId(i) for i in jobs]` before calling the use cases / repository; on
  output it extracts `.value` via `_task_to_dict`.
- `queue_submit_task(...) -> int` SHALL stay `int`; it wraps `submit_task`
  (which returns `TaskId`) and returns `(await submit_task(...)).value`.
- `status` SHALL be a `domain.TaskStatus` enum member (preserves `.name`
  access and cross-class IntEnum equality; NOT a plain `int`). Unchanged.
- `label` SHALL be the raw `task.label` string. Unchanged.
- `metadata` SHALL be the raw `task.context` metadata dict. Unchanged.
- `node` SHALL be an object built from `nodes_by_id.get(task.allocated_node_id)`,
  or `null` when the task has no allocated node (`allocated_node_id` is
  `None`). When non-null, the object has exactly `{ip, port, username, cloud}`:
  - `ip`: the raw `node.ip` string (replaces the flat `ip` key, which was
    `allocated_ip or ""`).
  - `port`: the raw `node.port` int.
  - `username`: the raw `node.username` string.
  - `cloud`: the raw `node.cloud` string, or `null` for static nodes.
  The `nodes_by_id` dict is obtained from the `query_tasks` use case, which
  now returns `(list[Task], dict[NodeId, Node])` (see the `use-cases`
  capability). The facade unpacks the tuple and passes `nodes_by_id` to
  `_task_to_dict`. The facade does NOT open its own UoW; it delegates to the
  use case, which owns the UoW and the node batch-load.

The public contract is keyed on the resolvable symbol and applies
identically whether `Yascheduler` is imported via the package facade
(`from yascheduler import Yascheduler`), the entrypoints layer facade
(`from yascheduler.entrypoints import Yascheduler`), or the compat shim
(`from yascheduler.client import Yascheduler`).

#### Scenario: Zero-arg construction remains valid
- **WHEN** `Yascheduler()` is called with no arguments
- **THEN** the client is constructed successfully and `queue_get_tasks_async` is invokable

#### Scenario: deps_factory is keyword-only
- **WHEN** `Yascheduler(config_path, logger, my_factory)` is called with `deps_factory` positionally
- **THEN** a `TypeError` is raised

#### Scenario: Query returns five-key dict with nested node
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a non-empty result
- **THEN** each Mapping has exactly the keys `{task_id, label, status, metadata, node}` and no others; the flat `ip` and `cloud` keys are absent

#### Scenario: task_id in returned dict is a bare int
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a task with `task_id=TaskId(1)`
- **THEN** the Mapping's `task_id` value is the int `1` (NOT a `TaskId` instance)

#### Scenario: status in returned dict is a TaskStatus enum member
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a RUNNING task
- **THEN** the Mapping's `status` value is `TaskStatus.RUNNING` (an IntEnum member, `.value == 1`, `.name == "RUNNING"`)

#### Scenario: node is null for unallocated task
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a `TO_DO` task with `allocated_node_id=None`
- **THEN** the Mapping's `node` value is `null` (the task has no allocated node)

#### Scenario: node carries ip, port, username, cloud for allocated task
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a task allocated to a node with `ip="10.0.0.1"`, `port=22`, `username="root"`, `cloud="hetzner"`
- **THEN** the Mapping's `node` value is `{"ip": "10.0.0.1", "port": 22, "username": "root", "cloud": "hetzner"}`

#### Scenario: label and metadata are unchanged
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a task with `label="my_job"` and `context` metadata `{"input": "data"}`
- **THEN** the Mapping's `label` is `"my_job"` and `metadata` is `{"input": "data"}` (both unchanged from the prior format)