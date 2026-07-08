## MODIFIED Requirements

### Requirement: yasetnode gateway lifecycle and resource safety

On the add path, `manage_node()` SHALL construct a single
`SSHMachineRepository` at the top and pass it to the add helper. The add
helper SHALL: (1) insert row with `enabled=False` before connecting, (2)
connect via `repository.connect(node=T, ...)`, (3) optionally call
`session.setup_node(engines)` on the session returned by `connect`, (4)
open second UoW to update `enabled=True`, (5) print success, (6)
`finally: repository.disconnect(T.node_id)`. On connect failure,
best-effort remove the tmp row and re-raise.

The legacy `SSHMachineOperations` instance is no longer constructed on
the `yasetnode` add path — the `setup_node` call is invoked directly on
the session.

#### Scenario: yasetnode constructs repository once and passes to add helper

- **WHEN** `yasetnode [IP]` is invoked on the add path
- **THEN** exactly one `SSHMachineRepository()` is constructed (at the top of `manage_node`), and that instance is passed as a parameter to the add helper; no `SSHMachineOperations` is constructed

#### Scenario: yasetnode add-path inserts enabled=False before connect, flips to TRUE after setup

- **WHEN** `_add_node` is called with a valid host spec
- **THEN** it inserts `NewNode(ip=spec.host, enabled=False, …) -> Node(T)` FIRST (before any SSH work), connects via `repository.connect(node=T, ...)`, optionally calls `session.setup_node(config.engines)` on the returned session, then opens a second UoW to update `enabled=True` and commit; the `finally` block calls `repository.disconnect(T.node_id)`

#### Scenario: yasetnode add-path rolls back tmp row on connect failure

- **WHEN** `repository.connect(node=T, ...)` raises `MachineConnectionError` (or any `Exception`) during `_add_node`
- **THEN** the helper best-effort removes the tmp row via `uow.nodes.remove(T.node_id)` + commit (logged not raised), then re-raises; no `enabled=TRUE` row remains; the orchestrator never saw the row (it was `enabled=FALSE`)

### Requirement: yasetnode dispatches add and remove paths

After argparse succeeds, `manage_node()` SHALL open a short read-only validation UoW, resolve the target `Node`, and close it. It SHALL then dispatch to exactly one helper, each opening its OWN UoW:

- If `already_there` and no remove flag: raise `ValueError` → exit 1.
- If NOT `already_there` and a remove flag: raise `ValueError` → exit 1.
- If `--remove-hard`: call `_remove_node_hard(deps, node)` — list RUNNING task ids, mark DONE, remove node, commit.
- If `--remove-soft`: call `_remove_node_soft(deps, node)` — disable if RUNNING tasks exist, else remove; commit.
- Otherwise (add): resolve username, call `_add_node(deps, repository, spec, config, skip_setup)`.

The remove helpers SHALL accept `node: Node` (not `ip: str`).

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW

- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(args.config)` is called, `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineRepository` is constructed at the top of `manage_node` (before any UoW is opened; no `SSHMachineOperations` is constructed), a short read-only UoW is opened to resolve the target `Node`, and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the repository is passed to the add helper.
