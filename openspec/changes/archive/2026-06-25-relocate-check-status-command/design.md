## Context

`yastatus` is the CLI command that queries task status, optionally displays
remote machine output (tail of `OUTPUT`), and optionally downloads + parses a
CRYSTAL convergence snippet. It lives at `yascheduler/infra/cli/check_status.py`
(270 lines) and is registered as the `yastatus` `console_script` in
`pyproject.toml`. The archived `add-entrypoints-layer` change created
`yascheduler/entrypoints/` as the outermost hexagonal layer and listed
`infra/cli/` as deferred-for-migration; `relocate-init-command`,
`relocate-show-nodes-command`, and `relocate-submit-command` then moved `init`,
`show_nodes`, and `submit` into `yascheduler/entrypoints/cli/` as the first
three residents, establishing the relocation pattern. `check_status` is the
fourth resident — the execution-query counterpart that additionally reads remote
machine output.

Current `check_status()` (key shape):

```python
@to_sync
async def check_status() -> None:
    args = _parse_status_args()
    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)
    local_parsing_ready = bool(args.convergence)
    local_calc_snippet = None
    async with deps.uow_factory() as uow:           # ← OUTER UoW (held during SSH!)
        if args.jobs:
            tasks = await uow.tasks.list_by_jobs(job_ids=args.jobs)
        else:
            tasks = await uow.tasks.list_by_status({RUNNING, TO_DO})
        if args.view:
            local_calc_snippet = await _print_status_view(tasks, config, ...)  # ← SSH inside
        elif args.info:
            _print_status_info(tasks)
        else:
            _print_status_default(tasks)
    if local_calc_snippet and os.path.exists(local_calc_snippet):
        os.unlink(local_calc_snippet)
```

Current `_print_status_view()` opens its OWN UoW for the nodes lookup, closes
it, then performs the long-lived SSH work — but the OUTER UoW from
`check_status` is still open throughout, holding two DB connections with one
idle. It also picks the SSH username via the buggy loop
`for c in config.clouds: ssh_user = c.username` (takes the last cloud, never
uses `node.username`/`node.port`/jump-host).

The AiiDA scheduler plugin (`entrypoints/aiida_plugin.py`) does NOT import
`check_status`. It executes `yastatus [--jobs ...]` over SSH transport and
parses stdout via `_parse_joblist_output`:

```python
job_list = [job.split() for job in stdout.split("\n") if job]
for job_id, status in job_list:                           # exactly 2 elements
    job.job_state = _MAP_STATUS_YASCHEDULER[status]       # ∈ {TO_DO, RUNNING, DONE}
```

`TaskStatus` is a closed `IntEnum {TO_DO=0, RUNNING=1, DONE=2}`
(`domain/model.py:60-65`); all "failures" are marked `DONE` + `context.error`.
So `_MAP_STATUS_YASCHEDULER` cannot KeyError. The default renderer output MUST
stay `<task_id><whitespace><STATUS_NAME>` byte-for-byte; the plugin's contract
is the #1 constraint.

`schema-migrations` (in progress) is adding a versioned migration system; it
touches no read path `yastatus` uses, so the two changes do not conflict.

## Goals / Non-Goals

**Goals:**
- Move `check_status.py` from `infra/cli/` to `entrypoints/cli/` as the fourth
  resident, mirroring the three precedents (real move, no compat shim, layer
  direction preserved).
- Reimplement `check_status()` with `argparse` exposing `prog="yastatus"`, the
  `argv: list[str] | None = None` testability parameter, and the
  `mutually_exclusive_group` flag matrix with `-o` requires `-v`.
- Define and enforce the `0`/`1`/`2` exit-code contract (mirrors `init`,
  `show_nodes`, `submit`).
- Fix the connection-params bug (`B-full`): `_resolve_conn_params(node, config)`
  mirrors `orchestrator._connect_machine_consumer:209-214`.
- Fix the DB-connection-lifecycle defect (`Q-uow`): separate query/render
  phases; no outer UoW held during SSH.
- Add `--json` output mode as the second instance of the machine-readable CLI
  convention (9 raw-value fields).
- Preserve the AiiDA stdout compatibility contract exactly: default renderer
  prints `<task_id>   <STATUS>`; the plugin is unchanged.
- Preserve every public contract: `yastatus` command name, default output,
  `--jobs` semantics, `console_script` wiring, layer-direction compliance, no
  new dependencies.

**Non-Goals:**
- Move the other 2 CLI commands (`manage_node`, `daemonize`) — they stay in
  `infra/cli/` for follow-up changes.
