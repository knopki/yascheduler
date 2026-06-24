## Why

`yanodes` lives at `yascheduler/infra/cli/show_nodes.py` but is an entrypoint
(a CLI command invoked by `console_script`), not an infra adapter. The archived
`add-entrypoints-layer` change listed `infra/cli/` as deferred-for-migration;
the archived `relocate-init-command` change then moved `init.py` into
`yascheduler/entrypoints/cli/init.py` as the first resident, establishing the
`entrypoints/cli/` home and the relocation pattern (real move, no compat shim,
layer direction `entrypoints → infra` preserved). `show_nodes` is the next
resident: the `entrypoints/cli/` home already exists, and `show_nodes` is an
execution query — the execution-command counterpart to `init`'s bootstrap-
command precedent.

The current `show_nodes()` also has real issues worth fixing in the same move:
no argparse (no flags, no `--help`), an O(n*m) inner scan that re-builds the
format string on every iteration, hidden last-writer-wins logic in the inner
task loop, no exit-code contract, and a `key=value` output format that nothing
parses but that is not machine-readable either. The move is the moment to bring
it to the modern standard `init` set (`argparse`, exit `0/1/2`, fresh GRACE-lite
markup) and add the filters and `--json` output that make `yanodes` useful both
for operators and for scripting.

## What Changes

- Move `yascheduler/infra/cli/show_nodes.py` →
  `yascheduler/entrypoints/cli/show_nodes.py` (real implementation, not a shim).
  This is the second resident of `entrypoints/cli/`, mirroring `init.py` from
  `relocate-init-command`. `show_nodes` is the execution-command precedent; the
  other 4 execution commands (`submit`, `check_status`, `manage_node`,
  `daemonize`) stay in `infra/cli/` for follow-up changes if pursued.
- Delete `yascheduler/infra/cli/show_nodes.py`. Drop `from .show_nodes import
  show_nodes` and `"show_nodes"` from `__all__` in
  `yascheduler/infra/cli/__init__.py`; drop the `show_nodes - Re-exported from
  .show_nodes` line from its `MODULE_MAP`. No compat shim: any
  `infra → entrypoints` re-export would invert the layer direction enforced by
  `import-linter` (same reasoning as `relocate-init-command` D1).
- Update `pyproject.toml` `[project.scripts]`:
  `yanodes = "yascheduler.entrypoints.cli.show_nodes:show_nodes"`.
