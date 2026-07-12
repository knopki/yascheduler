## MODIFIED Requirements

### Requirement: SSHMachineRepository implements MachineRepository

The system SHALL provide an `SSHMachineRepository` class that satisfies
the `MachineRepository` Protocol. The repository SHALL own a single dict
of sessions keyed by `NodeId`.

`connect(node: Node, ...)` SHALL use a two-method pattern: inner method
decorated with `@my_backoff_exc()` retries on `SSHRetryExc`; outer
`connect` translates exhausted `(asyncssh.misc.Error, OSError)` to
`MachineConnectionError`. `connect` SHALL open the SSH connection, detect
platform via the platform package, initialize paths via the platform
package, read `ncpus` via `adapter.get_cpu_cores(...)`, log the discovered
CPU count at the discovery site, construct a `ConnectedMachine` (carrying
`node_id`, `platform` only — NOT `hostname` or `ncpus`), construct an
`SSHMachineSession`, store it keyed by `node.node_id`, and return it.

`connect` SHALL read `node.hostname` as the asyncssh host address,
`node.username` as the login user, and `node.port` as the port. On
connection failure, `MachineConnectionError(node.node_id, node.hostname,
str(err))` SHALL be raised (carrying both identity and address — the
`MachineConnectionError` shape is unchanged by this change).

`disconnect(node_id)` SHALL pop the session for `node_id` (early return if
absent), then `await session._close()`. The pop-before-await ordering
SHALL be preserved. `disconnect_all()` SHALL iterate a snapshot of keys
and call `disconnect(node_id)` per session; it SHALL be idempotent.

`disconnect(node_id)` SHALL be scoped to the targeted node — it SHALL
cancel only the monitor registered for `node_id` and SHALL NOT cancel
monitors for any other machine.

#### Scenario: Repository owns only the sessions dict keyed by NodeId

- **WHEN** `SSHMachineRepository.__init__` is inspected
- **THEN** the instance has a dict of sessions keyed by `NodeId` and does NOT have `_machines` or `_monitors`

#### Scenario: connect logs CPU count at discovery site, not in setup_node

- **WHEN** `await repository.connect(node, client_keys, ...)` succeeds and `adapter.get_cpu_cores(...)` returns `8`
- **THEN** an info log line with the CPU count is emitted from the repository's connect path (in or immediately after the `START_BLOCK_CREATE_MACHINE` block), and `SSHMachineSession.setup_node` SHALL NOT emit a separate CPU-count log

### Requirement: SSHMachineSession implements MachineSession

The system SHALL provide an `SSHMachineSession` class that satisfies the
`MachineSession` Protocol. The session SHALL be constructed by
`SSHMachineRepository.connect` with: `hostname`, an open `SSHClientConnection`,
`SSHClientConnectionOptions`, a `ConnectedMachine` (initial snapshot with
`state=FREE`, `free_since=time.monotonic()` — the snapshot carries `node_id`
and `platform` only, NOT `hostname` or `ncpus`), `adapter`, `platforms`,
`data_dir`, `engines_dir`, `tasks_dir`.

The session SHALL own its own teardown via a `_close()` coroutine,
invoked only by `SSHMachineRepository.disconnect`. `_close()` SHALL be
idempotent: if `is_closed` is already `True`, it returns immediately.
Otherwise it SHALL:
1. Set the closed flag synchronously (BEFORE any await).
2. Pop and cancel the monitor task (if any).
3. Await the cancelled monitor's task (suppressing `asyncio.CancelledError`).
4. Close the SSH connection and await `wait_closed()`.

`SSHMachineSession`'s base primitives SHALL use the session's own `conn`
and `adapter` directly — NO hostname-keyed lookup, NO call into the repository.
`run_full` SHALL retry on `SSHRetryExc` via the `@my_backoff_exc()` decorator.
`setup_node` SHALL accept `engines: EngineRepository` and use the session's
own `adapter.setup_node(...)`. `setup_node` SHALL NOT log the CPU count —
the CPU-count log is owned by `SSHMachineRepository.connect` at the discovery
site.

#### Scenario: Session owns its monitor task

- **WHEN** `session.install_monitor(...)` is called
- **THEN** the resulting `asyncio.Task` is stored on the session and is NOT registered in any repository-level dict

#### Scenario: Session.hostname stays sourced from node.hostname

- **WHEN** `SSHMachineSession` is constructed by `SSHMachineRepository.connect`
- **THEN** `session.hostname == node.hostname` (the session's transport-echo field is sourced from the Node parameter, NOT from `ConnectedMachine.hostname` — `ConnectedMachine` no longer carries `hostname`)
