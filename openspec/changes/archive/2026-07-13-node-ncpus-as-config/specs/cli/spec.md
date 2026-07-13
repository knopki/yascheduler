## MODIFIED Requirements

### Requirement: yanodes default table output format

The default output of `yanodes` (when `--json` is not given) SHALL be a
fixed-width text table rendered with stdlib string formatting only (no external
dependencies such as `rich` or `tabulate`). The table SHALL have a header row
followed by one data row per node, in the order returned by
`uow.nodes.list_all()` (which is `ORDER BY node_id`). Column widths SHALL be
computed from the data (the maximum of the header width and the widest cell
width per column) so the table is self-aligning regardless of value lengths.

The columns SHALL be: `NODE_ID`, `HOSTNAME`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`,
`TASK_ID`, `LABEL`. `NODE_ID` is the first column (identity first). Display-only
transformations SHALL apply to the table cells:

| column   | raw value       | table cell                       |
| -------- | --------------- | -------------------------------- |
| NODE_ID  | `node.node_id`    | `str(node.node_id)` (the bare int, via `NodeId.__str__`) |
| HOSTNAME | `node.hostname`   | as-is                            |
| PORT     | `node.port`       | `-` when `22`, else the int      |
| NCPUS    | `node.ncpus`      | `MAX` when `None` (or legacy `0`), else the int |
| ENABLED  | `node.enabled`    | `yes` when True, `no` when False |
| CLOUD    | `node.cloud`      | `-` when None, else the string   |
| TASK_ID  | `task.task_id`     | `-` when free, else the int      |
| LABEL    | `task.label`       | `-` when free, else the string   |

The NCPUS cell SHALL display `MAX` when `node.ncpus is None` (no operator limit
— discovered at spawn) OR when `node.ncpus == 0` (defensive against pre-migration
rows viewed before migration 013 runs). Post-migration only `None` occurs in a
fresh database; the `== 0` branch is backward-compatible only.

A node is "free" when no RUNNING task has `allocated_node_id == node.node_id`;
it is "busy" when exactly one RUNNING task does (the one-task-per-node
invariant).

#### Scenario: yanodes table has a header row
- **WHEN** `yanodes` is invoked (with or without filter flags)
- **THEN** the first line of output is the header row `NODE_ID`, `HOSTNAME`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`, `TASK_ID`, `LABEL` (column separators and exact spacing follow the fixed-width computation)

#### Scenario: yanodes table shows a busy node
- **WHEN** a node with `node_id=1`, `hostname="[IP]"`, `port=22`, `ncpus=4`, `enabled=True`, `cloud=None` has a RUNNING task with `task_id=7`, `label="my_job"`
- **THEN** one row is emitted with NODE_ID=`1`, HOSTNAME=`[IP]`, PORT=`-`, NCPUS=`4`, ENABLED=`yes`, CLOUD=`-`, TASK_ID=`7`, LABEL=`my_job`

#### Scenario: yanodes table shows MAX for None ncpus
- **WHEN** a node has `ncpus=None`
- **THEN** the NCPUS cell is `MAX`

#### Scenario: yanodes table shows MAX for legacy zero ncpus
- **WHEN** a node has `ncpus=0` (a pre-migration row viewed before migration 013 runs)
- **THEN** the NCPUS cell is `MAX` (backward-compatible with the legacy sentinel)

#### Scenario: yanodes table no external deps
- **WHEN** the implementation of the table renderer is inspected
- **THEN** it uses only stdlib string formatting (f-string width specifiers, `str.ljust`, or equivalent) and does NOT import `rich`, `tabulate`, or any other third-party formatting library

### Requirement: yanodes --json output format

When `--json` is given, `yanodes` SHALL emit `json.dumps(list_of_objects)` where
each object represents one node with raw domain values (NO display
transformations — no `-`, no `MAX`, no `yes`/`no`). The object schema SHALL be:

```
{"node_id": int, "hostname": str, "port": int, "ncpus": int | null, "enabled": bool,
 "cloud": str | null, "jump_host": str | null, "jump_port": int,
 "jump_username": str, "external_id": str | null, "status": str,
 "created_at": str, "updated_at": str,
 "occupied_by": {"task_id": int, "label": str} | null}
```

- `node_id`: the raw `node.node_id.value` int (serialized via `.value` because
  a `NodeId` dataclass is not JSON-serializable).
- `hostname`: the raw `node.hostname` string.
- `port`: the raw `node.port` int (22 stays 22, 2222 stays 2222).
- `ncpus`: the raw `node.ncpus` value — `null` when `None` (no operator limit),
  else the positive int (`MAX` is a table-only display token and MUST NOT appear
  in JSON).
