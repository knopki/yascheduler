## MODIFIED Requirements

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

The `jump_host`, `jump_username`, and `jump_port` SHALL be read from
`config.remote.jump_host`, `config.remote.jump_username` (defaulting to `"root"`
when `None`), and `config.remote.jump_port` respectively — NOT hardcoded. The
`jump_port` SHALL reflect the parsed `[remote] jump_port` value (default `22`
when the key is absent).

`repository.connect` SHALL NOT receive `jump_host` / `jump_username` arguments;
the tmp node already carries them.

#### Scenario: yasetnode constructs repository once and passes to add helper

- **WHEN** `yasetnode [IP]` is invoked on the add path
- **THEN** exactly one `SSHMachineRepository()` is constructed (at the top of `manage_node`), and that instance is passed as a parameter to the add helper

#### Scenario: yasetnode add-path stamps jump from config.remote before insert

- **WHEN** the add helper is called with a valid host spec and `config.remote.jump_host="bastion.example.com"`, `config.remote.jump_username="jumper"`, `config.remote.jump_port=2222`
- **THEN** the `NewNode` passed to `insert` carries `jump_host="bastion.example.com"`, `jump_username="jumper"`, `jump_port=2222`; the subsequent `repository.connect(node=T, client_keys=...)` call passes no `jump_host` / `jump_username` arguments, and the tunnel leg is built from `T.jump_*`

#### Scenario: yasetnode add-path uses default jump_port when [remote] key absent

- **WHEN** the add helper is called with a valid host spec and the `[remote]` section does NOT set `jump_port`
- **THEN** the `NewNode` passed to `insert` carries `jump_port=22` (the `RemoteDefaults.jump_port` default)

#### Scenario: yasetnode add-path inserts enabled=False before connect, flips to TRUE after setup

- **WHEN** the add helper is called with a valid host spec
- **THEN** it inserts `NewNode(hostname=spec.host, enabled=False, jump_host=config.remote.jump_host, jump_username=config.remote.jump_username, jump_port=config.remote.jump_port, …) -> Node(T)` FIRST (before any SSH work), connects via `repository.connect(node=T, client_keys=..., ...)`, optionally calls `session.setup_node(config.engines)` on the returned session, then opens a second UoW to update `enabled=True` and commit; the `finally` block calls `repository.disconnect(T.node_id)`

#### Scenario: yasetnode add-path rolls back tmp row on connect failure

- **WHEN** `repository.connect(node=T, client_keys=...)` raises `MachineConnectionError` (or any `Exception`) during the add helper
- **THEN** the helper best-effort removes the tmp row via `uow.nodes.remove(T.node_id)` + commit (logged not raised), then re-raises; no `enabled=TRUE` row remains; the orchestrator never saw the row (it was `enabled=FALSE`)
