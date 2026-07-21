## MODIFIED Requirements

### Requirement: yanodes default table output format

The default output of `yanodes` (when `--json` is not given) SHALL be a
fixed-width text table rendered with stdlib string formatting only (no external
dependencies such as `rich` or `tabulate`). The table SHALL have a header row
followed by one data row per node, in the order returned by
`uow.nodes.list_all()` (which is `ORDER BY node_id`). Column widths SHALL be
computed from the data (the maximum of the header width and the widest cell
width per column) so the table is self-aligning regardless of value lengths.

The columns SHALL be: `NODE_ID`, `HOSTNAME`, `PORT`, `NCPUS`, `ENABLED`,
`CLOUD`, `TASK_ID`, `LABEL`. `NODE_ID` is the first column (identity first).
Display-only transformations SHALL apply to the table cells:

| column   | raw value       | table cell                       |
| -------- | --------------- | -------------------------------- |
| NODE_ID  | `node.node_id`    | `str(node.node_id)` (the bare int, via `NodeId.__str__`) |
| HOSTNAME | `node.hostname`  | as-is                            |
| PORT     | `node.port`       | `-` when `22`, else the int      |
| NCPUS    | `node.ncpus`      | `MAX` when `0`, else the int     |
| ENABLED  | `node.enabled`    | `yes` when True, `no` when False |
| CLOUD    | `node.cloud`      | `-` when None, else the string   |
| TASK_ID  | `task.task_id`     | `-` when free, else the int      |
| LABEL    | `task.label`       | `-` when free, else the string   |

A node is "free" when no RUNNING task has `allocated_node_id == node.node_id`;
it is "busy" when exactly one RUNNING task does (the one-task-per-node
invariant).

#### Scenario: yanodes table has a header row
- **WHEN** `yanodes` is invoked (with or without filter flags)
- **THEN** the first line of output is the header row `NODE_ID`, `HOSTNAME`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`, `TASK_ID`, `LABEL` (column separators and exact spacing follow the fixed-width computation)

#### Scenario: yanodes table shows a busy node
- **WHEN** a node with `node_id=1`, `hostname="[IP]"`, `port=22`, `ncpus=4`, `enabled=True`, `cloud=None` has a RUNNING task with `task_id=7`, `label="my_job"`
- **THEN** one row is emitted with NODE_ID=`1`, HOSTNAME=`[IP]`, PORT=`-`, NCPUS=`4`, ENABLED=`yes`, CLOUD=`-`, TASK_ID=`7`, LABEL=`my_job`

#### Scenario: yanodes table shows MAX for zero ncpus
- **WHEN** a node has `ncpus=0`
- **THEN** the NCPUS cell is `MAX`

#### Scenario: yanodes table no external deps
- **WHEN** the implementation of the table renderer is inspected
- **THEN** it uses only stdlib string formatting (f-string width specifiers, `str.ljust`, or equivalent) and does NOT import `rich`, `tabulate`, or any other third-party formatting library

### Requirement: yanodes --json output format

When `--json` is given, `yanodes` SHALL emit `json.dumps(list_of_objects)` where
each object represents one node with raw domain values (NO display
transformations — no `-`, no `MAX`, no `yes`/`no`). The object schema SHALL be:

```
{"node_id": int, "hostname": str, "port": int, "ncpus": int, "enabled": bool,
 "cloud": str | null, "jump_host": str | null, "jump_port": int,
 "jump_username": str, "external_id": str | null, "status": str,
 "created_at": str, "updated_at": str,
 "occupied_by": {"task_id": int, "label": str} | null}