- `cloud`: `null` for static nodes, else the `node.cloud` string.
- `jump_host`: `null` when `None`, else the `node.jump_host` string.
- `jump_port`: the raw `node.jump_port` int.
- `jump_username`: the raw `node.jump_username` string.
- `external_id`: `null` for static nodes, else the `node.external_id` string.
- `status`: the raw `node.status.name` string (e.g. `"OTHER"`).
- `created_at`: `node.created_at.isoformat()` (ISO-8601 string).
- `updated_at`: `node.updated_at.isoformat()` (ISO-8601 string).
- `occupied_by`: `null` when the node is free; a single object
  `{"task_id": int, "label": str}` when the node is busy (one RUNNING task).

#### Scenario: yanodes --json emits a list of objects
- **WHEN** `yanodes --json` is invoked against a non-empty node set
- **THEN** the output is a JSON array (parsed by `json.loads` yields a `list`)

#### Scenario: yanodes --json includes node_id
- **WHEN** a node with `node_id=NodeId(5)` is listed via `yanodes --json`
- **THEN** its object's `"node_id"` is the int `5` (not the string `"5"` and not the `NodeId` object)

#### Scenario: yanodes --json uses hostname key not ip
- **WHEN** a node with `hostname="10.0.0.1"` is listed via `yanodes --json`
- **THEN** its object has a `"hostname": "10.0.0.1"` key and NO `"ip"` key

#### Scenario: yanodes --json emits null ncpus for None
- **WHEN** a node with `ncpus=None` is listed via `yanodes --json`
- **THEN** its object's `"ncpus"` is JSON `null`

#### Scenario: yanodes --json emits positive int ncpus
- **WHEN** a node with `ncpus=8` is listed via `yanodes --json`
- **THEN** its object's `"ncpus"` is the int `8`

#### Scenario: yanodes --json includes new node fields
- **WHEN** a node with `jump_host=None`, `jump_port=22`, `jump_username="root"`, `external_id=None`, `status=NodeStatus.OTHER`, `created_at=<datetime>`, `updated_at=<datetime>` is listed via `yanodes --json`
- **THEN** its object includes `"jump_host": null`, `"jump_port": 22`, `"jump_username": "root"`, `"external_id": null`, `"status": "OTHER"`, `"created_at": <iso>`, `"updated_at": <iso>`

#### Scenario: yanodes --json empty result is empty list
- **WHEN** `yanodes --json` is invoked and no node matches the filters
- **THEN** the output is `[]`

### Requirement: yasetnode gateway lifecycle and resource safety

On the add path, `manage_node()` SHALL construct a single `SSHMachineRepository`
at the top and pass it to the add helper. The add helper SHALL: (1) construct a
`NewNode` with jump-leg fields resolved from `config.remote` (`jump_host`,
`jump_username`, `jump_port`) and `ncpus` taken directly from the parsed
`HostSpec.ncpus` (`int | None` — `None` when the `~ncpus` clause is absent or
`~0`, a positive int when `~N` is given; the value SHALL NOT be coerced to `0`),
(2) insert the row with `enabled=False` before connecting, (3) connect via
`repository.connect(node=T, client_keys=..., ...)`, (4) optionally call
`session.setup_node(engines)` on the session returned by `connect`, (5) open
second UoW to update `enabled=True`, (6) print success, (7)
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

#### Scenario: yasetnode add-path encodes absent ncpus as None

- **WHEN** the add helper is called with a host spec whose `~ncpus` clause is absent (so `HostSpec.ncpus is None`)
- **THEN** the `NewNode` passed to `insert` carries `ncpus=None` (the value is NOT coerced to `0`); the persisted tmp row stores SQL `NULL`

#### Scenario: yasetnode add-path encodes explicit ncpus

- **WHEN** the add helper is called with a host spec `host~8` (so `HostSpec.ncpus == 8`)
- **THEN** the `NewNode` passed to `insert` carries `ncpus=8`; the persisted tmp row stores `8`

#### Scenario: yasetnode add-path inserts enabled=False before connect, flips to TRUE after setup

- **WHEN** the add helper is called with a valid host spec
- **THEN** it inserts `NewNode(hostname=spec.host, enabled=False, ncpus=spec.ncpus, jump_host=config.remote.jump_host, jump_username=config.remote.jump_username, …) -> Node(T)` FIRST (before any SSH work), connects via `repository.connect(node=T, client_keys=..., ...)`, optionally calls `session.setup_node(config.engines)` on the returned session, then opens a second UoW to update `enabled=True` and commit; the `finally` block calls `repository.disconnect(T.node_id)`

#### Scenario: yasetnode add-path rolls back tmp row on connect failure

- **WHEN** `repository.connect(node=T, client_keys=...)` raises `MachineConnectionError` (or any `Exception`) during the add helper
- **THEN** the helper best-effort removes the tmp row via `uow.nodes.remove(T.node_id)` + commit (logged not raised), then re-raises; no `enabled=TRUE` row remains; the orchestrator never saw the row (it was `enabled=FALSE`)
