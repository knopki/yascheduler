## MODIFIED Requirements

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

On the remove path, the validation UoW resolves the `Node` early —
`uow.nodes.get_by_id(node_target.node_id) -> Node | None` on the node_id path,
`uow.nodes.get(spec.host) -> Node | None` on the host_spec path. If `None`, the
existing "NOT in DB" body validation raises (exit `1`). If found, the `Node`
is passed to the remove helpers (`_remove_node_soft`, `_remove_node_hard`),
which use `node.node_id` for the `nodes.disable(node.node_id)` /
`nodes.remove(node.node_id)` mutators and `node.ip` for
`tasks.list_ids_by_ip_and_status(node.ip, TaskStatus.RUNNING)` (Surface C —
ip-keyed, unchanged) and for user-facing stdout messages.

#### Scenario: yasetnode pure-digit positional is a node_id
- **WHEN** `_parse_node_target("5")` is called
- **THEN** it returns `NodeTarget(node_id=NodeId(5), host_spec=None)`

#### Scenario: yasetnode node_id branch does not call _parse_host_spec
- **WHEN** `_parse_node_target("5")` is called
- **THEN** `_parse_host_spec` is NOT invoked (the digit short-circuit returns a `NodeTarget` with `node_id` set directly)

#### Scenario: yasetnode add-by-id is rejected
- **WHEN** `yasetnode 5` is invoked (no `--remove-soft`/`--remove-hard`)
- **THEN** argparse surfaces `parser.error(...)` with exit `2` and a message stating a node cannot be added by id

#### Scenario: yasetnode remove-by-id soft resolves Node via get_by_id
- **WHEN** `yasetnode 5 --remove-soft` is invoked and a node with node_id=5 exists with no RUNNING tasks
- **THEN** `uow.nodes.get_by_id(NodeId(5))` resolves the `Node`, the `Node` is passed to `_remove_node_soft`, and `uow.nodes.remove(node.node_id)` removes it (node_id-keyed mutator)

#### Scenario: yasetnode remove-by-host soft resolves Node via get
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked and a node with ip=10.0.0.1 exists with no RUNNING tasks
- **THEN** `uow.nodes.get("10.0.0.1")` resolves the `Node`, the `Node` is passed to `_remove_node_soft`, and `uow.nodes.remove(node.node_id)` removes it (node_id-keyed mutator)

#### Scenario: yasetnode remove-by-id unknown id is a body error
- **WHEN** `yasetnode 999 --remove-hard` is invoked and no node with node_id=999 exists
- **THEN** `get_by_id` returns `None` and the body raises a "not in DB" error with exit `1`

#### Scenario: yasetnode node_id zero is rejected
- **WHEN** `_parse_node_target("0")` is called
- **THEN** `NodeId(0)` raises `ValueError` in `__post_init__` (node_id must be > 0); the error surfaces as a runtime error (exit `1`) or is rejected at parse time

#### Scenario: yasetnode negative-looking token falls through to grammar
- **WHEN** `_parse_node_target("-5")` is called
- **THEN** `"-5".isdigit()` is `False`, so it falls through to `_parse_host_spec`, which rejects it as a malformed host (no dots/brackets)

### Requirement: yasetnode dispatches add and remove paths