- Extract a `query_status` or `view_status` use case into
  `yascheduler/application/` — YAGNI; no second consumer exists.
- Add a public `SSHMachineGateway.run_command(ip, cmd)` — the
  `_get_machine_state` private-method access FIXME is carried forward with
  updated framing; cross-cutting follow-up.
- Cover the `-o`/`pycrystal` convergence path with unit tests in this change —
  scientific parse + optional deps is a separate concern;
  `_parse_convergence` and `_download_convergence_snippet` move as-is.
- Touch `di.py`, `application/`, `domain/`, `infra/persistence/`,
  `infra/ssh/gateway.py`, `entrypoints/aiida_plugin.py` — unchanged.

## Decisions

### D1 — Real implementation at the new path, no compat shim

**Choice:** Move the real implementation to
`yascheduler/entrypoints/cli/check_status.py`; delete
`yascheduler/infra/cli/check_status.py`; drop
`from .check_status import check_status` and `"check_status"` from `__all__` in
`yascheduler/infra/cli/__init__.py`; drop the `check_status` line from its
`MODULE_MAP`; update `pyproject.toml` to
`yastatus = "yascheduler.entrypoints.cli.check_status:check_status"`.

**Rationale:** A compat shim at `infra/cli/check_status.py` re-exporting from
`entrypoints/cli/check_status.py` would create an `infra → entrypoints` import,
inverting the layer direction enforced by `import-linter`'s `layers` contract.
The three precedents established that entrypoint residents are invoked by path
/ console_script, not re-exported from `infra/`. No deep import of
`from yascheduler.infra.cli.check_status import check_status` exists in
production code (verified by grep); the only consumers are
`yascheduler/infra/cli/__init__.py` (re-export), `pyproject.toml`
(console_script target), and two test files — all updated in this change.

**Alternative rejected:** One-line shim re-exporting from the new location.
Rejected: layer violation; would need an `ignore_imports` entry, adding debt
to preserve a path no production code uses. (Mirrors `relocate-submit-command`
D1.)

### D2 — In-module function splitting; no use-case extraction

**Choice:** Split the logic into private pure functions inside
`entrypoints/cli/check_status.py`: `_parse_status_args(argv)`,
`_query_tasks(uow, args)` (the conditional query phase),
`_render_default(tasks)` (AiiDA contract, moved as-is), `_render_info(tasks)`
(moved as-is), `_render_json(tasks, nodes_by_ip)`,
`_render_view(tasks, nodes_by_ip, config, fetch_convergence, deps)`,
`_resolve_conn_params(node, config)` (new bugfix helper),
`_display_remote_output(...)`, `_download_convergence_snippet(...)` (moved
as-is), `_parse_convergence(path)` (moved as-is, deferred imports preserved).
Do NOT extract a use case into `yascheduler/application/`.

**Rationale:** The `query_tasks` use case was extracted (in the archived
`client-query-uow` change) because the AiiDA client was a real second consumer
of the same query. No second consumer of the "list tasks by status / by ids +
optional remote tail + optional convergence parse" flow exists: the AiiDA
client queries via `queue_get_tasks_async` (a different repo method); the
daemon does not query status. The CLI-specific shaping (argparse, renderers,
SSH tail, pycrystal parse) is input/output shaping, not a business rule.
Extracting a use case now would create a module with a single caller and no
prospect of a second — YAGNI. The in-module split achieves the FIXME's intent
(logic-vs-IO separation) at the appropriate granularity (functions, not
layers). The `_render_view` contract records that promotion to
`application/view_status.py` awaits a second consumer.

**Alternative rejected:** Create `yascheduler/application/view_status.py`
mirroring `submit_task.py`. Rejected: no second consumer; CLI-only shaping is
not business logic; produces a one-caller use case. (Mirrors
`relocate-submit-command` D2.)

### D3 — Argparse flag matrix: mutex group + `-o` dependency body-check

**Choice:**
- `argparse.ArgumentParser(prog="yastatus", description="Show status of tasks")`.
- `-j/--jobs` (`nargs="*"`, `default=None`): orthogonal filter; composes with
  any renderer.
- `mutex = parser.add_mutually_exclusive_group()` with `-v/--view`,
  `-i/--info`, `--json` (each `action="store_true"`). At most one renderer is
  selected; none means the default AiiDA-compatible renderer.
- `-o/--convergence` (`action="store_true"`): NOT in the mutex group (it
  modifies `-v`, so `-o -v` must remain valid). After `parse_args`, a
  body-check rejects `-o` without `-v`: `if args.convergence and not
  args.view: parser.error("--convergence requires --view")`. `parser.error`
  exits 2 with a clean argparse message.
