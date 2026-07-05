## MODIFIED Requirements

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
2. Connect via `repository.connect(node=T, client_keys=...,
   engines_dir=...)`, registering the session under `T.node_id`. The login
   user and port come from `T.username` / `T.port` (which equal `username`
   and `spec.port`); `connect` takes no `username`/`port` arguments.
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
- **THEN** it calls `repository.connect(node=T, client_keys=..., ...)` with no `username`/`port` arguments (the login user and port are `T.username` / `T.port`), registering the session under `T.node_id`; the `finally` block calls `repository.disconnect(T.node_id)`

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

### Requirement: yastatus view mode connects via SSH with correct node params

When `-v` (or `-v -o`) is given, `yastatus` SHALL, for each RUNNING task with
an allocated IP, connect to the remote machine via `SSHMachineRepository`
(resolving a `MachineSession` via `repository.get_session` / a fresh
`repository.connect`), display a tail of the remote `OUTPUT` file, optionally
download and parse a CRYSTAL convergence snippet (when `-o` is also given),
and disconnect. The connection SHALL pass the resolved `node` to
`repository.connect(node=node, ...)`; the login user and port come from
`node.username` / `node.port` (NOT from separate `username`/`port` arguments —
`connect` reads them from the node). A private
`_resolve_conn_params(node, config)` helper resolves the jump-host parameters
(mirroring `orchestrator._connect_machine_consumer`):

- The login user is `node.username` (NOT a cloud username — the previous
  implementation's `for c in config.clouds: ssh_user = c.username` took the
  last cloud's username, which was a bug).
- The port is `node.port` (the previous implementation always used the
  gateway default of 22).
- `jump_host` and `jump_username` SHALL come from the cloud whose `prefix
  == node.cloud` (if any such cloud has both set), falling back to
  `config.remote.jump_host` / `config.remote.jump_username` for static nodes
  or clouds without a jump host. The previous implementation never passed
  jump-host parameters, so `yastatus -v` on a cloud node behind a jump host
  was functionally broken.

The `jump_host` and `jump_username` parameters SHALL be passed to
`repository.connect(...)`. The convergence snippet SHALL be stored in a
`tempfile`-based file (NOT the previous fixed-name `local_calc_snippet.tmp`)
and cleaned up in a `try/finally` block so it is removed even when
`_render_view` raises.

#### Scenario: yastatus -v uses node.username not cloud username
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `username="yascheduler"` and `cloud="hetzner"`, and the `hetzner` cloud config has `username="hcloud-user"`
- **THEN** `repository.connect(node=node, ...)` is called with a `node` whose `username == "yascheduler"` (the node's username, NOT the cloud's), and no separate `username` argument is passed

#### Scenario: yastatus -v uses node.port
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `port=2222`
- **THEN** `repository.connect(node=node, ...)` is called with a `node` whose `port == 2222` (NOT the repository default of 22), and no separate `port` argument is passed

#### Scenario: yastatus -v resolves jump host from matching cloud
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `cloud="hetzner"`, and the `hetzner` cloud config has `jump_host="jump.example.com"` and `jump_username="jumper"`
- **THEN** `repository.connect(...)` is called with `jump_host="jump.example.com"` and `jump_username="jumper"`

#### Scenario: yastatus -v falls back to config.remote for static nodes
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a static node (`cloud=None`), and `config.remote.jump_host` is set
- **THEN** `repository.connect(...)` is called with `jump_host=config.remote.jump_host` and `jump_username=config.remote.jump_username`

#### Scenario: yastatus -v -o uses a tempfile for the convergence snippet
- **WHEN** `yastatus -v -o` is invoked
- **THEN** the convergence snippet is written to a `tempfile.NamedTemporaryFile`/`mkstemp`-created file with a unique name (NOT the fixed `local_calc_snippet.tmp`), so concurrent invocations do not collide

#### Scenario: yastatus cleans up the snippet on exception
- **WHEN** `yastatus -v -o` is invoked and `_render_view` raises an exception during SSH or parse
- **THEN** the convergence snippet file is removed by the `try/finally` block (the previous implementation skipped cleanup on the exception path)
