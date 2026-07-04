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

The renderers SHALL look up nodes via `nodes_by_id.get(task.allocated_node_id)`
(was `nodes_by_ip.get(task.allocated_ip)`). The `_render_json` output
object SHALL keep `allocated_ip` (transport display, unchanged wire
field) and continue reading `node.port`/`node.cloud` from the resolved
`Node`.

The `_display_remote_output` helper SHALL resolve the node via
`nodes_by_id.get(task.allocated_node_id)`, build `_ConnParams` from the
node (via `_resolve_conn_params(node, config)`), and connect via
`SSHMachineRepository().connect(node, ...)` (passing the `Node` so the
session registers under `node.node_id`). The finally block SHALL call
`repository.disconnect(session.machine.node_id)` (was
`repository.disconnect(session.ip)`).

#### Scenario: yastatus queries tasks via CLIDeps

- **WHEN** yastatus is invoked (default mode, `-i`, `--json`, or `-v`)
- **THEN** make_cli_deps() is called, tasks are read via `uow.tasks.list_by_status({RUNNING, TO_DO})` (default) or `uow.tasks.list_by_jobs(job_ids)` (with `-j`), and the selected renderer prints the result

#### Scenario: yastatus view/json resolves nodes via get_by_ids

- **WHEN** yastatus is invoked with `--view` or `--json` and tasks have `allocated_node_id` set
- **THEN** the query-phase UoW calls `uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if t.allocated_node_id])` (a single batch round-trip); the resulting `nodes_by_id: dict[NodeId, Node]` is closed over for the render phase

#### Scenario: yastatus _display_remote_output connects via Node

- **WHEN** `_display_remote_output` is called for a running task
- **THEN** it resolves the node via `nodes_by_id.get(task.allocated_node_id)`, builds `_ConnParams` from the node, connects via `SSHMachineRepository().connect(node, ...)` (the session registers under `node.node_id`), and disconnects via `repository.disconnect(session.machine.node_id)` in the finally block

### Requirement: yanodes lists nodes and their running tasks

The `yanodes` command SHALL list nodes and their currently running tasks. The command is implemented as `show_nodes()` in `yascheduler/entrypoints/cli/show_nodes.py`, a synchronous entry point that calls `asyncio.run(_show_nodes_async(argv))`. It SHALL accept an `argv: list[str] | None = None` parameter for testability. It SHALL obtain `Config` via `Config.from_config_parser`, build `CLIDeps` via `make_cli_deps(config)`, open a single UoW, read nodes via `uow.nodes.list_all()` and running tasks via `uow.tasks.list_by_status({TaskStatus.RUNNING})`, join them in memory, apply the active filters, and print the result via the selected renderer. Output row order SHALL preserve the order returned by `uow.nodes.list_all()` (no sorting). Each node SHALL produce exactly one output row (table) or one output object (JSON).

The in-memory join SHALL build `tasks_by_node_id: dict[NodeId, Task] =
{t.allocated_node_id: t for t in tasks if t.allocated_node_id is not
None}` (was `tasks_by_ip` keyed by `allocated_ip`). Each node is matched
to its running task via `tasks_by_node_id.get(node.node_id)` (was
`tasks_by_ip.get(node.ip)`). The one-RUNNING-task-per-node invariant
means a later task on the same `node_id` would overwrite, but the
invariant forbids that.

#### Scenario: yanodes entry point uses asyncio.run