- `argv: list[str] | None = None` passed to `parse_args`.

**Rationale:** The current parser uses `nargs="?", type=bool, const=True` for
the flags, which is non-idiomatic (and lets `-v -i` both be set, with the
`if/elif` chain silently picking `-v`). `store_true` is the standard
boolean-flag form, matching `init`, `show_nodes`, and `submit`. The mutex group
makes the "pick exactly one renderer" rule explicit and enforces it at parse
time (exit 2) rather than via silent if/elif priority. `-o` cannot be in the
mutex group because it composes *with* `-v` (convergence requires the view
renderer); the body-check captures the dependency rule that argparse cannot
express natively. `parser.error(...)` (vs raising manually) keeps the error
message shape consistent with other argparse errors.

**Order of checks:** argparse catches mutex violations first (during
`parse_args`); the `-o`-requires-`-v` body-check runs second. Both yield exit
2.

**Behavior changes (deliberate, AiiDA-compatible):**
- `-v -i` previously ran the `-v` branch (silent priority); now exits 2 (mutex
  violation).
- `-o` without `-v` was silently ignored; now exits 2 with `--convergence
  requires --view`.
- `-v`/`-i`/`--json`/`-o` switch from `nargs="?", type=bool, const=True` to
  `action="store_true"` (no observable change for the flag's truthiness, but
  drops the weird `yastatus -v True` parsing shape).

None of these affect the default renderer (no flags), which is the only path
the AiiDA plugin uses.

**Alternative rejected (a):** Put `-o` in the mutex group. Rejected: `-o -v`
must work (convergence needs the view renderer); mutex forbids co-occurrence.
**Alternative rejected (b):** Make `-o` imply `-v` automatically. Rejected:
changes the semantics from "requires" to "implies" silently; the
`help="needs -v option"` text and existing intent is "requires". Exit 2 is
more honest.
**Alternative rejected (c):** Keep the `nargs="?", type=bool, const=True`
shape. Rejected: non-idiomatic, harder to test, lets `-v -i` both be true.

### D4 — Exit codes `0` / `1` / `2`

**Choice:**
- `0` on success: the function returns normally after rendering (default,
  `-i`, `--json`, or `-v`); the process exits 0.
- `1` on runtime failure: DB error, config parse error, SSH connection
  failure, SFTP failure, convergence-parse failure, or any unexpected
  exception caught at the top level (`except Exception as e:
  print(f"Error: {e}", file=sys.stderr); sys.exit(1)`).
- `2` on argparse error: argparse default (unknown flag, mutex violation), or
  `parser.error("--convergence requires --view")`.

**Rationale:** Mirrors the three precedent D3/D5/D4 decisions exactly. `2` is
the argparse default shell scripts expect for usage errors; `1` for runtime
failures is the POSIX convention. The current code has no exit-code contract
(exceptions propagate as tracebacks); this contract makes failures visible,
scriptable, and AiiDA-compatible (the plugin's `_parse_joblist_output` ignores
`retval` and parses stdout regardless, so a non-zero exit on the default path
is tolerated — but a clean exit 0 on success is still the contract).

`check_status` does NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits 0. Only the failure path calls
`sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/`sys.exit(2)`
internally before reaching the body. (Same as `submit` and `show_nodes`.)

`@to_sync` propagates `SystemExit` correctly: `SystemExit` is a
`BaseException`, and `asyncio.run` (used inside `to_sync`) does not wrap it as
an `Exception`. Verified at `yascheduler/shared/async_utils.py:41-63`.

**Alternative rejected:** Use `sysexits.h` codes. Rejected: over-engineering;
`0/1/2` is the convention every other yascheduler CLI command follows.

### D5 — AiiDA default-output compatibility contract (the distinguishing constraint)

**Choice:** The default renderer (`_render_default`, used when none of
`-v`/`-i`/`--json` is given) MUST emit exactly one line per task in the form
`<task_id><whitespace><STATUS_NAME>` where `STATUS_NAME ∈ {TO_DO, RUNNING,
DONE}`. This is the format the AiiDA scheduler plugin's
`_parse_joblist_output` parses via `for job_id, status in job.split()`. The
default renderer is moved as-is from `_print_status_default`:

```python
def _render_default(tasks: list[Task]) -> None:
    for task in tasks:
        print(f"{task.task_id}   {task.status.name}")
