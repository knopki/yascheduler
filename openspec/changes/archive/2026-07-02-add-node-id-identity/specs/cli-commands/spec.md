## MODIFIED Requirements

### Requirement: yanodes default table output format

The default output of `yanodes` (when `--json` is not given) SHALL be a
fixed-width text table rendered with stdlib string formatting only (no
external dependencies such as `rich` or `tabulate`). The table SHALL have a
header row followed by one data row per node, in the order returned by
`uow.nodes.list_all()` (which is `ORDER BY node_id`). Column widths SHALL be
computed from the data (the maximum of the header width and the widest cell
width per column) so the table is self-aligning regardless of value lengths.

The columns SHALL be: `NODE_ID`, `IP`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`,
`TASK_ID`, `LABEL`. `NODE_ID` is the first column (identity first). Display-only
transformations SHALL apply to the table cells:

| column   | raw value       | table cell                       |
| -------- | --------------- | -------------------------------- |
| NODE_ID  | `node.node_id`    | `str(node.node_id)` (the bare int, via `NodeId.__str__`) |
| IP       | `node.ip`         | as-is                            |
| PORT     | `node.port`       | `-` when `22`, else the int      |
| NCPUS    | `node.ncpus`      | `MAX` when `0`, else the int     |
| ENABLED  | `node.enabled`    | `yes` when True, `no` when False |
| CLOUD    | `node.cloud`      | `-` when None, else the string   |
| TASK_ID  | `task.task_id`     | `-` when free, else the int      |
| LABEL    | `task.label`       | `-` when free, else the string   |

A node is "free" when no RUNNING task has `allocated_ip == node.ip`; it is
"busy" when exactly one RUNNING task does (the one-task-per-node invariant).

#### Scenario: yanodes table has a header row
- **WHEN** `yanodes` is invoked (with or without filter flags)
- **THEN** the first line of output is the header row `NODE_ID`, `IP`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`, `TASK_ID`, `LABEL` (column separators and exact spacing follow the fixed-width computation)

#### Scenario: yanodes table shows a busy node
- **WHEN** a node with `node_id=1`, `ip="10.0.0.1"`, `port=22`, `ncpus=4`, `enabled=True`, `cloud=None` has a RUNNING task with `task_id=7`, `label="my_job"`
- **THEN** one row is emitted with NODE_ID=`1`, PORT=`-`, NCPUS=`4`, ENABLED=`yes`, CLOUD=`-`, TASK_ID=`7`, LABEL=`my_job`

#### Scenario: yanodes table shows a free node
- **WHEN** a node with `node_id=2`, `ip="10.0.0.2"`, `port=2222`, `ncpus=0`, `enabled=False`, `cloud="hetzner"` has no RUNNING task
- **THEN** one row is emitted with NODE_ID=`2`, PORT=`2222`, NCPUS=`MAX`, ENABLED=`no`, CLOUD=`hetzner`, TASK_ID=`-`, LABEL=`-`

#### Scenario: yanodes table hides port 22
- **WHEN** a node has `port=22`
- **THEN** the PORT cell is `-` (the default SSH port is not shown)

#### Scenario: yanodes table shows non-default port
- **WHEN** a node has `port=2222`
- **THEN** the PORT cell is `2222`

#### Scenario: yanodes table shows MAX for zero ncpus
- **WHEN** a node has `ncpus=0`
- **THEN** the NCPUS cell is `MAX`

#### Scenario: yanodes table shows enabled as yes/no
- **WHEN** a node has `enabled=True` (resp. `False`)
- **THEN** the ENABLED cell is `yes` (resp. `no`)

#### Scenario: yanodes table shows dash for null cloud
- **WHEN** a node has `cloud=None`
- **THEN** the CLOUD cell is `-`

#### Scenario: yanodes table column widths fit the data
- **WHEN** the widest IP value is `10.0.0.255` (10 chars) and the header `IP` is 2 chars
- **THEN** the IP column is at least 10 chars wide and all IP cells are padded to that width

#### Scenario: yanodes table no external deps
- **WHEN** the implementation of `_render_nodes_table` is inspected
- **THEN** it uses only stdlib string formatting (f-string width specifiers, `str.ljust`, or equivalent) and does NOT import `rich`, `tabulate`, or any other third-party formatting library

### Requirement: yanodes --json output format

