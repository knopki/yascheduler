# Spec Delta: package-facades

## MODIFIED Requirements

### Requirement: Yascheduler facade public contract

The `Yascheduler` facade SHALL expose the query methods (`queue_get_tasks`,
`queue_get_tasks_async`, `queue_get_task`, `queue_get_task_async`) and the
submission method (`queue_submit_task`) with the public contract below. This
delta modifies only the `metadata` field reconstruction source; all other
clauses (signatures, `task_id` int marshalling, `node` object shape, `status`
enum, `label` string, `queue_submit_task` return) are unchanged. Each query
method SHALL return Mappings with EXACTLY the keys
`{task_id, label, status, metadata, node}`. The `_task_to_dict` helper SHALL be
the sole extraction site and SHALL construct the `metadata` Mapping inline from
the typed `Task` fields plus `extra` (was `t.context.to_metadata()`).

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
  (which now returns `TaskId`) and returns `(await submit_task(...)).value`.
- `status` SHALL be a `domain.TaskStatus` enum member (preserves `.name`
  access and cross-class IntEnum equality; NOT a plain `int`). Unchanged.
- `label` SHALL be the raw `task.label` string. Unchanged.
- `metadata` SHALL be a flat dict reconstructed from the typed `Task` fields
  plus `extra` — the SAME shape that `TaskContext.to_metadata()` produced
  before the drop-task-context-entity change. `_task_to_dict` SHALL construct
  the dict inline: the six typed fields (`engine`, `remote_folder`,
  `local_folder`, `webhook_url`, `webhook_custom_params`, `error`) with `None`
  values omitted, then `**task.extra` merged. The public dict shape
  `{task_id, label, status, metadata, node}` is UNCHANGED — only the
  construction source changes (was `t.context.to_metadata()`, now inline
  reconstruction from `t.engine` / `t.remote_folder` / `t.local_folder` /
  `t.webhook_url` / `t.webhook_custom_params` / `t.error` / `t.extra`). This
  preserves wire compatibility for any caller parsing the `metadata` dict.
- `node` SHALL be an object built from `nodes_by_id.get(task.allocated_node_id)`,
  or `null` when the task has no allocated node (`allocated_node_id` is
  `None`). When non-null, the object has exactly `{ip, port, username, cloud}`:
  - `ip`: the raw `node.ip` string (replaces the flat `ip` key, which was
    `allocated_ip or ""`).
  - `port`: the raw `node.port` int.
  - `username`: the raw `node.username` string.
  - `cloud`: the raw `node.cloud` string, or `null` for static nodes.
  The `nodes_by_id` dict is obtained from the `query_tasks` use case, which
  returns `(list[Task], dict[NodeId, Node])` (see the `use-cases`
  capability). The facade unpacks the tuple and passes `nodes_by_id` to
  `_task_to_dict`.

The public contract is keyed on the resolvable symbol and applies
identically whether `Yascheduler` is imported via the package facade
(`from yascheduler import Yascheduler`), the entrypoints layer facade
(`from yascheduler.entrypoints import Yascheduler`), or the compat shim
(`from yascheduler.client import Yascheduler`).

#### Scenario: metadata dict is reconstructed from typed fields plus extra
- **WHEN** `_task_to_dict(t, nodes_by_id)` is called on a Task with `engine="cp2k"`, `remote_folder="/r"`, `local_folder=None`, `webhook_url=None`, `webhook_custom_params={"parent": 42}`, `error=None`, `extra={"input.in": "ATOMS"}`
- **THEN** the returned Mapping's `metadata` value is `{"engine": "cp2k", "remote_folder": "/r", "webhook_custom_params": {"parent": 42}, "input.in": "ATOMS"}` (None-valued `local_folder`/`webhook_url`/`error` omitted; `extra` merged in) — the SAME shape that `TaskContext.to_metadata()` produced before the change

#### Scenario: metadata dict omits all None typed fields
- **WHEN** `_task_to_dict(t, nodes_by_id)` is called on a Task with `remote_folder=None`, `local_folder=None`, `webhook_url=None`, `error=None`, `extra={}`
- **THEN** the returned Mapping's `metadata` value contains only the non-None typed fields (e.g. `{"engine": "cp2k", "webhook_custom_params": {}}`); the None-valued fields are absent (preserving the `to_metadata()` omission behavior)

#### Scenario: metadata dict shape unchanged from caller perspective
- **WHEN** a caller inspects `queue_get_tasks_async(jobs=[1])` output before and after the drop-task-context-entity change
- **THEN** the `metadata` Mapping has the same keys and values for the same task (the reconstruction produces the same flat dict that `to_metadata()` did) — wire compatibility preserved

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
- **THEN** it is a bare `int` (NOT a `TaskId` instance); the facade extracted `.value` via `_task_to_dict` so the public `int`-typed contract is preserved

#### Scenario: queue_get_task single-task returns Optional Mapping
- **WHEN** `queue_get_task(42)` is called and the task exists
- **THEN** it returns a Mapping with exactly `{task_id, label, status, metadata, node}` (NOT a list); `queue_get_task(99999)` for a missing task returns `None`

#### Scenario: node object shape when allocated
- **WHEN** `_task_to_dict` is called on a Task with `allocated_node_id=NodeId(7)` and `nodes_by_id={NodeId(7): Node(ip="10.0.0.1", port=22, username="u", cloud="hetzner", ...)}`
- **THEN** the `node` value is `{"ip": "10.0.0.1", "port": 22, "username": "u", "cloud": "hetzner"}`

#### Scenario: node is null when not allocated
- **WHEN** `_task_to_dict` is called on a Task with `allocated_node_id=None`
- **THEN** the `node` value is `None` (null)

#### Scenario: queue_submit_task returns bare int
- **WHEN** `queue_submit_task(...)` is called
- **THEN** it returns a bare `int` (NOT a `TaskId`); the facade unwraps `.value` from the `submit_task` use case's `TaskId` return

#### Scenario: No TaskContext reference in _task_to_dict
- **WHEN** `_task_to_dict` is inspected for `TaskContext` or `to_metadata` references
- **THEN** none are present (the dict is constructed inline from `t.engine`, `t.remote_folder`, `t.local_folder`, `t.webhook_url`, `t.webhook_custom_params`, `t.error`, `t.extra`)