```

**Rationale:** The AiiDA scheduler plugin
(`entrypoints/aiida_plugin.py:_parse_joblist_output`) does:
```python
job_list = [job.split() for job in stdout.split("\n") if job]
for job_id, status in job_list:
    job.job_state = _MAP_STATUS_YASCHEDULER[status]
```
`_get_joblist_command` returns `yastatus` or `yastatus --jobs <ids>`, so AiiDA
executes `yastatus` as a subprocess over SSH transport and parses its stdout.
The tuple unpack `for job_id, status in job_list` requires exactly 2 elements
per line (a 3rd column would raise `ValueError`); `_MAP_STATUS_YASCHEDULER`
keys are `{TO_DO, RUNNING, DONE}`. The current `print(f"{task.task_id}
   {task.status.name}")` produces `<int>   <STATUS_NAME>` (3 spaces) —
`.split()` handles any whitespace run, so the exact spacing is not contractual,
but the 2-element shape and the status-name set are. This is the key
constraint distinguishing `check_status` from `show_nodes` (which had no
machine consumer and could freely change format). For `check_status`, the
default format is fixed by an external consumer.

The `-v`, `-i`, `-o`, and `--json` modes are NOT used by the AiiDA plugin (it
only invokes the default mode, optionally with `--jobs`); their output is free
to change. `--json` is therefore safe to add (it is opt-in; AiiDA never passes
it).

**Default filter unchanged:** `yastatus` with no `-j` queries
`list_by_status({RUNNING, TO_DO})` — DONE is excluded by default. The AiiDA
plugin relies on this (it polls active jobs, not history). With `-j`, the
plugin queries specific job IDs via `list_by_jobs(job_ids)`, which returns
tasks of any status; because `TaskStatus` is a closed enum, all returned
statuses are valid AiiDA states.

**Regression test (see D9):** a golden test asserts the default renderer's
output parses via the plugin's exact logic.

**Alternative rejected:** Decorate the default output (e.g. add a header).
Rejected: would break the plugin's `for job_id, status in job.split()`
unpacking. (Mirrors `relocate-submit-command` D5.)

### D6 — `--json` output: 9 raw-value fields, second instance of the convention

**Choice:** When `--json` is given, `_render_json(tasks, nodes_by_ip)` emits
`json.dumps(list_of_objects)` (one object per task, in the order returned by
the query). Each object has exactly these 9 fields with raw domain values (NO
display transformations):

| field           | type           | source                              | null when                              |
| --------------- | -------------- | ----------------------------------- | -------------------------------------- |
| `task_id`       | int            | `task.task_id`                      | never                                  |
| `status`        | str (enum name)| `task.status.name`                  | never                                  |
| `label`         | str            | `task.label`                        | never                                  |
| `allocated_ip`  | str \| null    | `task.allocated_ip`                 | no allocated IP (TO_DO)                |
| `port`          | int \| null    | `node.port` (via nodes_by_ip)       | no allocated IP (TO_DO)                |
| `cloud`         | str \| null    | `node.cloud` (via nodes_by_ip)      | no allocated IP / static node          |
| `engine`        | str            | `task.context.engine`               | never                                  |
| `local_folder`  | str \| null    | `task.context.local_folder`         | context has no local_folder            |
| `remote_folder` | str \| null    | `task.context.remote_folder`        | context has no remote_folder           |

`nodes_by_ip` is the result of `uow.nodes.get_by_ips([t.allocated_ip for t in
tasks if t.allocated_ip])`; for tasks without an allocated IP (typically
`TO_DO`), `port`/`cloud`/`allocated_ip` are `null`. `engine` always comes from
`task.context.engine` (a required field on `TaskContext`, never null).
`local_folder`/`remote_folder` are `str | None` on `TaskContext`
(`domain/model.py:98-103`).

**Rationale:** `yanodes --json` (from `relocate-show-nodes-command`) established
the convention: query-oriented CLI commands emit raw-domain-value JSON (no
display tokens like `-`/`MAX`/`yes`). `yastatus --json` is the second instance.
The 9 fields cover everything a script consumer needs: identity (`task_id`),
state (`status`), display (`label`), placement (`allocated_ip`, `port`,
`cloud`), and engine context (`engine`, `local_folder`, `remote_folder`). The
null semantics for `TO_DO` are natural (no node allocated yet) and consistent
with how `yanodes --json` renders missing data. The existing
`--json` convention requirement in `cli-commands/spec.md` is updated to note
`yastatus` as the second instance (forward-looking convention, now with two
instances).

`--json` is in the mutex group with `-v`/`-i` (D3), so `--json -v` is an error.
Convergence (`-o`) is not part of `--json` (mixing machine-readable JSON with
ephemeral scientific output is bad design; `--json` and `-o` are mutually
exclusive via the `-v` mutex group since `-o` requires `-v`).

**Alternative rejected (a):** Include convergence info as a `convergence`
field in `--json`. Rejected: convergence requires SSH + SFTP download +
`pycrystal` parse (expensive, optional dep); mixing it into JSON inflates the
schema and couples the cheap DB query to a slow SSH path.
**Alternative rejected (b):** Fewer fields (just `task_id` + `status`).
Rejected: a script consumer cannot act on identity+state alone (needs
`allocated_ip` to know where it runs, `engine` to know what it runs); the 9
fields match what `yanodes --json` exposes per its domain.

### D7 — `_resolve_conn_params(node, config)` mirrors orchestrator (B-full bugfix)

**Choice:** Introduce a private pure function
`_resolve_conn_params(node, config) -> ConnParams` that returns the four SSH
connection parameters for a node, mirroring
`orchestrator._connect_machine_consumer:209-214` exactly:

```python
@dataclass(frozen=True)
class _ConnParams:
    username: str
    port: int
    jump_host: str | None
    jump_username: str | None

def _resolve_conn_params(node: Node, config: Config) -> _ConnParams:
    jump_host = config.remote.jump_host
    jump_username = config.remote.jump_username
    for cloud in config.clouds:
        if cloud.prefix == node.cloud:
            if cloud.jump_host and cloud.jump_username:
                jump_host, jump_username = cloud.jump_host, cloud.jump_username
            break
    return _ConnParams(
        username=node.username,
        port=node.port,
        jump_host=jump_host,
        jump_username=jump_username,
    )
```

`_display_remote_output` then passes all four to `gateway.connect(...)` (the
gateway's `connect` signature already accepts `port`, `jump_host`,
`jump_username` — verified at `infra/ssh/gateway.py:225-238`).

**Rationale:** The current code picks `ssh_user` via
`for c in config.clouds: ssh_user = c.username` — it takes the LAST cloud's
username (regardless of which cloud owns the node), ignores `node.username`
(which `orchestrator` uses as the primary), ignores `node.port` (always
connecting on 22), and never passes `jump_host`/`jump_username` (so cloud
nodes behind a jump host cannot be reached). The orchestrator already solves
this correctly at `_connect_machine_consumer:209-214`; mirroring it makes
`yastatus -v` reach cloud nodes the same way the daemon does. The helper is
duplicated rather than shared because its shape differs (orchestrator connects
inline within a larger method; `check_status` returns a params object for the
gateway call) and no third consumer exists (YAGNI). The `_resolve_conn_params`
contract records that promotion to a shared helper awaits a third consumer.

`Node.username: str = "root"` (`domain/model.py:369`) and `Node.port: int = 22`
(`domain/model.py:370`) are always set (never `None`), so `_ConnParams` has no
null fields for username/port.

**Behavior change:** `yastatus -v` on a cloud node behind a jump host now
connects (previously failed silently with the wrong username and no jump
host). On static nodes (no cloud), behavior is unchanged (uses
`node.username`, `node.port`, `config.remote.jump_host`). This is an observable
change in the `-v` path only — AiiDA never uses `-v`.

**Alternative rejected (a):** B-min (only fix `ssh_user = node.username or
config.remote.username`). Rejected: leaves `port`/`jump_host`/`jump_username`
broken; masks the bug instead of fixing it.
**Alternative rejected (b):** Extract a shared helper used by both orchestrator
and check_status. Rejected: the shapes differ; refactor of orchestrator is out
of scope for a relocation change; YAGNI without a third consumer.

### D8 — Query/render separation (Q-uow bugfix)

**Choice:** Restructure `check_status()` so that ALL DB reads happen in one
short UoW that is CLOSED before any SSH work begins. The renderers receive
already-fetched data:

```python
@to_sync
async def check_status(argv: list[str] | None = None) -> None:
    try:
        args = _parse_status_args(argv)
        config = Config.from_config_parser(CONFIG_FILE)
        deps = make_cli_deps(config)
        # QUERY PHASE — one short UoW
        async with deps.uow_factory() as uow:
            tasks = await _query_tasks(uow, args)
            nodes_by_ip: dict[str, Node] = {}
            if args.view or args.json:
                ips = [t.allocated_ip for t in tasks if t.allocated_ip]
                nodes_by_ip = await uow.nodes.get_by_ips(ips) if ips else {}
        # UoW closed — no DB connection held during SSH
        # RENDER PHASE
        if args.view:
            await _render_view(tasks, nodes_by_ip, config, bool(args.convergence), deps)
        elif args.info:
            _render_info(tasks)
        elif args.json:
            print(_render_json(tasks, nodes_by_ip))
        else:
            _render_default(tasks)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
```

`_render_view` no longer opens its own UoW for nodes; it receives
`nodes_by_ip` as an argument and `deps` only if it needs to re-query (it does
not — the nodes lookup is in the query phase). `make_cli_deps` is called once.

`_query_tasks(uow, args)` is the conditional query:
- `args.jobs` → `uow.tasks.list_by_jobs(job_ids=args.jobs)`
- else → `uow.tasks.list_by_status({RUNNING, TO_DO})`

**Rationale:** The current structure opens an outer UoW in `check_status`, then
calls `_print_status_view` inside the `async with` block. `_print_status_view`
opens its OWN UoW for the nodes lookup, closes it, then performs long-lived SSH
work (connect, tail, SFTP download, pycrystal parse) — all while the OUTER UoW
is still open, holding an idle DB connection for the duration of the SSH
operations. This is a real connection-pool drain under concurrent `yastatus -v`
invocations. Separating the phases means the DB connection is held only for
the two short `SELECT`s, then released before any network I/O. The nodes
lookup is conditional (`args.view or args.json`) so the default AiiDA-polled
path does not pay for a spurious `get_by_ips` query.

**Behavior change:** None observable — same tasks/nodes fetched, same output.
Only the connection lifecycle changes (correct). `make_cli_deps` is called
once (was twice). `_render_view`'s signature changes (private API, not a
public contract).