When `--json` is given, `yanodes` SHALL emit `json.dumps(list_of_objects)`
where each object represents one node with raw domain values (NO display
transformations — no `-`, no `MAX`, no `yes`/`no`). The object schema SHALL
be:

```
{"node_id": int, "ip": str, "port": int, "ncpus": int, "enabled": bool,
 "cloud": str | null, "occupied_by": {"task_id": int, "label": str} | null}
```

- `node_id`: the raw `node.node_id.value` int (serialized via `.value` because
  a `NodeId` dataclass is not JSON-serializable).
- `port`: the raw `node.port` int (22 stays 22, 2222 stays 2222).
- `ncpus`: the raw `node.ncpus` int (0 stays 0 — `MAX` is a table-only display
  token and MUST NOT appear in JSON).
- `cloud`: `null` for static nodes, else the `node.cloud` string.
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

#### Scenario: yanodes --json uses raw port
- **WHEN** a node has `port=22`
- **THEN** the JSON object's `port` field is `22` (NOT `null` or `"-"`)

#### Scenario: yanodes --json uses raw ncpus
- **WHEN** a node has `ncpus=0`
- **THEN** the JSON object's `ncpus` field is `0` (NOT `"MAX"` or `null`)

#### Scenario: yanodes --json busy node occupied_by is an object
- **WHEN** a node has a RUNNING task with `task_id=1`, `label="my_job"`
- **THEN** the JSON object's `occupied_by` field is `{"task_id": 1, "label": "my_job"}`

#### Scenario: yanodes --json free node occupied_by is null
- **WHEN** a node has no RUNNING task
- **THEN** the JSON object's `occupied_by` field is `null`

#### Scenario: yanodes --json static node cloud is null
- **WHEN** a node has `cloud=None`
- **THEN** the JSON object's `cloud` field is `null`

#### Scenario: yanodes --json empty result is empty list
- **WHEN** `yanodes --json` is invoked and no node matches the filters
- **THEN** the output is `[]` and the process exits `0`

### Requirement: yasetnode parses host grammar via argparse type

The `yasetnode` command SHALL accept a single positional `host` argument whose
argparse `type=` is `_parse_node_target(s) -> NodeTarget`. For input that is
NOT purely digits, `_parse_node_target` SHALL delegate to
`_parse_host_spec(s) -> HostSpec`, where `HostSpec` is a frozen dataclass with
fields `host: str`, `username: str | None`, `port: int`, `ncpus: int | None`.
The grammar for the host-delegation branch is `[user@]host[:port][~ncpus]`:

- `user` — non-empty string without `@`. When the `user@` prefix is absent,
  `HostSpec.username` is `None` (the default is resolved later from
  `config.remote.username` by `manage_node`, NOT hardcoded by the parser).
- `host` — either an IPv4 literal or a bracketed IPv6 literal `[...]`. The
  host string MUST be non-empty.
- `port` — integer in `1..65535`. When `:port` is absent, the parser
  applies the default `22`.
- `ncpus` — non-negative integer. `~0` and absent `~ncpus` both yield
  `HostSpec.ncpus = None` (the unlimited/MAX sentinel; downstream
  `Node(ncpus=0)` encodes this in the DB).

Malformed input (multiple `@`, multiple `~`, empty segments, unbracketed
IPv6, port out of range, negative ncpus, non-integer port/ncpus) SHALL
raise `argparse.ArgumentTypeError`, which argparse surfaces as a usage error
with exit `2`.

Purely-digit input (e.g. `"5"`) routes to the node_id branch described in
the "yasetnode positional discriminates node_id from host" requirement; it
does NOT pass through `_parse_host_spec`. The `_parse_host_spec` grammar
rules and ALL error/rejection behavior tested below are UNCHANGED from
before this change — only the positional `type=` was rewired to a wrapper
(`_parse_node_target`) that dispatches digit vs. non-digit input, so the
scenarios below call `_parse_node_target` (which delegates non-digit input
to the unchanged `_parse_host_spec`).

#### Scenario: yasetnode plain IPv4 host
- **WHEN** `_parse_node_target("10.0.0.1")` is called
- **THEN** it returns a `NodeTarget(node_id=None, host_spec=HostSpec(host="10.0.0.1", username=None, port=22, ncpus=None))`

#### Scenario: yasetnode user@host
- **WHEN** `_parse_node_target("deploy@10.0.0.1")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username="deploy", port=22, ncpus=None)`