- Reimplement `show_nodes()` with `argparse` exposing:
  - `--json` (`store_true`): emit JSON instead of the default table.
  - `--enabled` / `--disabled` (both `store_true`): subset selectors, NOT
    mutex. `--enabled --disabled` = all (= default). No
    `mutually_exclusive_group`.
  - `--busy` / `--free` (both `store_true`): subset selectors, NOT mutex.
    `--busy --free` = all (= default). **busy** = node has ≥1 RUNNING task with
    `allocated_ip == node.ip`; **free** = no such task.
  - `--cloud NAME` (`str`, exact match against `node.cloud`): single value.
    (Rejected `--cloud ""` for static nodes: an empty string is invisible on the
    command line and collides with argparse's flag-without-value error. The
    explicit `--no-cloud` flag below replaces it.)
  - `--no-cloud` (`store_true`): match nodes where `node.cloud is None`.
    `--cloud` and `--no-cloud` are in a `mutually_exclusive_group` —
    `--cloud hetzner --no-cloud` is an argparse error (exit 2). Rationale: unlike
    `--enabled`/`--disabled` (subset selectors over a 2-state attribute),
    `--cloud NAME` and `--no-cloud` select disjoint sets by value vs absence and
    cannot be unioned into "default"; both-present is a mistake, not the default.
  - `prog="yanodes"` is passed to `ArgumentParser` so `--help` and error screens
    show the command name (mirrors `entrypoints/cli/init.py`'s `prog="yainit"`).
  - All filters compose by AND. `--json` selects the renderer, not a filter.
  - `--help` shows the standard argparse help screen (argparse default).
  - `argv: list[str] | None = None` parameter for testability (mirrors
    `entrypoints/cli/init.py:init`).
- Exit code contract (mirrors `relocate-init-command` D3):
  - `0` on success (including empty filter results — an empty table or `[]` is
    a valid query answer, not a failure).
  - `1` on runtime failure: DB error, config parse error, any unexpected
    exception.
  - `2` on argparse error (argparse default — unknown flag, bad value, mutex
    violation).
- Default behavior preserved: `yanodes` (no flags) lists all nodes in the table
  format, exit 0. The output *format* changes (table replaces `key=value`) but
  the *information* shown (ip, port, ncpus, enabled, cloud, task_id, label)
  is the same.
- Output formats:
  - **Table (default):** fixed-width via `str.ljust`-style formatting, no
    external deps. One row per node. Display-only transformations: PORT = `-`
    when 22 else int, NCPUS = `MAX` when 0 else int, ENABLED = `yes`/`no`,
    CLOUD = `-` when None else string, TASK_ID/LABEL = `-` when free else
    value. Header row + data rows; column widths computed from the data.
  - **JSON (`--json`):** `json.dumps` of a list of one object per node, raw
    domain values (no display transformations): `port` and `ncpus` as raw ints
    (22 stays 22, 0 stays 0 — `MAX` is table-only), `cloud` as `null`/string,
    `occupied_by` as `null` when free or `{task_id, label}` when busy. The
    `occupied_by` single-object shape encodes the one-RUNNING-task-per-node
    invariant; promotion to array is a separate change if the domain ever
    allows >1.
- Split the logic into private pure functions in the new module: `_NodeView`
  (private frozen dataclass, local to the module), `_parse_nodes_args`,
  `_fetch_nodes_view` (async, two reads within one UoW — `uow.nodes.list_all()` +
  `uow.tasks.list_by_status({RUNNING})` — then an O(n+m) in-memory join via a
  `tasks_by_ip` dict built once),
  `_filter_rows` (AND of active predicates), `_render_nodes_table`,
  `_render_nodes_json`. Do NOT extract a `query_nodes` use case into
  `application/` — YAGNI: no second consumer of the join exists (the daemon
  tracks occupancy via `ConnectedMachine`/`AllocationTracker`; the client does
  not query nodes). The contract records that promotion to
  `application/query_nodes.py` awaits a second consumer.
- Do NOT carry the `# FIXME: split adapter and application layer` comment to the
  new file: the in-module function split resolves the concern for this command
  at this scale; the FIXME does not apply to the new home (same reasoning as
  `relocate-init-command` D7, adapted: there the FIXME was dropped because
  `init` does operational orchestration; here it is dropped because the split
  is into functions, not layers, and a use-case extraction is YAGNI).
- Do not sort output rows. Preserve the order returned by
  `uow.nodes.list_all()`. Tests feed nodes in a known order and assert it is
  preserved as-is.
- One row per node (one object per node in JSON). The domain invariant is one
  RUNNING task per node; the inner last-writer-wins loop in the current code is
  replaced by an explicit single-value join (`tasks_by_ip.get(node.ip)`).
- Fresh GRACE-lite markup at the new path: `MODULE_CONTRACT`, `MODULE_MAP`,
  `CHANGE_SUMMARY`, function contracts, and block anchors appropriate to the
  reimplemented logic. The `entrypoints/cli/__init__.py` facade is unchanged
  (it already exists from `relocate-init-command` and carries no `show_nodes`
  reference).
- Update `openspec/specs/package-facades/spec.md`: drop `show_nodes` from the R1
  example listing `infra/cli/__init__.py` submodules (the list becomes
  `check_status`, `daemonize`, `manage_node`, `submit`).
- Update `openspec/specs/cli-commands/spec.md`:
  - Update the `yanodes` requirement: module path
    `infra/cli/show_nodes.py` → `entrypoints/cli/show_nodes.py`; add the flag
    matrix, `--json` output, table/JSON format contracts, AND-filter semantics,
    exit-code contract, and one-row-per-node invariant.
  - Add `--json` as the established convention for machine-readable CLI output,
  starting with `yanodes`; note that future query-oriented commands may follow.
- Update `docs/knowledge-graph.xml`:
  - `M-CLI-COMMANDS`: delete the `<fn-show_nodes>` annotation.
  - Add a new module node `M-ENTRYPOINTS-CLI-SHOW-NODES`
    (`path: yascheduler/entrypoints/cli/show_nodes.py`,
    `depends: M-CONFIG, M-DI, M-DOMAIN-MODEL, M-SHARED`).
  - Add `CrossLink from="M-ENTRYPOINTS-CLI-SHOW-NODES" to="M-APPLICATION-UOW"
    relation="reads nodes and running tasks via UoW"` (and drop any stale
    `M-CLI-COMMANDS → ...` edge that existed for `show_nodes`).
- Tests:
  - Delete `tests/unit/test_cli_smoke.py::test_show_nodes_function_exists`
    (low-value smoke test that only checks the function exists and is
    `@to_sync`-decorated — replaced by real unit tests, same as
    `relocate-init-command` did for `init`).
  - Delete the `TestShowNodes` class from
    `tests/unit/test_cli_behavioral.py` (moved to a dedicated file).
  - Add `tests/unit/test_cli_show_nodes.py` with focused unit tests: flag
    parsing (each flag, combinations, mutex violation), filter behavior
    (enabled/disabled/busy/free/cloud/no-cloud, AND composition, empty result),
    table rendering (header, `-`/`MAX`/`yes-no` display transformations,
    column alignment, one row per node), JSON rendering (raw values,
    `occupied_by` null/object shape), exit codes (0 success incl. empty, 1
    runtime error, 2 argparse error), `--help` screen, O(n+m) join correctness
    against mocked UoW. Mark with `pytest.mark.unit`.

### Out of scope (explicit, deferred to follow-up changes)

- The other 4 CLI commands (`submit`, `check_status`, `manage_node`,
  `daemonize`) remain in `yascheduler/infra/cli/`; their migration into
  `entrypoints/cli/` is tracked separately. This change establishes the
  execution-command relocation pattern; the others may follow one per change.
- No new `application/query_nodes.py` use case (YAGNI — no second consumer).
- No multi-row-per-node / `occupied_by`-as-array support (domain invariant is
  one RUNNING task per node; promotion is a separate change if the invariant
  ever relaxes).
- No output row sorting (preserve `list_all()` order).
- No new dependencies (`rich`, `tabulate`, etc.) — fixed-width formatting via
  stdlib only.
- No `--watch` / polling mode, no `--ip` single-node selector, no
  `--cloud` multi-value / regex / substring matching — YAGNI.
- `schema-migrations` (in progress) — unaffected; `yanodes` is read-only and
  touches no schema. Parallel work, no conflict.
- `di.py`, `application/`, `domain/`, `infra/persistence/` — unchanged.

## Capabilities

### New Capabilities

_None._ The relocation and flag/format additions are structural/operational
concerns for an existing command. No new spec capability is introduced:
`yanodes` already exists under `cli-commands`, and its requirements are
modified (below) rather than replaced.

### Modified Capabilities

- `cli-commands`: the `yanodes` command gains `--json` / `--enabled` /
  `--disabled` / `--busy` / `--free` / `--cloud` / `--no-cloud` flags, a
  documented exit-code contract (`0`/`1`/`2`), a table output format (replacing
  `key=value`) with display transformations, a `--json` JSON output format with
  raw domain values, AND-filter semantics, a one-row-per-node invariant, and a
  new module path (`entrypoints/cli/show_nodes.py`). `--json` is recorded as
  the established convention for machine-readable CLI output, starting with
  `yanodes`.
- `package-facades`: the R1 example listing `infra/cli/__init__.py` submodules
  drops `show_nodes` (it has moved to `entrypoints/cli/`). No layer-direction
  or facade-content requirement changes.

## Impact

- **Code**: `yascheduler/entrypoints/cli/show_nodes.py` (1 new file);
  `yascheduler/infra/cli/show_nodes.py` removed;
  `yascheduler/infra/cli/__init__.py` loses the `show_nodes` re-export +
  `__all__` entry + MODULE_MAP line (bump VERSION, CHANGE_SUMMARY).
- **CLI**: `yanodes` behavior: default invocation output format changes from
  `key=value` to a fixed-width table (information preserved; format changed —
  no BREAKING change to the command name or default invocation). New flags:
  `--json`, `--enabled`, `--disabled`, `--busy`, `--free`, `--cloud NAME`,
  `--no-cloud`; `--help` works; exit codes `0`/`1`/`2` (was: 0 on success,
  non-deterministic traceback on error). No **BREAKING** change to the command
  name or the default invocation.
- **Config**: `pyproject.toml` line 50 (console_script target) updated.
  `[tool.importlinter]` unchanged.
- **Tests**: `tests/unit/test_cli_smoke.py` loses one test method;
  `tests/unit/test_cli_behavioral.py` loses the `TestShowNodes` class;
  `tests/unit/test_cli_show_nodes.py` added with focused unit tests for the new
  flag/filter/render/exit-code logic.
- **Specs**: `openspec/specs/cli-commands/spec.md` and
  `openspec/specs/package-facades/spec.md` modified.
- **Knowledge graph**: `docs/knowledge-graph.xml` — `M-CLI-COMMANDS` loses
  `<fn-show_nodes>`; new `M-ENTRYPOINTS-CLI-SHOW-NODES` node + CrossLink added.
- **Docs**: any references to the `yanodes` command name only — unchanged.
- **Dependencies**: none added or removed.