After argparse succeeds and the `HostSpec` is parsed, `manage_node()` SHALL
open a short, read-only validation UoW via
`async with deps.uow_factory() as uow:`, resolve the `Node` (via
`get(spec.host)` on the host_spec path, via `get_by_id(target.node_id)` on the
node_id path), and close it (without commit — nothing was mutated). It SHALL
then dispatch to exactly one helper, each of which opens its OWN UoW via
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
  config.remote.username`, call `_add_node(deps, gateway, spec, config,
  skip_setup)` — inside its own UoW, connect + optional setup +
  `uow.nodes.add(...)`, commit.

The remove helpers SHALL accept `node: Node` (not `ip: str`); the validation
UoW already fetched the `Node`, and passing it down avoids a re-fetch.
`tasks.list_ids_by_ip_and_status(node.ip, RUNNING)` stays ip-keyed (Surface C
— `TaskRepository` lookup, unchanged in this change). User-facing stdout
messages use `node.ip` (operators read ip, not node_id).

A TOCTOU window exists between closing the validation UoW and opening the
dispatch helper's UoW; for a single-operator CLI this is accepted (see design
D18). Failure modes are benign and non-corrupting: add-on-already-present →
unique-constraint / helper re-check → exit 1; remove-on-just-removed →
no-op / not-found → exit 1.

The `Node` record constructed on the add path SHALL use
`ip=spec.host`, `port=spec.port`, `username=<resolved>`,
`ncpus=(spec.ncpus if spec.ncpus is not None else 0)`, `enabled=True`.

#### Scenario: yasetnode add constructs Node with resolved username and default ncpus
- **WHEN** `yasetnode 10.0.0.1` is invoked and `config.remote.username` is `"root"`
- **THEN** `uow.nodes.add(...)` is called (inside `_add_node`'s own UoW) with a `Node(ip="10.0.0.1", port=22, username="root", ncpus=0, enabled=True)`

#### Scenario: yasetnode add respects explicit user@ override
- **WHEN** `yasetnode deploy@10.0.0.1` is invoked and `config.remote.username` is `"root"`
- **THEN** `uow.nodes.add(...)` is called (inside `_add_node`'s own UoW) with a `Node(ip="10.0.0.1", port=22, username="deploy", ncpus=0, enabled=True)` (the `user@` prefix overrides the config default)

#### Scenario: yasetnode add with explicit ncpus
- **WHEN** `yasetnode 10.0.0.1~4` is invoked
- **THEN** `uow.nodes.add(...)` is called (inside `_add_node`'s own UoW) with a `Node(ip="10.0.0.1", port=22, username=<resolved>, ncpus=4, enabled=True)`

#### Scenario: yasetnode remove-hard marks running tasks DONE then removes node by node_id
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked against a node with `node_id=7`, ip=10.0.0.1, and RUNNING task ids `[1, 2]`
- **THEN** inside `_remove_node_hard`'s own UoW, `uow.tasks.update_status(1, TaskStatus.DONE)` and `uow.tasks.update_status(2, TaskStatus.DONE)` are called, then `uow.nodes.remove(NodeId(7))` is called (node_id-keyed), then `uow.commit()` is called

#### Scenario: yasetnode remove-soft with tasks disables node by node_id
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against a node with `node_id=7`, ip=10.0.0.1, and at least one RUNNING task
- **THEN** inside `_remove_node_soft`'s own UoW, `uow.nodes.disable(NodeId(7))` is called (node_id-keyed), `uow.nodes.remove(...)` is NOT called, and `uow.commit()` is called

#### Scenario: yasetnode remove-soft without tasks removes node by node_id
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against a node with `node_id=7`, ip=10.0.0.1, and no RUNNING tasks
- **THEN** inside `_remove_node_soft`'s own UoW, `uow.nodes.remove(NodeId(7))` is called (node_id-keyed), `uow.nodes.disable(...)` is NOT called, and `uow.commit()` is called

#### Scenario: yasetnode remove helpers take Node not ip
- **WHEN** `_remove_node_hard` or `_remove_node_soft` is inspected
- **THEN** the signature is `(deps, node: Node)` (not `(deps, ip: str)`); the validation UoW resolved the `Node` and passed it down

#### Scenario: yasetnode logging captures warnings
- **WHEN** `manage_node()` is invoked
- **THEN** `logging.captureWarnings(True)` is called and the root logger level is set to `WARN` (so config warnings from `warn_unknown_fields` reach the operator)

#### Scenario: yasetnode helpers return None
- **WHEN** any of `_add_node`, `_remove_node_hard`, `_remove_node_soft` is called
- **THEN** it returns `None` (the function signals outcomes via side effects, exceptions, and exit codes, not via return values; the previous `bool` return signaling is removed)

### Requirement: yasetnode module path and GRACE-lite markup

The `yasetnode` command SHALL be implemented as `manage_node()` in
`yascheduler/entrypoints/cli/manage_node.py`, a synchronous entry point
that calls `asyncio.run(_manage_node_async(argv))` (NOT `@to_sync`-decorated;
CLI entry points have no async caller). The module SHALL carry fresh
GRACE-lite markup (`MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`,
function contracts, and block anchors) versioned `1.0.0`. The stale
`# FIXME: split adapter and application layer` comment from the old
`infra/cli/manage_node.py` SHALL NOT be carried to the new file. The logic
SHALL be split into private pure functions: `_parse_host_spec(s)`,
`_parse_node_args(argv)`, `_remove_node_hard(deps, node: Node)`,
`_remove_node_soft(deps, node: Node)`, `_add_node(deps, repository, operations,
spec, config, skip_setup)`, and the `HostSpec` frozen dataclass. Each
mutate helper opens its own UoW via `deps.uow_factory()` (see the dispatch
requirement); the validation read uses a separate read-only UoW closed
before dispatch. No use case SHALL be extracted into `application/` — YAGNI
(no second consumer; the daemon-side node lifecycle is owned by the
orchestrator).

#### Scenario: yasetnode entry point uses asyncio.run
- **WHEN** the `manage_node` callable in `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** it is a synchronous `def manage_node(argv: list[str] | None = None)` that calls `asyncio.run(_manage_node_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

#### Scenario: yasetnode module has fresh GRACE-lite markup
- **WHEN** `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** it contains `START_MODULE_CONTRACT`/`END_MODULE_CONTRACT`, `START_MODULE_MAP`/`END_MODULE_MAP`, `START_CHANGE_SUMMARY`/`END_CHANGE_SUMMARY`, function-level `START_CONTRACT:`/`END_CONTRACT:` blocks, and `START_BLOCK_`/`END_BLOCK_` anchors, versioned `1.0.0`

#### Scenario: yasetnode module drops stale FIXME
- **WHEN** `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** the comment `# FIXME: split adapter and application layer` does NOT appear (the framing was stale at the new home and the function-level split resolves the separation)

#### Scenario: yasetnode does not extract an application use case
- **WHEN** the implementation is inspected
- **THEN** no `application/manage_node.py` or equivalent use-case module is created; all orchestration lives in the CLI module's private helpers