#### Scenario: yasetnode host with explicit port
- **WHEN** `_parse_node_target("10.0.0.1:2222")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username=None, port=2222, ncpus=None)`

#### Scenario: yasetnode host with ncpus
- **WHEN** `_parse_node_target("10.0.0.1~4")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username=None, port=22, ncpus=4)`

#### Scenario: yasetnode full spec user@host:port~ncpus
- **WHEN** `_parse_node_target("deploy@10.0.0.1:2222~4")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username="deploy", port=2222, ncpus=4)`

#### Scenario: yasetnode bracketed IPv6
- **WHEN** `_parse_node_target("[::1]")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="::1", username=None, port=22, ncpus=None)`

#### Scenario: yasetnode bracketed IPv6 with port
- **WHEN** `_parse_node_target("[fe80::1]:2222")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="fe80::1", username=None, port=2222, ncpus=None)`

#### Scenario: yasetnode tilde-zero maps to None ncpus
- **WHEN** `_parse_node_target("10.0.0.1~0")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username=None, port=22, ncpus=None)` (the `0` is normalized to `None`, the unlimited sentinel)

#### Scenario: yasetnode unbracketed IPv6 is rejected
- **WHEN** `_parse_node_target("::1")` is called
- **THEN** `_parse_host_spec` (to which `_parse_node_target` delegates the non-digit input) raises `argparse.ArgumentTypeError` (IPv6 must be bracketed to disambiguate from `:port`)

#### Scenario: yasetnode multiple at-signs rejected
- **WHEN** `_parse_node_target("a@b@c")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode multiple tildes rejected
- **WHEN** `_parse_node_target("10.0.0.1~4~5")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode empty port rejected
- **WHEN** `_parse_node_target("10.0.0.1:")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode port out of range rejected
- **WHEN** `_parse_node_target("10.0.0.1:99999")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError` (port must be `1..65535`)

#### Scenario: yasetnode port zero rejected
- **WHEN** `_parse_node_target("10.0.0.1:0")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError` (port `0` is not a valid SSH port)

#### Scenario: yasetnode negative ncpus rejected
- **WHEN** `_parse_node_target("10.0.0.1~-5")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode non-integer port rejected
- **WHEN** `_parse_node_target("10.0.0.1:abc")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode hostname passes (no DNS validation)
- **WHEN** `_parse_node_target("compute-node-7")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="compute-node-7", username=None, port=22, ncpus=None)` (the parser validates structure, not reachability)

#### Scenario: yasetnode missing host positional exits 2
- **WHEN** `yasetnode` is invoked with no arguments
- **THEN** argparse prints a usage error to stderr (missing the required `host` argument) and exits `2`

#### Scenario: yasetnode malformed host exits 2
- **WHEN** `yasetnode ::1` is invoked (unbracketed IPv6)
- **THEN** the positional `type=_parse_node_target` raises `argparse.ArgumentTypeError` (via `_parse_host_spec` for the non-digit input), argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode prog is yasetnode in help and errors
- **WHEN** `yasetnode --help` or any argparse error is shown
- **THEN** the program name displayed is `yasetnode` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yasetnode parses flags via argparse

`manage_node()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yasetnode",
description="Add or remove nodes from the yascheduler daemon")` exposing:
- `host` (positional, `type=_parse_node_target`): the node target — EITHER a
  node_id (purely-digit string) OR a host spec in the
  `[user@]host[:port][~ncpus]` grammar (see the host grammar requirement).
  `_parse_node_target` returns a `NodeTarget` (see the "yasetnode positional
  discriminates node_id from host" requirement).
- `--skip-setup` (`store_true`): on the add path, skip the remote
  `gateway.setup_node` step. Valid ONLY on the add path.
- `--remove-soft` (`store_true`): disable the node if it has running tasks,
  or remove it immediately if not. Mutually exclusive with `--remove-hard`.
- `--remove-hard` (`store_true`): mark associated RUNNING tasks DONE and
  remove the node record. Mutually exclusive with `--remove-soft`.

`--remove-soft` and `--remove-hard` SHALL be in a
`mutually_exclusive_group`: passing both exits `2`. `--skip-setup` is
incompatible with either remove flag; a body-level check after `parse_args`
SHALL call `parser.error(...)` when
`skip_setup and (remove_soft or remove_hard)`, producing exit `2`. A
node_id positional is incompatible with the add path (no remove flag); a
body-level check after `parse_args` SHALL call `parser.error(...)` when
`node_target.node_id is not None and not (remove_soft or remove_hard)`,
producing exit `2` (see the "yasetnode positional discriminates node_id
from host" requirement). The flags SHALL use `action="store_true"` and
SHALL NOT accept a value (the previous `nargs="?", type=bool, const=True`
pattern was removed because `bool("false") is True`).

The parser SHALL accept an `argv: list[str] | None = None` parameter
forwarded to `parser.parse_args(argv)`. `None` reads `sys.argv` (the
console_script convention); tests pass an explicit list.

#### Scenario: yasetnode --help shows argparse usage
- **WHEN** `yasetnode --help` is invoked
- **THEN** argparse prints the standard help screen showing `prog="yasetnode"`, the `host` positional argument with its description, and the three flags, and exits `0`

#### Scenario: yasetnode with unknown flag exits 2
- **WHEN** `yasetnode 10.0.0.1 --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yasetnode --remove-soft --remove-hard exits 2
- **WHEN** `yasetnode 10.0.0.1 --remove-soft --remove-hard` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yasetnode --skip-setup --remove-hard exits 2
- **WHEN** `yasetnode 10.0.0.1 --skip-setup --remove-hard` is invoked
- **THEN** the body-level `parser.error(...)` fires, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode --skip-setup --remove-soft exits 2
- **WHEN** `yasetnode 10.0.0.1 --skip-setup --remove-soft` is invoked
- **THEN** the body-level `parser.error(...)` fires, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode --skip-setup does not accept a value
- **WHEN** `yasetnode 10.0.0.1 --skip-setup true` is invoked
- **THEN** argparse treats `true` as an unknown extra positional and exits `2` (the `store_true` flag takes no value)