**Alternative rejected:** Keep the outer UoW open and just remove the inner
one. Rejected: the outer UoW is the problem (held during SSH); the fix is to
close it before SSH, which requires the query/render split.

### D9 — AiiDA-contract regression golden test

**Choice:** Add a unit test in `tests/unit/test_cli_check_status.py` that
asserts the default renderer's output parses via the EXACT logic the AiiDA
plugin uses:

```python
def test_default_output_parses_like_aiida_plugin(self, ...):
    # Render tasks of all three statuses through the default renderer.
    tasks = [make_task(task_id=1, status=TO_DO), make_task(2, RUNNING), make_task(3, DONE)]
    _run_default_renderer(tasks)  # captures stdout
    # Parse stdout with the plugin's exact logic.
    job_list = [job.split() for job in captured_stdout.split("\n") if job]
    parsed = {}
    for job_id, status in job_list:              # 2-element unpack must hold
        parsed[job_id] = status
    assert set(parsed.values()) <= {"TO_DO", "RUNNING", "DONE"}
    assert parsed == {"1": "TO_DO", "2": "RUNNING", "3": "DONE"}
```

**Rationale:** The whole point of preserving the default renderer is AiiDA
compatibility. A regression test that runs the plugin's parser shape (not the
plugin itself — it has heavy deps) guards against accidental decoration of
the default output in future refactors. The test asserts (a) exactly 2
elements per line (the `for job_id, status in ...` unpack), (b) the status
set is within `{TO_DO, RUNNING, DONE}`, and (c) the mapping is correct.