```

- `node_id`: the raw `node.node_id.value` int (serialized via `.value` because
  a `NodeId` dataclass is not JSON-serializable).
- `hostname`: the raw `node.hostname` string.
- `port`: the raw `node.port` int (22 stays 22, 2222 stays 2222).
- `ncpus`: the raw `node.ncpus` int (0 stays 0 — `MAX` is a table-only display
  token and MUST NOT appear in JSON).
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
  The single-object shape encodes the one-RUNNING-task-per-node invariant;
  promotion to an array is a separate change if the invariant ever relaxes.

One object per node, in the order returned by `uow.nodes.list_all()`.

#### Scenario: yanodes --json emits a list of objects
- **WHEN** `yanodes --json` is invoked against a non-empty node set
- **THEN** the output is valid JSON parseable as a list of objects, one per node, in `list_all()` order

#### Scenario: yanodes --json includes node_id
- **WHEN** a node with `node_id=NodeId(5)` is listed
- **THEN** the JSON object's `node_id` field is `5` (the bare int via `.value`)

#### Scenario: yanodes --json uses hostname key not ip
- **WHEN** a node with `hostname="10.0.0.1"` is listed via `yanodes --json`
- **THEN** the JSON object has a `"hostname"` key with value `"10.0.0.1"` and does NOT have an `"ip"` key

#### Scenario: yanodes --json includes new node fields
- **WHEN** a node with `jump_host=None`, `jump_port=22`, `jump_username="root"`, `external_id=None`, `status=NodeStatus.OTHER`, `created_at=<datetime>`, `updated_at=<datetime>` is listed via `yanodes --json`
- **THEN** the JSON object includes `jump_host: null`, `jump_port: 22`, `jump_username: "root"`, `external_id: null`, `status: "OTHER"`, `created_at: <isoformat>`, `updated_at: <isoformat>`

#### Scenario: yanodes --json empty result is empty list
- **WHEN** `yanodes --json` is invoked and no node matches the filters
- **THEN** the output is `[]` and the process exits `0`

### Requirement: yastatus --json output format

When `--json` is given, `yastatus` SHALL emit `json.dumps(list_of_objects)` where
each object represents one task with raw domain values (NO display
transformations — no `MAX`, no `-`, no banner). The object schema SHALL be
exactly these fields:

```
{"task_id": int, "status": str, "label": str, "engine": str,
 "local_folder": str | null, "remote_folder": str | null,
 "created_at": str, "updated_at": str,
 "node": {"hostname": str, "port": int, "username": str,
          "cloud": str | null, "jump_host": str | null,
          "jump_port": int, "jump_username": str,
          "external_id": str | null, "status": str,
          "created_at": str, "updated_at": str} | null}
