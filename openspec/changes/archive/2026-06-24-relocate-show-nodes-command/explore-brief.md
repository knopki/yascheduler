# Explore Brief — relocate-show-nodes-command

## Problem

`yascheduler/infra/cli/show_nodes.py` (58 lines) is the `yanodes` CLI command —
an execution query that lists enabled nodes and their currently running tasks.
It was explicitly listed as deferred-for-migration into the `entrypoints/` layer
by the archived `add-entrypoints-layer` change. The archived
`relocate-init-command` change then moved `init.py` into
`yascheduler/entrypoints/cli/init.py` as the first resident, establishing the
`entrypoints/cli/` home and the relocation pattern (real move, no compat shim,
layer direction `entrypoints → infra` preserved). `show_nodes` is the next
resident: it is an entrypoint (CLI command invoked by console_script), not an
infra adapter, and the `entrypoints/cli/` home already exists.

Current `show_nodes()`:

```python
@to_sync
async def show_nodes() -> None:
    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)
    async with deps.uow_factory() as uow:
        tasks = await uow.tasks.list_by_status(statuses={TaskStatus.RUNNING})
        nodes = await uow.nodes.list_all()
        for node in nodes:
            tmpl = "ip={ip}{port} ncpus={ncpus} enabled={enabled} occupied_by={occ} (task_id={tid}) {cloud}"
            node_tasks = [t for t in tasks if t.allocated_ip == node.ip]
            node_label = "-"
            task_id = "-"
            for x in node_tasks:
                node_label = x.label
                task_id = x.task_id
            msg = tmpl.format(...)
            print(msg)
```

Issues with the current shape, in scope for this change:
- No argparse: `yanodes` takes no flags. No `--help`, no filters, no
  machine-readable output.
- The format string `tmpl` is re-built inside the loop on every iteration.
- O(n*m) inner scan: for each node, scan all running tasks to find the ones on
  that ip. Should be O(n+m) via a single `tasks_by_ip` dict built once.
- The inner `for x in node_tasks` loop silently overwrites `node_label` /
  `task_id` each iteration, so if a node ever had >1 running task, only the last
  would be shown. Today the domain invariant is one RUNNING task per node, so
  this is latent rather than active, but it is hidden logic.
- No exit-code contract. The function returns normally on success and propagates
  exceptions (DB error, config error) as tracebacks with whatever exit code
  Python assigns — non-deterministic, not 1.
- `# FIXME: split adapter and application layer` carried from the `infra/cli/`
  template. For `show_nodes` the FIXME is more applicable than it was for `init`
  (there is genuine query/join logic here), but the resolution chosen in this
  change is in-module function splitting, not extracting a use case — see D2.

## Rejected alternatives

- **Move all 5 remaining CLI commands (`submit`, `check_status`, `show_nodes`,
  `manage_node`, `daemonize`) to `entrypoints/cli/` in one change.** Rejected
  for scope: each command has its own redesign surface (argparse, exit codes,
  output format). Bundling them produces a巨型 change with 5 independent
  decision matrices. `show_nodes` is scoped here; the other 4 may follow in
  separate changes. This change establishes the pattern for execution-command
  relocation (init was the bootstrap-command precedent; this is the
  execution-command precedent).
- **Keep a compat shim at `infra/cli/show_nodes.py` re-exporting from
  `entrypoints/cli/show_nodes.py`.** Rejected: any `infra → entrypoints`
  re-export inverts the layer direction
  (`entrypoints → infra → application → domain → shared`) enforced by
  import-linter's `layers` contract. The `relocate-init-command` precedent
  established that entrypoint residents are invoked by path / console_script,
  not re-exported from `infra/`. No deep import of
  `from yascheduler.infra.cli.show_nodes import show_nodes` exists in production
  code (verified by grep); the only consumers are
  `yascheduler/infra/cli/__init__.py` (re-export), `pyproject.toml`
  (console_script target), and two test files — all updated in this change.
- **Extract a `query_nodes` use case into `yascheduler/application/` mirroring
  `query_tasks.py`.** Rejected as YAGNI: `query_tasks` was extracted because the
  AiiDA client (`yascheduler.entrypoints.client.Yascheduler.queue_get_tasks_async`)
  was a real second consumer of the same query. No second consumer of "join
  nodes to their running tasks" exists — the daemon tracks occupancy via
  `ConnectedMachine` / `AllocationTracker`, not via this join; the client does
  not query nodes. The join is in-memory DTO assembly, not a business rule. The
  resolution is in-module splitting into private pure functions
  (`_fetch_nodes_view`, `_filter_rows`, `_render_*`); the contract records that
  promotion to `application/query_nodes.py` awaits a second consumer.