**Alternative rejected:** Spin up the actual AiiDA plugin in a test.
Rejected: AiiDA is a heavy optional dependency; the parser logic is trivial
enough to mirror inline. The golden test captures the contract without the
dep.

### D10 — `tempfile` for the convergence snippet + `try/finally` cleanup

**Choice:** Replace the fixed-name
`Path(config.local.data_dir, "local_calc_snippet.tmp")` with
`tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")` (or
`tempfile.mkstemp(suffix=".tmp")`) and clean it up in a `try/finally` block
around the render phase, so the file is removed even when `_render_view`
raises. The filename is passed down to `_render_view` /
`_download_convergence_snippet` as before.

**Rationale:** The fixed name collides on concurrent `yastatus -v -o`
invocations (two processes overwrite each other's snippet). The current
cleanup at the end of `check_status` is skipped if `_render_view` raises (the
`async with` block exits via exception, the `if local_calc_snippet and
os.path.exists(...)` line is never reached). `tempfile` gives a unique name;
`try/finally` guarantees cleanup on the exception path of the `1` exit-code
contract (D4).

**Alternative rejected:** Keep the fixed name, accept the collision.
Rejected: latent bug under concurrent invocations; `tempfile` is stdlib and
trivial.

### D11 — Fresh GRACE-lite markup; carry the `_get_machine_state` FIXME, drop the other

**Choice:** The new `entrypoints/cli/check_status.py` gets fresh
`MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`, function contracts (for
`check_status` and the private helpers as appropriate), and block anchors
appropriate to the reimplemented logic. Do NOT carry the
`# FIXME: split adapter and application layer` comment (stale framing at
`entrypoints/`; the in-module split resolves the concern — mirrors
`relocate-submit-command` D10). DO carry the `gateway._get_machine_state(ip)`
FIXME with updated framing:

```python
# FIXME: _display_remote_output reaches into gateway._get_machine_state(ip)
# to bridge to run_full(state.machine, ...). A public
# SSHMachineGateway.run_command(ip, cmd) should replace this; tracked for a
# cross-cutting follow-up (not this relocation).
```

**Rationale:** GRACE-lite requires governed files to carry markup; the
reimplementation has different control flow (argparse dispatch, mutex,
query/render split, `_resolve_conn_params`, `_render_json`) than the original,
so the markup is written for the new shape. The "split adapter and application
layer" FIXME is resolved at the function granularity (D2) and its framing is
stale at `entrypoints/`. The `_get_machine_state` FIXME is a genuine
cross-cutting concern (the SSH gateway lacks a public run-command API) that
this relocation does not address; carrying it forward with updated framing
preserves the signal without blocking the move.

**Alternative rejected:** Drop both FIXMEs. Rejected: `_get_machine_state` is
a real debt; dropping it silently loses the signal.

### D12 — `entrypoints/cli/__init__.py` facade declarative edit

**Choice:** Declarative PURPOSE edit to
`yascheduler/entrypoints/cli/__init__.py` to add `check_status`. After
`relocate-submit-command`, the facade reads "Init, show_nodes, and submit CLI
entry point subpackage facade." This change generalizes it to "Init,
show_nodes, submit, and check_status CLI entry point subpackage facade." (or a
generic equivalent). The facade's content (no re-exports) does not change —
`check_status` is invoked by console_script, not imported across layers.