#### Scenario: yasetnode node_id positional with add path exits 2
- **WHEN** `yasetnode 5` is invoked (a node_id positional with no `--remove-soft`/`--remove-hard`)
- **THEN** the body-level `parser.error(...)` fires (a node cannot be added by id), argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode argv parameter reads sys.argv when None
- **WHEN** `manage_node()` is invoked with `argv=None` (the console_script default)
- **THEN** `parser.parse_args(None)` is called, which reads `sys.argv[1:]`

#### Scenario: yasetnode argv parameter accepts explicit list
- **WHEN** `manage_node(["10.0.0.1", "--remove-hard"])` is invoked
- **THEN** `parser.parse_args(["10.0.0.1", "--remove-hard"])` is called, with no reading of `sys.argv`

### Requirement: yasetnode exit code contract

`manage_node()` SHALL follow the `0`/`1`/`2` exit-code contract:
- `0` on success: add completed; remove-hard completed; remove-soft
  completed (whether the node was disabled or removed).
- `1` on runtime failure: host already in DB (on the add path); host NOT in
  DB (on either remove path); node_id NOT in DB (on a remove-by-id path);
  SSH connection or setup failure; DB error; config parse error; or any
  unexpected exception caught at the top level. The error SHALL be printed
  to stderr as `Error: <error>` and the process SHALL exit `1`.
- `2` on argparse error (argparse default — missing host positional,
  malformed host grammar via `type=_parse_node_target` (which delegates to
  `_parse_host_spec` for non-digit input), port out of range, negative
  ncpus, `--remove-soft --remove-hard`, `--skip-setup --remove-*`,
  node_id-positional × add-path combination, unknown flag).

