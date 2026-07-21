## MODIFIED Requirements

### Requirement: yastatus view mode connects via SSH with correct node params

When `-v` (or `-v -o`) is given, `yastatus` SHALL, for each RUNNING task with
an allocated node, connect to the remote machine via `SSHMachineRepository`
(resolving a `MachineSession` via `repository.get_session` / a fresh
`repository.connect`), display a tail of the remote `OUTPUT` file, optionally
download and parse a CRYSTAL convergence snippet (when `-o` is also given), and
disconnect. The connection SHALL pass the resolved `node` to
`repository.connect(node=node, client_keys=..., ...)`; the login user, port,
and jump-leg parameters come from `node.username` / `node.port` /
`node.jump_host` / `node.jump_port` / `node.jump_username` (NOT from separate
arguments — `connect` reads them from the node).

- The login user is `node.username`.
- The port is `node.port`.
- The jump leg is built from `node.jump_host` / `node.jump_port` / `node.jump_username`. There is no per-call resolution from `CloudConfig` or `config.remote` — `yastatus` trusts the values stamped on `Node` at creation.

`yastatus` SHALL NOT pass `jump_host` / `jump_username` parameters to
`repository.connect(...)`. The convergence snippet SHALL be stored in a
`tempfile`-based file and cleaned up in a `try/finally` block so it is removed
even when the view renderer raises.

#### Scenario: yastatus -v uses node.username not cloud username

- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `username="yascheduler"` and `cloud="hetzner"`, and the `hetzner` cloud config has `username="hcloud-user"`
- **THEN** `repository.connect(node=node, ...)` is called with a `node` whose `username == "yascheduler"` (the node's username, NOT the cloud's), and no separate `username` argument is passed

#### Scenario: yastatus -v reads jump from Node not from CloudConfig

- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `cloud="hetzner"` and `jump_host="jump.example.com"` (stamped at creation), and the `hetzner` cloud config still has `jump_host="jump.example.com"` (unchanged)
- **THEN** `repository.connect(node=node, client_keys=...)` is called with no `jump_host` / `jump_username` arguments, and the tunnel leg is built from `node.jump_host` / `node.jump_username`

#### Scenario: yastatus -v follows Node jump even when CloudConfig changed

- **WHEN** `yastatus -v` is invoked against a node with `jump_host="old-bastion.example.com"` (stamped at creation), and the `hetzner` cloud config has since been edited to `jump_host="new-bastion.example.com"`
- **THEN** the tunnel leg uses `node.jump_host == "old-bastion.example.com"` (Node is the source of truth, not the live config)

### Requirement: yasetnode gateway lifecycle and resource safety

On the add path, `manage_node()` SHALL construct a single `SSHMachineRepository`
at the top and pass it to the add helper. The add helper SHALL: (1) construct a
`NewNode` with jump-leg fields resolved from `config.remote` (`jump_host`,
`jump_username`, `jump_port`), (2) insert the row with `enabled=False` before
connecting, (3) connect via `repository.connect(node=T, client_keys=..., ...)`,
(4) optionally call `session.setup_node(engines)` on the session returned by
`connect`, (5) open second UoW to update `enabled=True`, (6) print success, (7)
`finally: repository.disconnect(T.node_id)`. On connect failure, best-effort
remove the tmp row and re-raise.

`repository.connect` SHALL NOT receive `jump_host` / `jump_username` arguments;
the tmp node already carries them.

#### Scenario: yasetnode constructs repository once and passes to add helper

- **WHEN** `yasetnode [IP]` is invoked on the add path
- **THEN** exactly one `SSHMachineRepository()` is constructed (at the top of `manage_node`), and that instance is passed as a parameter to the add helper

#### Scenario: yasetnode add-path stamps jump from config.remote before insert

- **WHEN** the add helper is called with a valid host spec and `config.remote.jump_host="bastion.example.com"` and `config.remote.jump_username="jumper"`
- **THEN** the `NewNode` passed to `insert` carries `jump_host="bastion.example.com"`, `jump_username="jumper"`, `jump_port=22` (the schema default); the subsequent `repository.connect(node=T, client_keys=...)` call passes no `jump_host` / `jump_username` arguments, and the tunnel leg is built from `T.jump_*`

#### Scenario: yasetnode add-path inserts enabled=False before connect, flips to TRUE after setup

- **WHEN** the add helper is called with a valid host spec
- **THEN** it inserts `NewNode(hostname=spec.host, enabled=False, jump_host=config.remote.jump_host, jump_username=config.remote.jump_username, …) -> Node(T)` FIRST (before any SSH work), connects via `repository.connect(node=T, client_keys=..., ...)`, optionally calls `session.setup_node(config.engines)` on the returned session, then opens a second UoW to update `enabled=True` and commit; the `finally` block calls `repository.disconnect(T.node_id)`

#### Scenario: yasetnode add-path rolls back tmp row on connect failure

- **WHEN** `repository.connect(node=T, client_keys=...)` raises `MachineConnectionError` (or any `Exception`) during the add helper
- **THEN** the helper best-effort removes the tmp row via `uow.nodes.remove(T.node_id)` + commit (logged not raised), then re-raises; no `enabled=TRUE` row remains; the orchestrator never saw the row (it was `enabled=FALSE`)