**Rationale:** Mirrors `relocate-submit-command` D11. The facade exists to be
the subpackage boundary; `check_status` is also invoked by console_script, so
no re-export is added. The PURPOSE wording edit is declarative (generalizes
the description to cover the fourth resident), not a decision-level change.

**Alternative rejected:** Leave the PURPOSE listing `init, show_nodes, submit`
only. Rejected: stale wording after the fourth resident moves in; declarative
generalization keeps the contract accurate.

### D13 — Knowledge-graph amendments: precise relation edits

**Choice:**
- Add `<M-ENTRYPOINTS-CLI-CHECK-STATUS NAME="yastatus CLI entry point"
  TYPE="ENTRY_POINT" STATUS="implemented">` with
  `<path>yascheduler/entrypoints/cli/check_status.py</path>`,
  `<depends>M-CONFIG, M-DI, M-SSH-GATEWAY, M-DOMAIN-MODEL, M-SHARED,
  M-APPLICATION-UOW</depends>`, and annotations for `fn-check_status` (and
  private helpers as appropriate).
- `M-CLI-COMMANDS`: delete `<fn-check_status PURPOSE="..." />`.
- New CrossLinks:
  - `<CrossLink from="M-ENTRYPOINTS-CLI-CHECK-STATUS" to="M-DI"
    relation="uses make_cli_deps for CLI status" />`
  - `<CrossLink from="M-ENTRYPOINTS-CLI-CHECK-STATUS" to="M-APPLICATION-UOW"
    relation="reads tasks and nodes via UoW" />`
  - `<CrossLink from="M-ENTRYPOINTS-CLI-CHECK-STATUS" to="M-SSH-GATEWAY"
    relation="verbose mode connects, tails OUTPUT, downloads convergence" />`
- Amend the existing
  `<CrossLink from="M-CLI-COMMANDS" to="M-DI" relation="uses make_daemon for
  daemon entry" />` to `<CrossLink from="M-CLI-COMMANDS" to="M-DI"
  relation="uses make_cli_deps for CLI node management; make_daemon for daemon
  entry" />`. **Why amend (not drop-and-readd):** `manage_node` STAYS in
  `infra/cli/` and imports `make_cli_deps` (verified at
  `infra/cli/manage_node.py:29`); the current relation string omits this
  clause, so this change makes it explicit. `check_status` does NOT appear
  (it moved to `M-ENTRYPOINTS-CLI-CHECK-STATUS`, which has its own edge).
