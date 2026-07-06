# Delta: cli

## MODIFIED Requirements

### Requirement: yastatus queries task status

The `yastatus` command SHALL query and display task status, optionally with
remote machine output (verbose mode) and convergence info, resolving nodes via
`get_by_ids` (batch lookup by `allocated_node_id`). The command is implemented
as `check_status()` in `yascheduler/entrypoints/cli/check_status.py`, a
synchronous entry point that calls `asyncio.run(_check_status_async(argv))`
and accepts `argv: list[str] | None = None` for testability.

In view/json mode, the command SHALL open a single query-phase UoW, read
tasks via `_query_tasks(uow, args)`, and read nodes via
`uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if
t.allocated_node_id])` (a single batch round-trip), building
`nodes_by_id: dict[NodeId, Node]`. The UoW is closed before any SSH work
in the view path.

The renderers SHALL look up nodes via `nodes_by_id.get(task.allocated_node_id)`.
The `_render_json` output object SHALL emit a nested `node` object (see the
"yastatus --json output format" requirement) built from the resolved `Node`,
and SHALL NOT emit flat `allocated_ip`/`port`/`cloud` fields (those are
removed in favor of the nested `node`). The `_render_info` renderer SHALL emit
`node_id={task.allocated_node_id}` (was `ip={task.allocated_ip}`) as the
placement field, because the `Task` entity no longer carries `allocated_ip`.

The `_display_remote_output` helper SHALL resolve the node via
`nodes_by_id.get(task.allocated_node_id)`, build `_ConnParams` from the
node (via `_resolve_conn_params(node, config)`), and connect via
`SSHMachineRepository().connect(node, ...)` (passing the `Node` so the
session registers under `node.node_id`). The finally block SHALL call
`repository.disconnect(session.machine.node_id)`. The verbose renderer
(`_render_view`) SHALL use `node.ip` (the resolved `Node`'s transport
address) in its display line, NOT `task.allocated_ip` (which is removed).

#### Scenario: yastatus queries tasks via CLIDeps

- **WHEN** yastatus is invoked (default mode, `-i`, `--json`, or `-v`)
- **THEN** it obtains `CLIDeps` via `make_cli_deps(config)` and uses `deps.uow_factory` to open the query-phase UoW

#### Scenario: yastatus resolves nodes by allocated_node_id

- **WHEN** yastatus runs in view/json mode with a non-empty task set
- **THEN** it reads nodes via `uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if t.allocated_node_id])` and builds `nodes_by_id: dict[NodeId, Node]`; renderers look up nodes via `nodes_by_id.get(task.allocated_node_id)`

#### Scenario: yastatus does not read allocated_ip

- **WHEN** the `check_status.py` implementation is inspected
- **THEN** no code reads `task.allocated_ip` (the field is removed from `Task`); node transport address is obtained from the resolved `Node.ip` via `nodes_by_id`

### Requirement: yastatus --json output format

When `--json` is given, `yastatus` SHALL emit
`json.dumps(list_of_objects)` where each object represents one task with raw
domain values (NO display transformations — no `MAX`, no `-`, no banner).
The object schema SHALL be exactly these fields:

```
{"task_id": int, "status": str, "label": str, "engine": str,
 "local_folder": str | null, "remote_folder": str | null,
 "created_at": str, "updated_at": str,
 "node": {"ip": str, "port": int, "username": str, "cloud": str | null} | null}
```

- `task_id`: the raw `task.task_id.value` int.
- `status`: the `task.status.name` string (`"TO_DO"`, `"RUNNING"`, or
  `"DONE"`) — NOT an int, NOT a display token. Unchanged from the prior
  format.
- `label`: the raw `task.label` string. Unchanged (the DB column is `title`,
  but the domain field and JSON key remain `label`).
- `engine`: the raw `task.context.engine` string (always present —
  `TaskContext.engine` is a required field). Unchanged.
- `local_folder`: the raw `task.context.local_folder` string, or `null`.
  Unchanged.
- `remote_folder`: the raw `task.context.remote_folder` string, or `null`.
  Unchanged.
- `created_at`: the `task.created_at` datetime serialized as an ISO-8601
  string (via `.isoformat()`). New field (the DB column is added by migration
  007).
- `updated_at`: the `task.updated_at` datetime serialized as an ISO-8601
  string. New field.
- `node`: an object built from `nodes_by_id.get(task.allocated_node_id)`,
  or `null` when the task has no allocated node (`allocated_node_id` is
  `None`, e.g. a `TO_DO` task or a task whose node was deleted). When
  non-null, the object has exactly:
  - `ip`: the raw `node.ip` string (was the flat `allocated_ip` field; now
    sourced from the resolved `Node`).
  - `port`: the raw `node.port` int (was the flat `port` field; now sourced
    from the resolved `Node`).
  - `username`: the raw `node.username` string. New nested field (was not
    in the flat 9-field shape).
  - `cloud`: the raw `node.cloud` string, or `null` for static nodes (was
    the flat `cloud` field; now sourced from the resolved `Node`).

