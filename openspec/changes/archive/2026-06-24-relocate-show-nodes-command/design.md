## Context

`yanodes` is the CLI command that lists enabled nodes and their currently
running tasks. It lives at `yascheduler/infra/cli/show_nodes.py` (58 lines) and
is registered as the `yanodes` `console_script` in `pyproject.toml` line 50.
The archived `add-entrypoints-layer` change created `yascheduler/entrypoints/`
as the outermost hexagonal layer and listed `infra/cli/` as deferred-for-
migration; the archived `relocate-init-command` change then moved `init.py`
into `yascheduler/entrypoints/cli/init.py` as the first resident, establishing
the `entrypoints/cli/` home and the relocation pattern (real move, no compat
shim, layer direction `entrypoints → infra` preserved, fresh GRACE-lite markup,
argparse-based reimplemented logic, `0`/`1`/`2` exit-code contract).
`show_nodes` is the second resident: it is an execution query (the
execution-command counterpart to `init`'s bootstrap-command precedent), and
the `entrypoints/cli/` home already exists.

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

The domain invariant is one RUNNING task per node (`Task.allocated_ip` is a
single value; the allocator assigns one task to one node at a time). The
inner `for x in node_tasks` loop is last-writer-wins, which is latent rather
than active under that invariant, but is hidden logic. The `Node` entity
(`yascheduler/domain/model.py`) carries `ip`, `ncpus`, `enabled`, `cloud`,
`username`, `port` (default 22). `uow.nodes.list_all()` returns
`list[Node]`; `uow.tasks.list_by_status({RUNNING})` returns `list[Task]`. The
UoW exposes two separate repositories (`tasks`, `nodes`); there is no joined
query, so the join is in-memory in the CLI module.

`schema-migrations` (in progress) is adding a versioned migration system
alongside `apply_schema`; it does not touch `yanodes` or any read-only query
path, so this change and that one do not conflict.

## Goals / Non-Goals

**Goals:**
- Move `show_nodes.py` from `infra/cli/` to `entrypoints/cli/` as the second
  resident, mirroring the `relocate-init-command` precedent (real move, no
  compat shim, layer direction preserved).
- Reimplement `show_nodes()` with `argparse` exposing `--json`, `--enabled`,
  `--disabled`, `--busy`, `--free`, `--cloud NAME`, `--no-cloud` flags.
- Define and enforce the `0`/`1`/`2` exit-code contract (mirrors `init`).
- Replace the `key=value` output with a fixed-width table (default) and a
  raw-domain-values JSON output (`--json`), both with one row/object per node.
- Split the logic into private pure functions in the module
  (`_parse_nodes_args`, `_fetch_nodes_view`, `_filter_rows`, `_render_nodes_table`,
  `_render_nodes_json`) with a private `_NodeView` DTO local to the module.
- Preserve every public contract: `yanodes` command name, default invocation
  behavior (all nodes listed), `console_script` wiring, layer-direction
  compliance, no new dependencies.

**Non-Goals:**
- Move the other 4 CLI commands (`submit`, `check_status`, `manage_node`,
  `daemonize`) — they stay in `infra/cli/` for follow-up changes. This change
  establishes the execution-command relocation pattern; it does not prejudge
  the others.
- Extract a `query_nodes` use case into `yascheduler/application/` — YAGNI; no
  second consumer of the join exists (the daemon tracks occupancy via
  `ConnectedMachine`/`AllocationTracker`; the client does not query nodes).
  Promotion to `application/query_nodes.py` awaits a second consumer and is
  recorded in the `_fetch_nodes_view` contract.
- Support multiple RUNNING tasks per node (multi-row table / `occupied_by` as
  an array). The domain invariant is one RUNNING task per node; the
  `occupied_by` single-object shape encodes it. Promotion to array + multi-row
  is a separate change if the invariant ever relaxes.
- Sort output rows. Preserve the order returned by `uow.nodes.list_all()`.
- Add a `--watch`/polling mode, `--ip` single-node selector, or
  `--cloud` multi-value/regex/substring matching — YAGNI.
- Add a dependency (`rich`, `tabulate`, etc.) — fixed-width formatting via
  stdlib only.
- Touch `di.py`, `application/`, `domain/`, `infra/persistence/` — unchanged.

## Decisions

### D1 — Real implementation at the new path, no compat shim

**Choice:** Move the real implementation to
`yascheduler/entrypoints/cli/show_nodes.py`; delete
`yascheduler/infra/cli/show_nodes.py`; drop `from .show_nodes import show_nodes`
and `"show_nodes"` from `__all__` in `yascheduler/infra/cli/__init__.py`; drop
the `show_nodes - Re-exported from .show_nodes` line from its `MODULE_MAP`;
update `pyproject.toml` line 50 to
`yanodes = "yascheduler.entrypoints.cli.show_nodes:show_nodes"`.

**Rationale:** A compat shim at `infra/cli/show_nodes.py` re-exporting from
`entrypoints/cli/show_nodes.py` would create an `infra → entrypoints` import,
inverting the layer direction (`entrypoints → infra → application → domain →
shared`) enforced by `import-linter`'s `layers` contract. The
`relocate-init-command` precedent established that entrypoint residents are
invoked by path / console_script, not re-exported from `infra/`. No deep
import of `from yascheduler.infra.cli.show_nodes import show_nodes` exists in
production code (verified by grep); the only consumers are
`yascheduler/infra/cli/__init__.py` (re-export), `pyproject.toml`
(console_script target), and two test files — all updated in this change.

**Alternative rejected:** Keep a one-line shim at `infra/cli/show_nodes.py`
re-exporting from the new location. Rejected: the layer violation is real and
the import-linter contract would need an `ignore_imports` entry to suppress
it — adding technical debt to preserve a path that no production code uses.

### D2 — In-module function splitting; no use-case extraction

**Choice:** Split the logic into private pure functions inside
`entrypoints/cli/show_nodes.py`: `_NodeView` (private frozen dataclass),
`_parse_nodes_args(argv)`, `_fetch_nodes_view(uow)`, `_filter_rows(rows, args)`,
`_render_nodes_table(rows)`, `_render_nodes_json(rows)`. Do NOT extract a
`query_nodes` use case into `yascheduler/application/`.

**Rationale:** The `query_tasks` use case was extracted (in the archived
`client-query-uow` change) because the AiiDA client
(`yascheduler.entrypoints.client.Yascheduler.queue_get_tasks_async`) was a real
second consumer of the same query. No second consumer of "join nodes to their
running tasks" exists: the daemon tracks occupancy via `ConnectedMachine` and
`AllocationTracker` (runtime state, not this DB join), and the client does not
query nodes. The join is in-memory DTO assembly, not a business rule.
Extracting a use case now would create a module with a single caller and no
prospect of a second — the textbook YAGNI violation. The in-module split still
achieves the FIXME's intent (logic vs display separation) at the appropriate
granularity (functions, not layers). The `_fetch_nodes_view` contract records
that promotion to `application/query_nodes.py` awaits a second consumer.

**Alternative rejected:** Create `yascheduler/application/query_nodes.py`
mirroring `query_tasks.py`. Rejected: no second consumer; the join is DTO
assembly, not business logic; produces a one-caller use case.

### D3 — Subset selectors vs mutex for the filter flags

**Choice:**
- `--enabled` / `--disabled` (both `store_true`): subset selectors, NOT mutex.
  `--enabled --disabled` = all (= default). No `mutually_exclusive_group`.
- `--busy` / `--free` (both `store_true`): subset selectors, NOT mutex.
  `--busy --free` = all (= default).
- `--cloud NAME` / `--no-cloud` (`store_true`): **mutually exclusive** — the
  ONLY `mutually_exclusive_group` in the parser. `--cloud hetzner --no-cloud`
  → argparse error (exit 2).
- All filters compose by AND. `--json` selects the renderer, not a filter.

**Rationale:** `--enabled`/`--disabled` and `--busy`/`--free` are subset
selectors over a 2-state attribute; both-present means "both subsets" = the
full set = the default, so erroring would be hostile to scripting (same
reasoning as `init`'s `--schema`/`--daemon`). `--cloud NAME` and `--no-cloud`
are different: they select disjoint sets by *value* vs *absence*. There is no
sensible union of "nodes whose cloud is hetzner" and "nodes whose cloud is
None" that equals "all nodes" — that would silently discard the user's
explicit `NAME`. Both-present here is a mistake, not the default, so argparse
exits `2`.

**Alternative rejected (a):** Make `--enabled`/`--disabled` mutually exclusive.
Rejected: both-present = default is the natural reading; erroring adds no value.
**Alternative rejected (b):** Allow `--cloud NAME --no-cloud` to mean "all".
Rejected: silently discards the explicit `NAME`; the user typed it for a
reason.

### D4 — `--no-cloud` for static nodes (not `--cloud ""`)

**Choice:** Add `--no-cloud` (`store_true`) to match nodes where
`node.cloud is None`. Make it mutually exclusive with `--cloud NAME` (D3).

**Rationale:** The natural alternative, `--cloud ""`, is invisible on the
command line and collides with argparse's "flag without value" error. An
explicit `--no-cloud` flag is discoverable via `--help` and self-documenting.
The mutex with `--cloud` (D3) prevents the nonsensical both-present case.

**Alternative rejected:** `--cloud ""` for static nodes. Rejected: invisible
on the CLI, collides with argparse semantics.

### D5 — Exit codes `0` / `1` / `2`

**Choice:**
- `0` on success, including an empty filter result (an empty table or `[]` is
  a valid query answer, not a failure).
- `1` on runtime failure: DB error, config parse error, any unexpected
  exception caught at the top level.
- `2` on argparse error (argparse default — unknown flag, bad value, mutex
  violation).

**Rationale:** Mirrors the `relocate-init-command` D3 precedent exactly. `2`
is the argparse default that shell scripts expect for usage errors; reusing it
avoids fighting the framework. `1` for runtime failures is the POSIX
convention. The current code has no exit-code contract (it returns on success
and propagates exceptions as tracebacks with non-deterministic exit codes);
this contract makes failures visible and scriptable.

**Note on `sys.exit(0)`:** `show_nodes` does NOT call `sys.exit(0)` explicitly
on success — the function returns normally and the process exits `0`. Only the
failure path calls `sys.exit(1)`. argparse's `--help`/error path calls
`sys.exit(0)`/`sys.exit(2)` internally before reaching the body. This differs
slightly from `init`, which calls `sys.exit(0)` explicitly because `init`'s
body has no other terminal point; `show_nodes` returns from the body normally.

**Alternative rejected:** Use `sysexits.h` codes. Rejected: over-engineering;
`0/1/2` is the convention every other yascheduler CLI command follows.

### D6 — Table format (default) with display transformations

**Choice:** Default output is a fixed-width table, one row per node, with a
header row. Column widths computed from the data (max of header and cell
widths per column). Rendered with stdlib `str` formatting (`str.ljust`-style
or f-string width specifiers) — no external deps. Display-only transformations:

| field    | raw value       | table cell                       |
| -------- | --------------- | -------------------------------- |
| IP       | `node.ip`         | as-is                            |
| PORT     | `node.port`       | `-` when 22, else int            |
| NCPUS    | `node.ncpus`      | `MAX` when 0, else int           |
| ENABLED  | `node.enabled`    | `yes` / `no`                     |
| CLOUD    | `node.cloud`      | `-` when None, else string       |
| TASK_ID  | `task.task_id`     | `-` when free, else int          |
| LABEL    | `task.label`       | `-` when free, else string       |

```
IP            PORT   NCPUS  ENABLED  CLOUD    TASK_ID  LABEL
10.0.0.1      -      4      yes      -        1        my_job
10.0.0.2      2222   MAX    no       hetzner  -        -
```

**Rationale:** A fixed-width table is more readable than `key=value` when
values vary in length, and it scales to multiple rows without visual noise.
The display transformations (`-` for 22, `MAX` for 0, `yes`/`no`) preserve
the user-facing meaning of the current format (`:22` hidden, `MAX` for
unlimited cpus, boolean as word) while making the table compact. Column widths
from data (not hardcoded) keep the table self-aligning for any IP/label/cloud
length. No deps per AGENTS.md.

**Alternative rejected:** Keep `key=value` as default, add `--table` for the
new format. Rejected: nothing parses the current format (verified by grep —
no caller matches `ip=`/`occupied_by=` output), and the user explicitly chose
to change the default. Two formats with a flag to switch adds complexity for
no consumer.

### D7 — JSON format (`--json`) with raw domain values

**Choice:** `--json` emits `json.dumps(list_of_objects)`, one object per
node, with raw domain values — NO display transformations:

```json
[
  {"ip": "10.0.0.1", "port": 22, "ncpus": 4, "enabled": true,
   "cloud": null, "occupied_by": {"task_id": 1, "label": "my_job"}},
  {"ip": "10.0.0.2", "port": 2222, "ncpus": 0, "enabled": false,
   "cloud": "hetzner", "occupied_by": null}
]
```

- `port`: raw int (22 stays 22, 2222 stays 2222 — no `-`).
- `ncpus`: raw int (0 stays 0 — no `MAX`; `MAX` is a table-only display token).
- `cloud`: `null` for static nodes, else the string.
- `occupied_by`: `null` when free, single object `{"task_id", "label"}` when
  busy. The single-object shape encodes the one-RUNNING-task-per-node
  invariant; promotion to an array is a separate change if the invariant ever
  relaxes.

**Rationale:** JSON is for machines; machines want the real values, not
display tokens (`-`, `MAX`, `yes`/`no`). Keeping `port` and `ncpus` as raw
ints means a consumer does not need to reverse the display transformations.
The `occupied_by` shape (null vs object) is a clean signal for free/busy and
extends naturally to an array if the domain ever allows >1.

**Alternative rejected:** Reuse the table's display transformations in JSON.
Rejected: a machine reading `ncpus: "MAX"` or `port: "-"` would have to
reverse-map strings to semantics — defeating the purpose of machine-readable
output.

### D8 — `_NodeView` private DTO, local to the module

**Choice:** Define a private frozen dataclass `_NodeView` (leading underscore)
inside `entrypoints/cli/show_nodes.py`:

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

It is NOT exported, NOT placed in the domain layer, and NOT added to any
facade. `_fetch_nodes_view` returns `list[_NodeView]`; `_filter_rows` and the
two renderers consume it.

**Rationale:** The DTO is a CLI-specific projection (node joined with at most
one running task), not a domain entity. Placing it in `domain/` would pollute
the domain with a presentation concern; placing it in `application/` would
imply a use case (rejected in D2). A private local dataclass keeps the
projection co-located with its only consumer and its renderer. The leading
underscore signals "module-private, not public surface."

**Alternative rejected:** Reuse `Node` + `Task` directly in the renderers.
Rejected: the renderers would each re-do the join logic (lookup task by ip),
duplicating the O(n+m) dict and the "at most one task" invariant handling.
A single `_NodeView` built once in `_fetch_nodes_view` is the single source
of truth for the projection.

### D9 — No sorting; preserve `list_all()` order

**Choice:** Do not sort the rows. Emit them in the order returned by
`uow.nodes.list_all()`.

**Rationale:** The user explicitly chose to preserve the current order. Adding
a sort (by enabled desc, then ip; or by ip) would change observed behavior and
add a decision (which key?) with no consumer demand. Tests feed nodes in a
known order and assert it is preserved as-is; no sort-stability test is needed
because there is no sort.

**Alternative rejected:** Sort by enabled desc, then ip. Rejected: changes
observed order; no consumer demand; adds a decision with no payoff.

### D10 — One row per node (one object per node in JSON)

**Choice:** Emit exactly one table row per node and exactly one JSON object
per node. The `_fetch_nodes_view` join uses `tasks_by_ip.get(node.ip)` (single
value, not a list), reflecting the one-RUNNING-task-per-node invariant. The
current code's inner `for x in node_tasks` last-writer-wins loop is replaced
by this explicit single-value lookup.

**Rationale:** The domain invariant is one RUNNING task per node. The current
code is accidentally correct under that invariant (last-writer-wins of a
1-element list yields that element) but hides the logic. The explicit
`tasks_by_ip.get(node.ip)` makes the invariant structural. If the domain ever
allows >1, both the table (multi-row) and JSON (`occupied_by` → array) would
change together in a separate change; this change does not pre-empt that.

**Alternative rejected:** Emit multiple rows per node now (one per task) to
future-proof. Rejected by the user: the invariant holds today; multi-row is
speculative and would change the observed row count.

### D11 — `argv: list[str] | None = None` testability parameter

**Choice:** `show_nodes(argv: list[str] | None = None) -> None` passes
`argv` through to `_parse_nodes_args(argv)` and thence to
`parser.parse_args(argv)`. The `argv=None` default means the console_script
entrypoint (which calls `show_nodes()` with no args) reads `sys.argv` — the
standard argparse convention; tests pass an explicit list.

**Rationale:** Mirrors `entrypoints/cli/init.py:init(argv=None)`. Makes the
argparse path unit-testable without `patch("sys.argv", ...)` (the current
behavioral tests use `patch("sys.argv", ...)`, which is fragile and couples
test to global state). The `init` precedent established this pattern; `yanodes`
follows it.

**Alternative rejected:** Read `sys.argv` inside the function via
`parse_args()` with no argument. Rejected: forces tests to patch `sys.argv`
(a global), which the `init` reimplementation already moved away from.

### D12 — `prog="yanodes"` for argparse

**Choice:** `argparse.ArgumentParser(prog="yanodes", description="Show nodes and their running tasks")`.

**Rationale:** `--help` and error screens show the command name the user
typed. Mirrors `entrypoints/cli/init.py`'s `prog="yainit"`. Without `prog`,
argparse derives the program name from `sys.argv[0]`, which for a
console_script is the script path, not the command name.

### D13 — Fresh GRACE-lite markup; drop the FIXME

**Choice:** The new `entrypoints/cli/show_nodes.py` gets fresh
`MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`, function contracts (for
`show_nodes` and the private helpers as appropriate), and block anchors
appropriate to the reimplemented logic. Do NOT carry the
`# FIXME: split adapter and application layer` comment to the new file.

**Rationale:** GRACE-lite requires governed files to carry markup; the
reimplementation has different control flow (argparse dispatch, filter
composition, two renderers) than the original, so the markup is written for
the new shape. The FIXME is dropped because the in-module function split (D2)
resolves the concern at the appropriate granularity: the "logic" lives in
`_fetch_nodes_view` / `_filter_rows`, the "display" in `_render_*`, all
private to the module. Carrying the FIXME would mark a resolved concern as
still open. (This adapts `relocate-init-command` D7's reasoning: there the
FIXME was dropped because `init` does operational orchestration with no
business logic to split; here it is dropped because the split is into
functions, not layers, and a use-case extraction is YAGNI.)

### D14 — `entrypoints/cli/__init__.py` facade unchanged

**Choice:** Do not modify `yascheduler/entrypoints/cli/__init__.py`. It was
created by `relocate-init-command` as a subpackage facade with no re-exports
(`init` is invoked by console_script, not imported across layers). `show_nodes`
follows the same pattern: invoked by console_script, not re-exported. The
facade's `MODULE_CONTRACT` (PURPOSE: subpackage facade for the `init` CLI
entry point; SCOPE: no re-exports) is updated only if its PURPOSE wording
needs to generalize to "init and show_nodes CLI entry points" — a declarative
edit, not a decision-level change. (See tasks for the exact wording update.)

**Rationale:** The facade exists to be the subpackage boundary; its content
(no re-exports) does not change because `show_nodes` is also invoked by
console_script. The `init` precedent did not add an `init` re-export to the
facade; `show_nodes` does not add one either.

## Risks / Trade-offs

- **[Risk] Output format change breaks scripts that parse `yanodes`.** →
  Mitigation: grep verified no caller matches `ip=`/`occupied_by=` output; the
  user confirmed nobody parses it and serious out-of-scope changes are coming
  anyway. The information shown (ip, port, ncpus, enabled, cloud, task_id,
  label) is preserved; only the format changes. `--json` provides a stable
  machine-readable path going forward.
- **[Risk] Operators relying on non-deterministic exit codes (0 on success,
  traceback on error) see new exit 1 on DB/config errors.** → Mitigation: the
  old behavior was a latent bug (tracebacks are not scriptable); exit 1 on
  runtime failure is the POSIX convention and matches `init`. The success path
  (exit 0) is unchanged.
- **[Risk] `--cloud`/`--no-cloud` mutex surprises users who expect subset
  semantics like `--enabled`/`--disabled`.** → Mitigation: `--help` documents
  both flags; the rationale (value vs absence cannot union into default) is in
  the design. The mutex group is the only one in the parser, so the surprise
  is localized.
- **[Risk] The `occupied_by` single-object shape in JSON locks in the
  one-task-per-node invariant; a future domain change to allow >1 would break
  the JSON shape.** → Mitigation: that breakage would be a deliberate domain
  change requiring its own proposal (table multi-row + JSON array together);
  this change encodes the current invariant faithfully rather than
  speculative future-proofing.
- **[Trade-off] Temporary asymmetry: 2 of 6 CLI commands in `entrypoints/`,
  4 in `infra/cli/`.** → Accepted: `init` (bootstrap) and `show_nodes`
  (execution-query, first of the execution commands) are relocated; the other
  4 execution commands may follow in separate changes. This change establishes
  the execution-command relocation pattern without prejudging the rest.
- **[Trade-off] In-module function split (D2) instead of a use case.** →
  Accepted: a `query_nodes` use case would have one caller and no prospect of
  a second; the in-module split achieves logic/display separation at the
  right granularity. The contract records the promotion condition so a future
  second consumer triggers extraction rather than duplication.

## Migration Plan

**Deploy:**
1. Install the new package version (contains
   `yascheduler/entrypoints/cli/show_nodes.py`; no longer contains
   `yascheduler/infra/cli/show_nodes.py`).
2. `yanodes` console_script now resolves to
   `yascheduler.entrypoints.cli.show_nodes:show_nodes` (via updated
   `pyproject.toml`). Re-install the package (`uv sync` or `pip install -e .`)
   to refresh the entrypoint.
3. No DB migration, no config change, no service file change needed.
   `yanodes` is read-only.

**Rollback:**
1. Revert to the previous package version (restores
   `yascheduler/infra/cli/show_nodes.py`, restores `pyproject.toml` line 50,
   restores the `infra/cli/__init__.py` re-export).
2. Re-install the package to refresh the entrypoint.
3. No data or state to clean up — `yanodes` is read-only.

**Open Questions:** None. All decisions captured in D1–D14.