- Amend the existing
  `<CrossLink from="M-CLI-COMMANDS" to="M-DOMAIN-MODEL" relation="imports Node,
  Task, TaskStatus for CLI status and node management" />` to
  `<CrossLink from="M-CLI-COMMANDS" to="M-DOMAIN-MODEL" relation="imports Node,
  TaskStatus for CLI node management" />`. **Why:** `check_status` was the
  `Task` + status importer and has moved; `manage_node` keeps `Node` +
  `TaskStatus` (verified at `infra/cli/manage_node.py:30`: `from
  yascheduler.domain import Node, TaskStatus`) but does NOT import `Task`.
- Do NOT touch any `DF-*` element (there is no `DF-STATUS` or `DF-QUERY`; the
  only CLI-related DF is `DF-DAEMON-START`, unaffected).

**Rationale:** Mirrors `relocate-submit-command` D12 (amend relation strings
rather than drop-and-readd, to preserve edge identity and keep clauses for
modules that stay). The two amendments are necessary because the current
relation strings were written when all three commands (`check_status`,
`manage_node`, `daemonize`) lived in `M-CLI-COMMANDS`; moving `check_status`
out requires updating both edges to reflect what `manage_node` and `daemonize`
still need.

**Alternative rejected:** Drop both `M-CLI-COMMANDS → ...` edges and re-add
them with new relation strings. Rejected: amending preserves edge identity
and produces a smaller diff.

## Risks / Trade-offs

- **[Risk] `-v -i` previously ran silently; now exits 2.** → Mitigation: no
  production caller is known (the AiiDA plugin uses the default mode only);
  the mutex violation gives a clear argparse error. Verified by grep — no
  script invokes `yastatus -v -i`.
- **[Risk] `-o` without `-v` previously silently ignored; now exits 2.** →
  Mitigation: the `help="needs -v option"` text already documented the
  requirement; the body-check enforces what the help promised. No production
  caller is known.
- **[Risk] `yastatus -v` on a jump-host cloud node now connects (previously
  failed).** → Mitigation: this is a bugfix, not a regression; the new
  behavior matches `orchestrator._connect_machine_consumer`. Operators who
  worked around the bug (e.g. by always using `config.remote.username`) see
  the correct username per node instead.
- **[Risk] Operators relying on the traceback for `-v` debugging lose it.** →
  Mitigation: the `except Exception as e: print(f"Error: {e}",
  file=sys.stderr); sys.exit(1)` path prints the exception message (not the
  full traceback). For SSH/SFTP failures, the message is the
  `MachineConnectionError` text. Setting `LOGLEVEL=DEBUG` or running under a
  debugger restores the full traceback.
- **[Trade-off] Temporary asymmetry: 4 of 6 CLI commands in `entrypoints/`,
  2 in `infra/cli/`.** → Accepted: `init`, `show_nodes`, `submit`,
  `check_status` are relocated; `manage_node` and `daemonize` may follow in
  separate changes. This change completes the relocation pattern for the four
  commands with the clearest entrypoint characterization.
- **[Trade-off] `_resolve_conn_params` duplicates orchestrator logic.** →
  Accepted: the shapes differ (inline connect vs. params object); a shared
  helper would require refactoring orchestrator (out of scope) and has no
  third consumer (YAGNI). The contract records the promotion condition.
- **[Trade-off] `-o`/convergence path is not unit-tested in this change.** →
  Accepted: `pycrystal`/`numpy` are optional deps with deferred imports; the
  scientific parse is a separate concern from the relocation. The functions
  move as-is (behavior preserved); follow-up tests can target them in
  isolation.

## Migration Plan

**Deploy:**
1. Install the new package version (contains
   `yascheduler/entrypoints/cli/check_status.py`; no longer contains
   `yascheduler/infra/cli/check_status.py`).
2. `yastatus` console_script now resolves to
   `yascheduler.entrypoints.cli.check_status:check_status` (via updated
   `pyproject.toml`). Re-install the package (`uv sync` or `pip install -e .`)
   to refresh the entrypoint.
3. No DB migration, no config change, no service file change. `yastatus` is a
   read-only command; no schema interaction beyond `SELECT`.

**Rollback:**
1. Revert to the previous package version (restores
   `yascheduler/infra/cli/check_status.py`, restores `pyproject.toml`,
   restores the `infra/cli/__init__.py` re-export).
2. Re-install the package to refresh the entrypoint.
3. No data or state to clean up — `yastatus` performs read-only queries.

**Open Questions:** None. All decisions captured in D1–D13.