The flat `allocated_ip`, `port`, and `cloud` fields are REMOVED and
replaced by the nested `node` object. This is a **BREAKING** change to the
`yastatus --json` wire format.

One object per task, in the order returned by the query
(`list_by_status` or `list_by_jobs`). `--json` SHALL be in the
`mutually_exclusive_group` with `-v` and `-i`; convergence (`-o`) is NOT
part of `--json` (mixing machine-readable JSON with ephemeral scientific
output is excluded by design).

#### Scenario: yastatus --json emits a list of objects
- **WHEN** `yastatus --json` is invoked against a non-empty task set
- **THEN** the output is valid JSON parseable as a list of objects, one per task, in query order

#### Scenario: yastatus --json uses raw status name
- **WHEN** a task has status `RUNNING`
- **THEN** the JSON object's `status` field is the string `"RUNNING"` (NOT `1`, NOT `"running"`) — unchanged

#### Scenario: yastatus --json uses nested node object
- **WHEN** a task is allocated to a node with `ip="10.0.0.1"`, `port=22`, `username="root"`, `cloud="hetzner"`
- **THEN** the JSON object's `node` field is `{"ip": "10.0.0.1", "port": 22, "username": "root", "cloud": "hetzner"}` (a nested object, NOT the flat `allocated_ip`/`port`/`cloud` fields)

#### Scenario: yastatus --json TO_DO task has null node
- **WHEN** a `TO_DO` task (no `allocated_node_id`) is rendered via `--json`
- **THEN** the JSON object's `node` field is `null` (the task has not been placed on a node yet); the flat `allocated_ip`, `port`, and `cloud` fields are ABSENT (replaced by the nested `node`)

#### Scenario: yastatus --json includes audit timestamps
- **WHEN** a task with `created_at` and `updated_at` datetimes is rendered via `--json`
- **THEN** the JSON object's `created_at` and `updated_at` fields are ISO-8601 strings (e.g. `"2026-07-06T12:00:00+00:00"`)

#### Scenario: yastatus --json engine always present
- **WHEN** a task with `context.engine="g09"` is rendered via `--json`
- **THEN** the JSON object's `engine` field is `"g09"` (never null — `TaskContext.engine` is required)

#### Scenario: yastatus --json empty result is empty list
- **WHEN** `yastatus --json` is invoked and the query returns no tasks
- **THEN** the output is `[]` and the process exits `0`

#### Scenario: yastatus --json composes with -j
- **WHEN** `yastatus -j 1 2 --json` is invoked
- **THEN** `list_by_jobs(job_ids=["1", "2"])` is called and the JSON renderer prints the result (the `-j` filter composes with `--json`)

### Requirement: yanodes joins nodes to running tasks in memory

`show_nodes()` SHALL perform the node-to-running-task join in memory within a
single UoW: it SHALL read `uow.nodes.list_all()` and
`uow.tasks.list_by_status({TaskStatus.RUNNING})` (two reads within one UoW),
build a `tasks_by_node_id` dict mapping `allocated_node_id` to the single
running task on that node (O(n+m) single pass over tasks), and look up each
node's task via `tasks_by_node_id.get(node.node_id)`. It SHALL NOT perform an
O(n*m) nested scan.

The join key is `node_id` (the task's `allocated_node_id` matches the node's
`node_id`), NOT `ip`. The `allocated_ip` field is removed from `Task`; the
join is by `allocated_node_id` exclusively. This requirement text is updated
to remove the stale `tasks_by_ip`/`allocated_ip` references that lingered after
the ssh-rekey-node-id change.

#### Scenario: yanodes join is O(n+m)
- **WHEN** the implementation of `_fetch_nodes_view` (or equivalent) is inspected
- **THEN** it builds a `tasks_by_node_id` dict once and looks up each node's task by `node_id` via dict access, rather than scanning the full task list per node

#### Scenario: yanodes reads nodes and tasks within one UoW
- **WHEN** `show_nodes()` is invoked
- **THEN** both `uow.nodes.list_all()` and `uow.tasks.list_by_status({TaskStatus.RUNNING})` are called within the same `async with deps.uow_factory() as uow:` block

#### Scenario: yanodes join key is node_id not ip
- **WHEN** the in-memory join is built
- **THEN** the dict is `tasks_by_node_id = {t.allocated_node_id: t for t in tasks if t.allocated_node_id is not None}` and each node is matched via `tasks_by_node_id.get(node.node_id)`; no `allocated_ip` or `ip`-keyed dict is used