- **Sort output rows (by enabled desc, then ip; or by ip).** Rejected: the user
  explicitly chose to preserve the order returned by `uow.nodes.list_all()`.
  Tests must feed nodes in a known order and assert it is preserved as-is (no
  sort-stability test, because there is no sort).
- **Multiple rows per node (one per task) for future-proofing against >1 RUNNING
  task per node.** Rejected: the domain invariant is one RUNNING task per node,
  and the user confirmed one row per node. The JSON shape `occupied_by` as a
  single object (not an array) encodes the same invariant. If the domain ever
  allows >1, JSON `occupied_by` → array AND table multi-row would change
  together in a separate change.
- **`--cloud ""` (empty string) for static (cloud-less) nodes.** Rejected as
  too obscure (empty string is invisible on the command line and collides with
  argparse's "flag without value" error). Replaced by an explicit `--no-cloud`
  store_true flag, mutually exclusive with `--cloud`.
- **Add a dependency (`rich`, `tabulate`) for table formatting.** Rejected:
  AGENTS.md forbids adding dependencies without a declared rationale, and
  fixed-width formatting via Python str formatting is trivial and dependency-
  free. The table is rendered with plain f-strings / `str.ljust`.

## Final approach — labels / dimensions / mapping tables

### Flag matrix

| invocation                          | --json | --enabled | --disabled | --busy | --free | --cloud | --no-cloud | action                                          | exit |
| ----------------------------------- | ------ | --------- | ---------- | ------ | ------ | ------- | ---------- | ----------------------------------------------- | ---- |
| `yanodes`                             | -      | -         | -          | -      | -      | -       | -          | all nodes, table                                | 0/1  |
| `yanodes --json`                      | yes    | -         | -          | -      | -      | -       | -          | all nodes, JSON                                 | 0/1  |
| `yanodes --enabled`                   | -      | yes       | -          | -      | -      | -       | -          | only enabled                                    | 0/1  |
| `yanodes --disabled`                  | -      | -         | yes        | -      | -      | -       | -          | only disabled                                   | 0/1  |
| `yanodes --enabled --disabled`        | -      | yes       | yes        | -      | -      | -       | -          | all (= default, subset semantics)              | 0/1  |
| `yanodes --busy`                      | -      | -         | -          | yes    | -      | -       | -          | only busy (≥1 RUNNING task)                     | 0/1  |
| `yanodes --free`                      | -      | -         | -          | -      | yes    | -       | -          | only free (no RUNNING task)                     | 0/1  |
| `yanodes --busy --free`               | -      | -         | -          | yes    | yes    | -       | -          | all (= default, subset semantics)              | 0/1  |
| `yanodes --cloud hetzner`             | -      | -         | -          | -      | -      | hetzner | -          | only nodes with cloud == hetzner               | 0/1  |
| `yanodes --no-cloud`                  | -      | -         | -          | -      | -      | -       | yes        | only static (cloud is None) nodes               | 0/1  |
| `yanodes --cloud hetzner --no-cloud`  | -      | -         | -          | -      | -      | hetzner | yes        | argparse error (mutex group)                    | 2    |
| `yanodes --cloud hetzner --enabled --busy` | - | -      | -          | yes    | -      | hetzner | -          | AND of all filters: enabled AND busy AND hetzner | 0/1  |
| `yanodes --help`                      | n/a    | n/a       | n/a        | n/a    | n/a    | n/a     | n/a        | argparse help screen                             | 0    |
| `yanodes --bogus`                     | n/a    | n/a       | n/a        | n/a    | n/a    | n/a     | n/a        | argparse error                                   | 2    |

Flag semantics:
- `--json` (`store_true`): emit JSON instead of the table. Independent of all
  filters.
- `--enabled` / `--disabled` (both `store_true`): subset selectors, NOT mutex.
  `--enabled --disabled` = all (= default). No `mutually_exclusive_group`.
- `--busy` / `--free` (both `store_true`): subset selectors, NOT mutex.
  `--busy --free` = all (= default). No `mutually_exclusive_group`.
  - **busy** = node has ≥1 RUNNING task with `allocated_ip == node.ip`.
  - **free** = node has no such task.
- `--cloud NAME` (`str`, exact match against `node.cloud`): single value,
  exact equality. `None`/empty `node.cloud` matches no `--cloud` value.
- `--no-cloud` (`store_true`): match nodes where `node.cloud is None`.
  **Mutually exclusive** with `--cloud` (the only `mutually_exclusive_group` in
  the parser; `--cloud hetzner --no-cloud` → argparse error, exit 2). Rationale:
  unlike `--enabled`/`--disabled` (which are subset selectors over a 2-state
  attribute), `--cloud NAME` and `--no-cloud` select disjoint sets by *value*
  vs *absence* and cannot be unioned into "default"; treating both-present as
  "all" would silently discard the user's explicit `NAME`, which is a mistake,
  not the default.
- All filters compose by AND: a row is emitted iff it passes every active
  filter. `--enabled --busy --cloud hetzner` = enabled AND busy AND hetzner.
- Default (no flags) = all nodes, table format, exit 0 — current behavior
  preserved.

### Exit code contract

| code | meaning                              | source                                                       |
| ---- | ------------------------------------ | ------------------------------------------------------------ |
| 0    | success (including empty result)     | normal completion; empty filter result still exits 0         |
| 1    | runtime failure                      | DB error, config parse error, any unexpected exception       |
| 2    | argparse error                       | argparse default (unknown flag, bad value, mutex violation) |

Mirrors the `relocate-init-command` precedent.

### Output formats

**Table (default):** fixed-width, no external deps, `str.ljust`-style. One row
per node. Display-only transformations:

| field    | raw value     | table cell | note                                |
| -------- | ------------- | ---------- | ----------------------------------- |
| IP       | `node.ip`       | as-is      |                                     |
| PORT     | `node.port`     | `-` when 22, else int | symmetry with old `:22` hidden   |
| NCPUS    | `node.ncpus`    | `MAX` when 0, else int | preserve user-facing display     |
| ENABLED  | `node.enabled`  | `yes` / `no` |                                   |
| CLOUD    | `node.cloud`     | `-` when None, else string |                             |
| TASK_ID  | task.task_id     | `-` when free, else int |                                  |
| LABEL    | task.label       | `-` when free, else string |                                |

Header row + data rows. Column widths computed from the data (max of header
and cell widths per column) so the table is self-aligning regardless of value
lengths. No trailing whitespace trimming policy — fixed width per column.

```
IP            PORT   NCPUS  ENABLED  CLOUD    TASK_ID  LABEL
10.0.0.1      -      4      yes      -        1        my_job
10.0.0.2      2222   MAX    no       hetzner  -        -
```

**JSON (`--json`):** `json.dumps` of a list of objects, one per node. Raw
domain values — NO display transformations (no `-`, no `MAX`, no `yes/no`):

```json
[
  {"ip": "10.0.0.1", "port": 22, "ncpus": 4, "enabled": true,
   "cloud": null, "occupied_by": {"task_id": 1, "label": "my_job"}},
  {"ip": "10.0.0.2", "port": 2222, "ncpus": 0, "enabled": false,
   "cloud": "hetzner", "occupied_by": null}
]
```

- `port`: raw int (22 stays 22, 2222 stays 2222).
- `ncpus`: raw int (0 stays 0 — `MAX` is table-only display).
- `cloud`: `null` for static nodes, else the string.
- `occupied_by`: `null` when free, single object `{task_id, label}` when busy.
  Shape encodes the one-RUNNING-task-per-node invariant; promotion to array is
  a separate change if the domain ever allows >1.

### `NodeView` (private DTO, local to the module)

```python
@dataclass(frozen=True)
class _NodeView:
    ip: str
    port: int
    ncpus: int
    enabled: bool
    cloud: str | None
    task_id: int | None    # None when free
    label: str | None      # None when free
```

Private (leading underscore), local to `entrypoints/cli/show_nodes.py`. Not
exported, not in the domain layer. The renderers consume `list[_NodeView]`;
filters consume it too. `_fetch_nodes_view` builds it from one UoW read.

### Module shape (D2 — in-module splitting, no use case extraction)

```
entrypoints/cli/show_nodes.py
  _NodeView                 # @dataclass(frozen=True), private
  _parse_nodes_args(argv)   # pure: argparse → Namespace (prog="yanodes")
  _fetch_nodes_view(uow)    # async: one UoW → list[_NodeView] (O(n+m) join)
  _filter_rows(rows, args)  # pure: list[_NodeView] × Namespace → list[_NodeView]
  _render_nodes_table(rows) # pure: list[_NodeView] → str
  _render_nodes_json(rows)  # pure: list[_NodeView] → str
  show_nodes(argv=None)     # @to_sync: parse → config → deps → fetch → filter → render → print
```

`_fetch_nodes_view` does two reads (`uow.nodes.list_all()` and
`uow.tasks.list_by_status({RUNNING})`) and one in-memory join via a
`tasks_by_ip` dict built once (O(n+m)). The contract records that promotion to
`application/query_nodes.py` awaits a second consumer.

### Filter semantics (D3 — AND composition, subset selectors)

A row passes the filter iff ALL active predicates hold:

- `enabled` filter active iff `args.enabled` is True.
  - If `args.enabled and not args.disabled`: keep `row.enabled == True`.
  - If `args.disabled and not args.enabled`: keep `row.enabled == False`.
  - If both or neither: no `enabled` filtering (all pass this axis).
- `busy` filter active iff `args.busy` is True.
  - If `args.busy and not args.free`: keep `row.task_id is not None`.
  - If `args.free and not args.busy`: keep `row.task_id is None`.
  - If both or neither: no `busy` filtering.
- `cloud` filter: `args.cloud` (str) XOR `args.no_cloud` (bool), enforced as
  mutex by argparse. If `args.cloud` is not None: keep `row.cloud == args.cloud`.
  If `args.no_cloud` is True: keep `row.cloud is None`. If neither: no cloud
  filtering.

`--json` is not a filter; it selects the renderer.

## Cross-module data flows

### Call path (after change)

```
yanodes (console_script)
  → yascheduler.entrypoints.cli.show_nodes.show_nodes()
      → _parse_nodes_args(argv)            # argparse: --json/--enabled/--disabled/--busy/--free/--cloud/--no-cloud
      → Config.from_config_parser(CONFIG_FILE)
      → make_cli_deps(config)
      → try:
          async with deps.uow_factory() as uow:
              → _fetch_nodes_view(uow)
                  → uow.tasks.list_by_status({TaskStatus.RUNNING})  # one read
                  → uow.nodes.list_all()                            # one read
                  → build tasks_by_ip = {t.allocated_ip: t for t in tasks}
                  → for node in nodes: join via tasks_by_ip.get(node.ip) → _NodeView
          → _filter_rows(rows, args)        # AND of active predicates
          → if args.json: print(_render_nodes_json(rows))
            else:           print(_render_nodes_table(rows))
        except Exception as e:
          print(f"Error: {e}", file=sys.stderr); sys.exit(1)
      → implicit exit 0 (no sys.exit(0) needed — return is exit 0)
```

Note: `show_nodes` does NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits 0. Only the failure path calls
`sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/`sys.exit(2)`
internally before reaching the body.

### Layer direction (verified)

```
yascheduler.entrypoints.cli.show_nodes
  → yascheduler.config.Config                     (entrypoints → config, outside-layer-set ✓)
  → yascheduler.di.make_cli_deps                   (entrypoints → di, outside-layer-set ✓ — same as init)
  → yascheduler.domain.TaskStatus                  (entrypoints → domain ✓)
  → yascheduler.shared.CONFIG_FILE, to_sync        (entrypoints → shared ✓)
```

`import-linter` `layers` contract stays green:
`["yascheduler.entrypoints", "yascheduler.infra", "yascheduler.application",
"yascheduler.domain", "yascheduler.shared"]`. `ignore_imports` stays `[]`.
No new `ignore_imports` entries needed. (Note: `make_cli_deps` lives in
`yascheduler/di.py` which is outside the layered set — same pattern `init.py`
already uses; `check_status.py` / `submit.py` in `infra/cli/` already import
`make_cli_deps` the same way.)

### Files added / removed / modified

| action   | path                                                | note                                                                  |
| -------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| add      | `yascheduler/entrypoints/cli/show_nodes.py`         | real implementation                                                   |
| remove   | `yascheduler/infra/cli/show_nodes.py`               | moved, not shimmed                                                    |
| modify   | `yascheduler/infra/cli/__init__.py`                 | drop `from .show_nodes import show_nodes` + `"show_nodes"` from `__all__` + MODULE_MAP line; bump VERSION; CHANGE_SUMMARY |
| modify   | `pyproject.toml` line 50                            | `yanodes = "yascheduler.entrypoints.cli.show_nodes:show_nodes"`       |
| modify   | `openspec/specs/package-facades/spec.md` R1 example | drop `show_nodes` from infra/cli submodule list (line ~103)           |
| modify   | `openspec/specs/cli-commands/spec.md`               | update path; add yanodes flag scenarios, --json, exit codes, table/JSON formats |
| modify   | `docs/knowledge-graph.xml`                          | drop `M-CLI-COMMANDS` `<fn-show_nodes>`; add `M-ENTRYPOINTS-CLI-SHOW-NODES` node + CrossLinks |
| modify   | `tests/unit/test_cli_smoke.py`                      | delete `test_show_nodes_function_exists`                              |
| modify   | `tests/unit/test_cli_behavioral.py`                 | delete `TestShowNodes` class (moved to dedicated file)                |
| add      | `tests/unit/test_cli_show_nodes.py`                 | focused unit tests (new file, mirrors `test_cli_init.py` shape)       |

## Open questions

None. All decisions captured above. Ready to write proposal.