`manage_node()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body.

#### Scenario: yasetnode add exits 0 on success
- **WHEN** `yasetnode 10.0.0.1` is invoked and the add completes without exception
- **THEN** the success messages are printed to stdout and the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yasetnode add exits 1 when host already in DB
- **WHEN** `yasetnode 10.0.0.1` is invoked and `uow.nodes.get("10.0.0.1")` returns an existing node
- **THEN** `Error: ...` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasetnode remove exits 1 when host NOT in DB
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked and `uow.nodes.get("10.0.0.1")` returns `None`
- **THEN** `Error: ...` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasetnode remove-by-id exits 1 when node_id NOT in DB
- **WHEN** `yasetnode 999 --remove-hard` is invoked and `uow.nodes.get_by_id(NodeId(999))` returns `None`
- **THEN** `Error: ...` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasetnode exits 1 on SSH connect failure
- **WHEN** `yasetnode 10.0.0.1` is invoked and `gateway.connect(...)` raises an SSH connection error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode exits 1 on DB error
- **WHEN** `uow.nodes.insert(...)`, `uow.nodes.remove(...)`, `uow.nodes.disable(...)`, `uow.tasks.update_status(...)`, or `uow.tasks.list_ids_by_ip_and_status(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode exits 1 on config parse error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode --help exits 0
- **WHEN** `yasetnode --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yasetnode remove-hard exits 0 on success
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked against an existing node and the hard-remove completes without exception
- **THEN** the per-task and removal success messages are printed to stdout and the process exits `0`

#### Scenario: yasetnode remove-soft exits 0 on success
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against an existing node and the soft-remove completes without exception (whether the node had running tasks or not)
- **THEN** the success messages are printed to stdout and the process exits `0`

### Requirement: yasetnode output channels and verbatim success messages

On success, `manage_node()` SHALL print the following messages verbatim to
**stdout**, and SHALL emit them **after** `await uow.commit()` succeeds (so
the observable output matches the committed DB state):

| path                        | message (verbatim)                                                      |
| --------------------------- | ----------------------------------------------------------------------- |
| add, before setup           | `Setup host...`                                                          |
| add, after commit           | `Added host to yascheduler: {host}:{port}`                                |
| remove-hard, per task       | `An associated task {task_id} at {host} is now marked done!`              |
| remove-hard, after commit   | `Removed host from yascheduler: {host}`                                   |
| remove-soft, has tasks      | `A task associated, prevent from assigning the new tasks`                 |
|                              | `Prevented from assigning the new tasks: {host}`                          |
| remove-soft, no tasks       | `No tasks associated, remove node immediately`                             |
| remove-soft, no tasks, after commit | `Removed host from yascheduler: {host}`                            |

`{host}` is the parsed `HostSpec.host` (the cleaned host string, not the
raw input) when the positional is a host spec. When the positional is a
node_id (see the "yasetnode positional discriminates node_id from host"
requirement), `{host}` is the resolved `node.ip` from `get_by_id` (no
`HostSpec` is parsed on that path). `{port}` is the resolved `port` int
(host-spec path only; the node_id path has no port placeholder in the
messages — the remove messages use `{host}` alone). `{task_id}` is each
RUNNING task id marked DONE by the hard-remove.

On failure, `manage_node()` SHALL print `Error: <message>` to **stderr**
via `raise` + top-level `except Exception as e: print(f"Error: {e}",
file=sys.stderr); sys.exit(1)`. Failure messages SHALL NOT appear on
stdout.

#### Scenario: yasetnode add success prints verbatim messages to stdout after commit
- **WHEN** `yasetnode 10.0.0.1` succeeds (without `--skip-setup`)
- **THEN** stdout contains `Setup host...` (a progress indicator printed before `setup_node`, not a success confirmation) and `Added host to yascheduler: 10.0.0.1:22` (the confirmation, emitted after `uow.commit()` returns), in that order

#### Scenario: yasetnode add with --skip-setup omits Setup host message
- **WHEN** `yasetnode 10.0.0.1 --skip-setup` succeeds
- **THEN** stdout does NOT contain `Setup host...` (the setup step was skipped) and contains `Added host to yascheduler: 10.0.0.1:22`

#### Scenario: yasetnode remove-hard prints per-task messages after commit
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` succeeds against a node with RUNNING task ids `[1, 2]`
- **THEN** stdout contains `An associated task 1 at 10.0.0.1 is now marked done!` and `An associated task 2 at 10.0.0.1 is now marked done!` and `Removed host from yascheduler: 10.0.0.1`, all emitted after `uow.commit()` returns

#### Scenario: yasetnode remove-soft with tasks prints disable messages
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` succeeds against a node with at least one RUNNING task
- **THEN** stdout contains `A task associated, prevent from assigning the new tasks` and `Prevented from assigning the new tasks: 10.0.0.1`

#### Scenario: yasetnode remove-soft without tasks prints remove messages
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` succeeds against a node with no RUNNING tasks
- **THEN** stdout contains `No tasks associated, remove node immediately` and `Removed host from yascheduler: 10.0.0.1`

#### Scenario: yasetnode remove-by-id success messages use resolved node.ip
- **WHEN** `yasetnode 5 --remove-hard` succeeds against a node with `node_id=5`, `ip="10.0.0.5"`
- **THEN** stdout's success messages substitute `{host}` with `10.0.0.5` (the resolved `node.ip`), since no `HostSpec` is parsed on the node_id path

#### Scenario: yasetnode failure prints Error to stderr not stdout
- **WHEN** `yasetnode 10.0.0.1` fails (host already in DB, SSH failure, DB error, or any exception)
- **THEN** stderr contains `Error: ...`, stdout is empty of success messages, and the process exits `1`

## ADDED Requirements

### Requirement: yasetnode positional discriminates node_id from host

The `yasetnode` positional argument SHALL accept EITHER a node_id (a purely
digit string) OR a host spec (the `[user@]host[:port][~ncpus]` grammar). The
positional `type=_parse_node_target(s) -> NodeTarget` discriminates:

- if `s.isdigit()` is True, the result is
  `NodeTarget(node_id=NodeId(int(s)), host_spec=None)`;
- otherwise the result is
  `NodeTarget(node_id=None, host_spec=_parse_host_spec(s))`.

`NodeTarget` is a frozen dataclass with `node_id: NodeId | None` and
`host_spec: HostSpec | None`; exactly one of the two is set. The
discriminator `s.isdigit()` is safe because IPv4 literals contain `.`, IPv6
must be bracketed (`[...]`), and FQDNs contain `.`/letters — none are
pure-digit.

A node cannot be added by id (adding requires a real host). After
`parse_args`, if `node_target.node_id is not None` AND neither `--remove-soft`
nor `--remove-hard` is set (i.e. the add path), `manage_node` SHALL call
`parser.error("a node cannot be added by id; provide a host like user@host[:port][~ncpus]")`
(exit `2` — an argument-combination error, consistent with the existing
`--skip-setup × remove` `parser.error`).

On the remove-by-id path, the validation UoW resolves the node via
`uow.nodes.get_by_id(node_target.node_id) -> Node | None`. If `None`, the
existing "NOT in DB" body validation raises (exit `1`). If found, the
remove helpers (`_remove_node_soft`, `_remove_node_hard`) use `node.ip` for
`tasks.list_ids_by_ip_and_status(node.ip, TaskStatus.RUNNING)` and for the
ip-keyed `nodes.disable(node.ip)` / `nodes.remove(node.ip)` mutators — the
ip-keyed mutators are unchanged; `ip` is just now obtained from the
looked-up `Node` rather than the CLI positional.

#### Scenario: yasetnode pure-digit positional is a node_id
- **WHEN** `_parse_node_target("5")` is called
- **THEN** it returns `NodeTarget(node_id=NodeId(5), host_spec=None)`

#### Scenario: yasetnode node_id branch does not call _parse_host_spec
- **WHEN** `_parse_node_target("5")` is called
- **THEN** `_parse_host_spec` is NOT invoked (the digit short-circuit returns a `NodeTarget` with `node_id` set directly)

#### Scenario: yasetnode add-by-id is rejected
- **WHEN** `yasetnode 5` is invoked (no `--remove-soft`/`--remove-hard`)
- **THEN** argparse surfaces `parser.error(...)` with exit `2` and a message stating a node cannot be added by id

#### Scenario: yasetnode remove-by-id soft resolves via get_by_id
- **WHEN** `yasetnode 5 --remove-soft` is invoked and a node with node_id=5 exists with no RUNNING tasks
- **THEN** `uow.nodes.get_by_id(NodeId(5))` resolves the `Node`, and `uow.nodes.remove(node.ip)` removes it (ip-keyed mutator, unchanged)

#### Scenario: yasetnode remove-by-id unknown id is a body error
- **WHEN** `yasetnode 999 --remove-hard` is invoked and no node with node_id=999 exists
- **THEN** `get_by_id` returns `None` and the body raises a "not in DB" error with exit `1`

#### Scenario: yasetnode node_id zero is rejected
- **WHEN** `_parse_node_target("0")` is called
- **THEN** `NodeId(0)` raises `ValueError` in `__post_init__` (node_id must be > 0); the error surfaces as a runtime error (exit `1`) or is rejected at parse time

#### Scenario: yasetnode negative-looking token falls through to grammar
- **WHEN** `_parse_node_target("-5")` is called
- **THEN** `"-5".isdigit()` is `False`, so it falls through to `_parse_host_spec`, which rejects it as a malformed host (no dots/brackets)