- **WHEN** the `show_nodes` callable in `yascheduler/entrypoints/cli/show_nodes.py` is inspected
- **THEN** it is a synchronous `def show_nodes(argv: list[str] | None = None)` that calls `asyncio.run(_show_nodes_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

#### Scenario: yanodes joins nodes to tasks by node_id

- **WHEN** `_fetch_nodes_view` runs
- **THEN** it builds `tasks_by_node_id = {t.allocated_node_id: t for t in tasks if t.allocated_node_id is not None}` and matches each node to its task via `tasks_by_node_id.get(node.node_id)` (the join key is `node_id`, not `ip`)

### Requirement: yasetnode dispatches add and remove paths

After argparse succeeds and the `HostSpec` is parsed, `manage_node()` SHALL
open a short, read-only validation UoW via
`async with deps.uow_factory() as uow:`, resolve the target `Node` (via
`get_by_id(target.node_id)` on the node_id path, or via `get_by_id` after a
host-spec resolution on the host_spec path — the ip-keyed `get(spec.host)` is
REMOVED), and close it (without commit — nothing was mutated). It SHALL then
dispatch to exactly one helper, each of which opens its OWN UoW via
`deps.uow_factory()` to perform its mutations, commit, and print:

- If `already_there` and no remove flag: raise `ValueError` → top-level
  handler prints `Error: ...` to stderr, exits `1`. (Adding an existing
  node is an operator error; disabled nodes are re-enabled via the
  remove + add cycle, not by re-adding.)
- If NOT `already_there` and a remove flag is set: raise `ValueError` →
  top-level handler prints `Error: ...` to stderr, exits `1`.
- If `--remove-hard`: call `_remove_node_hard(deps, node: Node)` — inside its
  own UoW, list RUNNING task ids for `node.ip`, mark each DONE, remove the node
  via `uow.nodes.remove(node.node_id)`, commit.
- If `--remove-soft`: call `_remove_node_soft(deps, node: Node)` — inside its
  own UoW, if RUNNING tasks exist, disable the node via
  `uow.nodes.disable(node.node_id)`; else remove the node via
  `uow.nodes.remove(node.node_id)`; commit.
- Otherwise (add): resolve `username = spec.username or
  config.remote.username`, call `_add_node(deps, gateway, operations, spec,
  config, skip_setup)` (see the "yasetnode gateway lifecycle and resource
  safety" requirement for the V1-pattern add sequence).

A TOCTOU window exists between closing the validation UoW and opening the
dispatch helper's UoW; for a single-operator CLI this is accepted (see design
D18). Failure modes are benign and non-corrupting: add-on-already-present →
no-op / helper re-check → exit 1; remove-on-just-removed →
no-op / not-found → exit 1.

The remove helpers SHALL accept `node: Node` (not `ip: str`); the validation
UoW already fetched the `Node`, and passing it down avoids a re-fetch.
`tasks.list_ids_by_ip_and_status(node.ip, RUNNING)` stays ip-keyed
(`ip` is the cloud host identifier for the TaskRepository lookup — out of
scope for this change). User-facing stdout messages use `node.ip` (operators
read ip, not node_id).

The `NewNode` record constructed on the add path SHALL use
`ip=spec.host`, `port=spec.port`, `username=<resolved>`,
`ncpus=(spec.ncpus if spec.ncpus is not None else 0)`, `enabled=False` (the
row is inserted `enabled=FALSE` before connect; the V1-pattern add sequence
in "yasetnode gateway lifecycle and resource safety" flips it to `enabled=TRUE`
via `update` after setup).

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW

- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(args.config)` is called, `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineRepository` and an `SSHMachineOperations` (bound to that repository) are constructed at the top of `manage_node` (before any UoW is opened), a short read-only UoW is opened to resolve the target `Node` (by `get_by_id` on the node_id path, or via host-spec resolution on the host_spec path — `get(spec.host)` is removed), and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the repository and operations are passed to the add helper.

#### Scenario: yasetnode remove helpers take Node not ip

- **WHEN** `_remove_node_hard` or `_remove_node_soft` is inspected
- **THEN** the signature is `(deps, node: Node)` (not `(deps, ip: str)`); the validation UoW resolved the `Node` and passed it down

#### Scenario: yasetnode remove-hard marks running tasks DONE then removes node by node_id

- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked against a node with `node_id=7`, ip=10.0.0.1, and RUNNING task ids `[1, 2]`
- **THEN** inside `_remove_node_hard`'s own UoW, `uow.tasks.update_status(1, TaskStatus.DONE)` and `uow.tasks.update_status(2, TaskStatus.DONE)` are called, then `uow.nodes.remove(NodeId(7))` is called (node_id-keyed), then `uow.commit()` is called

#### Scenario: yasetnode remove-soft with tasks disables node by node_id

- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against a node with `node_id=7`, ip=10.0.0.1, and at least one RUNNING task
- **THEN** inside `_remove_node_soft`'s own UoW, `uow.nodes.disable(NodeId(7))` is called (node_id-keyed), `uow.nodes.remove(...)` is NOT called, and `uow.commit()` is called

### Requirement: yasetnode gateway lifecycle and resource safety

On the add path, `manage_node()` SHALL construct a single
`SSHMachineRepository` and a single `SSHMachineOperations` (bound to that
repository) at the top of the function (before opening any UoW) and pass
them as parameters to the add helper. The add helper `_add_node(deps,
repository, operations, spec, config, skip_setup)` SHALL adopt the
V1-pattern (same as cloud allocation): insert the row with `enabled=False`
BEFORE connecting, so the `Node` (carrying `node_id`) is in hand for
`connect(node, ...)`. The flow SHALL be:

1. Open a UoW, call `uow.nodes.insert(NewNode(ip=spec.host, port=spec.port,
   username=username, ncpus=(spec.ncpus if spec.ncpus is not None else 0),
   enabled=False)) -> Node(T)`, commit, close the UoW. The row is
   `enabled=False` so orchestrator's `list_enabled()` skips it.
2. Connect via `repository.connect(node=T, username=username,
   client_keys=..., engines_dir=..., port=spec.port)`, registering the
   session under `T.node_id`.
3. If not `skip_setup`: call `operations.setup_node(session, config.engines)`.
4. Open a second UoW, call `uow.nodes.update(Node(node_id=T.node_id,
   ip=spec.host, port=spec.port, username=username, ncpus=…,
   enabled=True, …))`, commit, close the UoW. This flips the row to
   `enabled=TRUE`.
5. Print `Added host to yascheduler: {spec.host}:{spec.port}`.
6. In a `finally` block: `await repository.disconnect(T.node_id)`.

The `disconnect` SHALL run on both the success path and any failure path
(SSH failure, setup failure, DB failure), so the SSH connection is released
rather than leaking until timeout.

The repository and operations SHALL be instantiated once per invocation;
the helper SHALL NOT construct its own repository/operations. This makes
the add helper unit-testable via direct mock injection.

On connect-failure (step 2 raises `MachineConnectionError` or any
`Exception`): the `_add_node` helper SHALL best-effort remove the tmp row
via a UoW (`uow.nodes.remove(T.node_id)` + commit, logged not raised),
then re-raise. The orchestrator never saw the row (it was
`enabled=FALSE`), so no orchestrator-side cleanup is needed. The
operator-visible behavior is unchanged: success → "Added host", failure →
error + no row remains.

#### Scenario: yasetnode constructs repository+operations once and passes to add helper

- **WHEN** `yasetnode 10.0.0.1` is invoked on the add path
- **THEN** exactly one `SSHMachineRepository()` and one `SSHMachineOperations(...)` are constructed (at the top of `manage_node`), and those instances are passed as parameters to the add helper

#### Scenario: yasetnode add-path inserts enabled=False before connect

- **WHEN** `_add_node` is called with a valid host spec
- **THEN** it inserts `NewNode(ip=spec.host, enabled=False, …) -> Node(T)` FIRST (before any SSH work), so `T.node_id` is in hand for `connect(node=T, ...)`

#### Scenario: yasetnode add-path connects via Node and disconnects by node_id

- **WHEN** `_add_node` reaches the connect step
- **THEN** it calls `repository.connect(node=T, username=..., ...)` (registering the session under `T.node_id`); the `finally` block calls `repository.disconnect(T.node_id)`

#### Scenario: yasetnode add-path flips enabled to TRUE after setup

- **WHEN** `_add_node` completes the optional `setup_node` step
- **THEN** it opens a second UoW, calls `uow.nodes.update(Node(node_id=T.node_id, enabled=True, …))`, commits, and prints `Added host to yascheduler: {spec.host}:{spec.port}`

#### Scenario: yasetnode add-path rolls back tmp row on connect failure

- **WHEN** `repository.connect(node=T, ...)` raises `MachineConnectionError` (or any `Exception`) during `_add_node`
- **THEN** the helper best-effort removes the tmp row via `uow.nodes.remove(T.node_id)` + commit (logged not raised), then re-raises; no `enabled=TRUE` row remains; the orchestrator never saw the row (it was `enabled=FALSE`)

#### Scenario: yasetnode add-path row is invisible to orchestrator during setup

- **WHEN** `_add_node` has inserted the row (enabled=False) and is mid-connect or mid-setup
- **THEN** the orchestrator's `_connect_machine_producer` filters by `list_enabled()`, which excludes the row; no concurrent connect attempt occurs

#### Scenario: yasetnode disconnects repository on add success

- **WHEN** `yasetnode 10.0.0.1` succeeds on the add path
- **THEN** `repository.disconnect(T.node_id)` is called after the `update` commit (inside `_add_node`'s `try/finally`, disconnect runs)

#### Scenario: yasetnode disconnects repository when setup_node raises

- **WHEN** `operations.setup_node(session, ...)` raises an exception after `repository.connect(node=T, ...)` succeeded
- **THEN** `repository.disconnect(T.node_id)` is still called (the `finally` block runs), the tmp row is best-effort removed, and the exception propagates to the top-level handler which prints `Error: ...` to stderr and exits `1`