```

The `node` object is `null` when the task has no allocated node; otherwise it
carries the resolved `Node` fields with `hostname` (not `ip`), all connection
parameters (`port`, `username`, `jump_host`, `jump_port`, `jump_username`),
`cloud`, `external_id`, `status` (the `NodeStatus` name string), and audit
timestamps (`created_at`/`updated_at` as ISO-8601 strings).

One object per task, in the order returned by the query (`list_by_status` or
`list_by_jobs`). `--json` SHALL be in the `mutually_exclusive_group` with `-v`
and `-i`; convergence (`-o`) is NOT part of `--json` (mixing machine-readable
JSON with ephemeral scientific output is excluded by design).

#### Scenario: yastatus --json emits a list of objects
- **WHEN** `yastatus --json` is invoked against a non-empty task set
- **THEN** the output is valid JSON parseable as a list of objects, one per task, in query order

#### Scenario: yastatus --json empty result is empty list
- **WHEN** `yastatus --json` is invoked and the query returns no tasks
- **THEN** the output is `[]` and the process exits `0`

#### Scenario: yastatus --json composes with -j
- **WHEN** `yastatus -j 1 2 --json` is invoked
- **THEN** `list_by_jobs(job_ids=["1", "2"])` is called and the JSON renderer prints the result (the `-j` filter composes with `--json`)

#### Scenario: yastatus --json node object uses hostname key
- **WHEN** a task with an allocated node that has `hostname="10.0.0.1"` is rendered via `yastatus --json`
- **THEN** the `node` object has a `"hostname"` key with value `"10.0.0.1"` and does NOT have an `"ip"` key

### Requirement: yasetnode output channels and verbatim success messages

On success, `manage_node()` SHALL print the following messages verbatim to
stdout, emitted **after** `await uow.commit()` succeeds:

| path | message (verbatim) |
| --- | --- |
| add, before setup | `Setup host...` |
| add, after commit | `Added host to yascheduler: {host}:{port}` |
| remove-hard, per task | `An associated task {task_id} at {host} is now marked done!` |
| remove-hard, after commit | `Removed host from yascheduler: {host}` |
| remove-soft, has tasks | `A task associated, prevent from assigning the new tasks` / `Prevented from assigning the new tasks: {host}` |
| remove-soft, no tasks | `No tasks associated, remove node immediately` / `Removed host from yascheduler: {host}` |

`{host}` is the parsed `HostSpec.host` (host spec path) or resolved
`node.hostname` (node_id path). On failure, print `Error: <message>` to stderr
and exit 1.

#### Scenario: yasetnode add success prints verbatim messages to stdout after commit
- **WHEN** `yasetnode [IP]` succeeds (without `--skip-setup`)
- **THEN** stdout contains `Setup host...` and `Added host to yascheduler: [IP]:22`, in that order

#### Scenario: yasetnode remove-hard prints per-task messages after commit
- **WHEN** `yasetnode [IP] --remove-hard` succeeds against a node with RUNNING task ids `[1, 2]`
- **THEN** stdout contains `An associated task 1 at [IP] is now marked done!` and `An associated task 2 at [IP] is now marked done!` and `Removed host from yascheduler: [IP]`, all emitted after `uow.commit()` returns

### Requirement: yasetnode positional discriminates node_id from host

The positional `type=_parse_node_target(s) -> NodeTarget` SHALL discriminate:

- if `s.isdigit()` is True, the result is
  `NodeTarget(node_id=NodeId(int(s)), host_spec=None)`;
- otherwise the result is
  `NodeTarget(node_id=None, host_spec=_parse_host_spec(s))`.

`NodeTarget` is a frozen dataclass with `node_id: NodeId | None` and
`host_spec: HostSpec | None`; exactly one of the two is set. The discriminator
`s.isdigit()` is safe because IPv4 literals contain `.`, IPv6 must be bracketed
(`[...]`), and FQDNs contain `.`/letters — none are pure-digit.

A node cannot be added by id (adding requires a real host). After `parse_args`,
if `node_target.node_id is not None` AND neither `--remove-soft` nor
`--remove-hard` is set (i.e. the add path), `manage_node` SHALL call
`parser.error("a node cannot be added by id; provide a host like user@host[:port][~ncpus]")`
(exit `2` — an argument-combination error, consistent with the existing
`--skip-setup × remove` `parser.error`).

On the remove path, the validation UoW resolves the `Node` early —
`uow.nodes.get_by_id(node_target.node_id) -> Node | None` on the node_id path,
or `uow.nodes.list_all()` + filter by `hostname == target.host_spec.host` on
the host_spec path (the hostname-keyed `get(ip)` lookup is removed — `node_id`
is the sole identity; resolving a host_spec to a `Node` requires listing
because `hostname` is not a unique key). If `None`, the existing "NOT in DB"
body validation raises (exit `1`). If found, the `Node` is passed to the remove
helpers, which use `node.node_id` for the `nodes.disable(node.node_id)` /
`nodes.remove(node.node_id)` mutators and `node.hostname` for user-facing
stdout messages.

#### Scenario: yasetnode pure-digit positional is a node_id
- **WHEN** `_parse_node_target("5")` is called
- **THEN** it returns `NodeTarget(node_id=NodeId(5), host_spec=None)`

#### Scenario: yasetnode add-by-id is rejected
- **WHEN** `yasetnode 5` is invoked (no `--remove-soft`/`--remove-hard`)