## Why

`yastatus` lives at `yascheduler/infra/cli/check_status.py` but is an entrypoint
(a CLI command invoked by `console_script`), not an infra adapter. The archived
`add-entrypoints-layer` change listed `infra/cli/` as deferred-for-migration;
`relocate-init-command`, `relocate-show-nodes-command`, and
`relocate-submit-command` then moved `init`, `show_nodes`, and `submit` into
`yascheduler/entrypoints/cli/` as the first three residents, establishing the
`entrypoints/cli/` home and the relocation pattern (real move, no compat shim,
layer direction `entrypoints → infra` preserved, fresh GRACE-lite markup,
argparse-based reimplemented logic, `0`/`1`/`2` exit-code contract).
`check_status` is the fourth resident — the execution-query counterpart that
additionally reads remote machine output — and completes the migration of the
non-daemon execution commands.

The current `check_status()` also has real issues worth fixing in the same move:
no `prog="yastatus"` (`--help`/error screens show the console_script path, not
the command name), no `argv` testability parameter (tests must
`patch("sys.argv", ...)`, a fragile global-state coupling), no exit-code
contract (exceptions propagate as tracebacks), a latent `ssh_user` bug (the loop
`for c in config.clouds: ssh_user = c.username` takes the *last* cloud's
username rather than the matching one, and never passes `node.port`,
`jump_host`, or `jump_username` — so `yastatus -v` is functionally broken on
cloud nodes behind a jump host), a DB-connection-lifecycle defect (the outer
`async with deps.uow_factory()` block stays open while `_print_status_view`
performs long-lived SSH operations, holding two DB connections at once with one
idle), and a silent-acceptance bug (`-o/--convergence` without `-v` is silently
ignored instead of erroring). The move is the moment to bring it to the modern
standard `init`, `show_nodes`, and `submit` set (`prog`, `argv`, `0`/`1`/`2`
exit codes, fresh GRACE-lite markup) while preserving the AiiDA scheduler
plugin's stdout contract exactly.

## What Changes

- Move `yascheduler/infra/cli/check_status.py` →
  `yascheduler/entrypoints/cli/check_status.py` (real implementation, not a
  shim). This is the fourth resident of `entrypoints/cli/`, mirroring `init.py`
  (from `relocate-init-command`), `show_nodes.py` (from
  `relocate-show-nodes-command`), and `submit.py` (from
  `relocate-submit-command`). The remaining 2 execution commands
  (`manage_node`, `daemonize`) stay in `infra/cli/` for follow-up changes if
  pursued.
- Delete `yascheduler/infra/cli/check_status.py`. Drop
  `from .check_status import check_status` and `"check_status"` from `__all__`
  in `yascheduler/infra/cli/__init__.py`; drop the
  `check_status - Re-exported from .check_status` line from its `MODULE_MAP`.
  No compat shim: any `infra → entrypoints` re-export would invert the layer
  direction enforced by `import-linter` (same reasoning as
  `relocate-submit-command` D1).
- Update `pyproject.toml`:
  `yastatus = "yascheduler.entrypoints.cli.check_status:check_status"`.
- Reimplement `check_status()` with `argparse`:
  - `prog="yastatus"` passed to `ArgumentParser` so `--help` and error screens
    show the command name (mirrors `init`'s `prog="yainit"`, `show_nodes`'s
    `prog="yanodes"`, `submit`'s `prog="yasubmit"`).
  - `argv: list[str] | None = None` parameter passed through to
    `parser.parse_args(argv)`. The `argv=None` default means the
    console_script entrypoint reads `sys.argv`; tests pass an explicit list.
    Mirrors `init`, `show_nodes`, `submit`.
  - `--help` shows the standard argparse help screen (argparse default).
  - Flags: `-j/--jobs` (nargs="*", orthogonal filter, composes with any
    renderer); `-v/--view`, `-i/--info`, `--json` in a
    `mutually_exclusive_group` (pick at most one renderer; none = the default
    AiiDA-compatible output); `-o/--convergence` is NOT in the mutex group (it
    is a modifier of `-v`) and a body-check after parse rejects `-o` without
    `-v` with `parser.error(...)` (exit 2).
- Exit code contract (mirrors `relocate-init-command` D3,
  `relocate-show-nodes-command` D5, `relocate-submit-command` D4):
  - `0` on success (normal completion; the function returns).
  - `1` on runtime failure: DB error, config parse error, SSH/SFTP failure,
    convergence-parse failure, any unexpected exception caught at the top level
    (`except Exception as e: print(f"Error: {e}", file=sys.stderr);
    sys.exit(1)`).
  - `2` on argparse error (argparse default — unknown flag, mutex violation,
    `-o` without `-v` via `parser.error`).
- AiiDA stdout compatibility contract (the distinguishing constraint,
  analogous to `relocate-submit-command` D5):
  - The default renderer (`_render_default`, used when none of `-v`/`-i`/`--json`
    is given) MUST emit exactly one line per task in the form
    `<task_id><whitespace><STATUS_NAME>` where `STATUS_NAME ∈ {TO_DO, RUNNING,
    DONE}` (the keys of `_MAP_STATUS_YASCHEDULER`). This is the format the AiiDA
    scheduler plugin's `_parse_joblist_output` parses via
    `for job_id, status in job.split()`; any other shape breaks it.
  - `-v`, `-i`, `-o`, and `--json` are NOT used by the AiiDA plugin (it only
    invokes `yastatus` or `yastatus --jobs ...`); their output is free to change.
- Default filter unchanged: `yastatus` with no `-j` queries
  `list_by_status({RUNNING, TO_DO})` (DONE excluded — the AiiDA plugin relies on
  this; the closed `TaskStatus` enum `{TO_DO, RUNNING, DONE}` guarantees the
  plugin's `_MAP_STATUS_YASCHEDULER` never KeyErrors). With `-j`, queries
  `list_by_jobs(job_ids)` (returns tasks of any status, all of which are valid
  AiiDA states).
- Fix the connection-params bug (`B-full`): introduce a private
  `_resolve_conn_params(node, config)` helper that mirrors
  `orchestrator._connect_machine_consumer:209-214` — returns
  `username=node.username`, `port=node.port`, and looks up `jump_host`/
  `jump_username` from the cloud whose `prefix == node.cloud`, falling back to
  `config.remote.jump_host`/`config.remote.jump_username` for static nodes.
  Pass all four to `gateway.connect(...)`. This fixes `yastatus -v` for cloud
  nodes behind a jump host. The helper is duplicated (not shared with
  orchestrator) because its shape differs (orchestrator connects inline;
  `check_status` returns a params object for the gateway call); a shared helper
  awaits a third consumer.
- Fix the DB-connection-lifecycle defect (`Q-uow`): separate the query phase
  from the render phase. Open one short UoW, fetch `tasks` (and, only when the
  renderer needs them, `nodes_by_ip`), close the UoW, then perform any SSH work
  in `_render_view` with no outer DB connection held. `_render_view` no longer
  opens its own UoW for the nodes lookup; it receives `nodes_by_ip` as an
  argument. `make_cli_deps(config)` is called once in `check_status` and passed
  down (the current code calls it twice).
- Add `--json` output mode (the second instance of the `--json` machine-readable
  CLI convention established by `relocate-show-nodes-command`): when `--json`
  is given, emit `json.dumps(list_of_objects)` with raw domain values (no display
  transformations). Each object has exactly these 9 fields:
  `task_id` (int), `status` (str, the enum name), `label` (str),
  `allocated_ip` (str | null), `port` (int | null), `cloud` (str | null),
  `engine` (str), `local_folder` (str | null), `remote_folder` (str | null).
  `port`/`cloud`/`allocated_ip` are `null` for tasks with no allocated IP
  (i.e. `TO_DO`); `engine` always comes from `task.context.engine`;
  `local_folder`/`remote_folder` come from `task.context`.
- Replace the fixed-name `local_calc_snippet.tmp` file with a `tempfile`-based
  file and `try/finally` cleanup so that the snippet is removed even when
  `_render_view` raises, and so two concurrent `yastatus -v -o` invocations no
  longer collide on the same filename.
- Split the logic into private pure functions in the new module:
  `_parse_status_args(argv)`, `_query_tasks(uow, args)` (the conditional query
  phase), `_render_default(tasks)` (AiiDA contract — moved as-is), `_render_info`
  (moved as-is), `_render_json(tasks, nodes_by_ip)`, `_render_view(tasks,
  nodes_by_ip, config, fetch_convergence)`, `_resolve_conn_params(node, config)`
  (new bugfix helper), `_display_remote_output(...)`,
  `_download_convergence_snippet(...)` (moved as-is), `_parse_convergence(path)`
  (moved as-is; deferred `pycrystal`/`numpy` imports preserved). Do NOT extract
  a `query_status` use case into `application/` — YAGNI: no second consumer
  exists (the AiiDA client queries via `queue_get_tasks_async`, not via CLI; the
  daemon does not query status). The contract records that promotion awaits a
  second consumer.
- Do NOT carry the `# FIXME: split adapter and application layer` comment to the
  new file (stale framing at `entrypoints/`, in-module split resolves the
  concern; same reasoning as `relocate-submit-command` D10). DO carry the
  `gateway._get_machine_state(ip)` FIXME with updated framing (private-method
  access is a cross-cutting SSH-gateway concern, out of scope for this
  relocation; tracked for a follow-up that adds a public
  `SSHMachineGateway.run_command(ip, cmd)`).
- Fresh GRACE-lite markup at the new path: `MODULE_CONTRACT`, `MODULE_MAP`,
  `CHANGE_SUMMARY`, function contracts, and block anchors appropriate to the
  reimplemented logic. The `entrypoints/cli/__init__.py` facade gets a
  declarative PURPOSE edit to add `check_status`.
- Update `openspec/specs/package-facades/spec.md`: drop `check_status` from the
  R1 example listing `infra/cli/__init__.py` submodules (the pre-state list is
  `check_status`, `daemonize`, `manage_node`; this change drops `check_status`
  → `daemonize`, `manage_node`).
- Update `openspec/specs/cli-commands/spec.md`:
  - Add new requirements for `yastatus`: module path
    `entrypoints/cli/check_status.py`; the `prog="yastatus"` detail; the `argv`
    testability parameter; the `0`/`1`/`2` exit-code contract; the
    AiiDA-default-output compatibility requirement (`<task_id>   <STATUS>`
    format, status names ∈ {TO_DO, RUNNING, DONE}); the
    `mutually_exclusive_group` flag matrix and the `-o` requires `-v` rule; the
    `--json` output schema (9 raw-value fields); the connection-params bugfix
    (`_resolve_conn_params` mirroring orchestrator); and the query/render
    separation.
  - Update the "other N CLI commands remain in `infra/cli/`" counter (from
    "other 3": `check_status`, `manage_node`, `daemonize` → "other 2":
    `manage_node`, `daemonize`).
  - Update the `--json` convention requirement to note `yastatus` as the second
    instance (after `yanodes`).
- Update `docs/knowledge-graph.xml`:
  - `M-CLI-COMMANDS`: delete the `<fn-check_status>` annotation.
  - Add a new module node `M-ENTRYPOINTS-CLI-CHECK-STATUS`
    (`path: yascheduler/entrypoints/cli/check_status.py`,
    `depends: M-CONFIG, M-DI, M-SSH-GATEWAY, M-DOMAIN-MODEL, M-SHARED,
    M-APPLICATION-UOW`).
  - Add `CrossLink from="M-ENTRYPOINTS-CLI-CHECK-STATUS" to="M-DI"
    relation="uses make_cli_deps for CLI status"`; `→ M-APPLICATION-UOW
    relation="reads tasks and nodes via UoW"`; `→ M-SSH-GATEWAY
    relation="verbose mode connects, tails OUTPUT, downloads convergence"`.
  - Amend the existing `CrossLink from="M-CLI-COMMANDS" to="M-DI"` relation to
    "uses make_cli_deps for CLI node management; make_daemon for daemon entry"
    (the current "uses make_daemon for daemon entry" omits the `manage_node`
    clause which also applies; this change makes it explicit and does NOT
    mention `check_status` since that module has moved out of `M-CLI-COMMANDS`).
  - Amend the existing
    `CrossLink from="M-CLI-COMMANDS" to="M-DOMAIN-MODEL" relation="imports Node,
    Task, TaskStatus for CLI status and node management"` to "imports Node,
    TaskStatus for CLI node management" (drop "Task" and "status" —
    `check_status` was the Task+status importer and has moved; `manage_node`
    keeps Node + TaskStatus).
  - Do NOT touch any `DF-*` element (there is no data-flow element for status
    queries; the only CLI-related DF is `DF-DAEMON-START`, unaffected).
- Tests:
  - Delete `tests/unit/test_cli_smoke.py::test_check_status_function_exists`
    (low-value smoke test — replaced by real unit tests, same as the three
    prior relocation changes did).
  - Delete the `TestCheckStatus` class from
    `tests/unit/test_cli_behavioral.py`; drop the `check_status_mod`
    module-level import.
  - Add `tests/unit/test_cli_check_status.py` with focused unit tests:
    argparse (`--help`, unknown flag → exit 2, `-v -i`/`--json -v` mutex → exit
    2, `-o` without `-v` → exit 2, `prog="yastatus"` in help/error screens),
    AiiDA-contract regression golden test (the default output of
    `_render_default` parses via `job.split()` into exactly 2 elements with the
    status ∈ {TO_DO, RUNNING, DONE}), default listing (`<task_id>   <STATUS>`
    format, `RUNNING + TO_DO` filter), `-j` filter (`list_by_jobs` called),
    `-i` info mode (tab-separated), `--json` (9 raw-value fields, `TO_DO` null
    fields, empty result `[]`, no display transformations), `-v` happy path
    (mock `SSHMachineGateway`: connect, tail OUTPUT, disconnect — verifies
    `_resolve_conn_params` passes `node.username`/`node.port`/jump-host from the
    matching cloud), exit codes (0 success, 1 runtime error, 2 argparse error),
    `argv` injection (no `patch sys.argv` needed), `_resolve_conn_params` unit
    test (matching cloud → its jump host; static node → `config.remote` jump
    host; no jump host configured → `None`), query/render separation invariant
    (no `uow` open during SSH — verified by mock call ordering). Mark with
    `pytest.mark.unit`. The `-o`/`pycrystal` convergence path is NOT covered
    here (left to a follow-up; the `_parse_convergence` deferred-import +
    `pycrystal`/`numpy` optional-dep shape makes it a separate concern).

### Out of scope (explicit, deferred to follow-up changes)

- The other 2 CLI commands (`manage_node`, `daemonize`) remain in
  `yascheduler/infra/cli/`; their migration into `entrypoints/cli/` is tracked
  separately, one per change.
- No new `application/query_status.py` or `application/view_status.py` use case
  (YAGNI — no second consumer).
- No public `SSHMachineGateway.run_command(ip, cmd)` method — the
  `_get_machine_state` private-method access FIXME is carried forward with
  updated framing; a follow-up change will address it cross-cuttingly.
- No `-o`/convergence (`pycrystal`) unit tests in this change — the scientific
  parse path is a separate concern; `_parse_convergence` and
  `_download_convergence_snippet` move as-is and keep their deferred imports.
- No new dependencies — stdlib only (`argparse`, `json`, `os`, `sys`,
  `tempfile`, `pathlib`, `typing`).
- `schema-migrations` (in progress) — unaffected; `yastatus` touches no schema,
  only reads via the existing task/node repositories.
- `di.py`, `application/`, `domain/`, `infra/persistence/`,
  `infra/ssh/gateway.py`, `entrypoints/aiida_plugin.py` — unchanged.

## Capabilities

### New Capabilities

_None._ The relocation and reimplementation are structural/operational concerns
for an existing command. No new spec capability is introduced: `yastatus`
already exists under `cli-commands`, and its requirements are modified (below)
rather than replaced.

### Modified Capabilities

- `cli-commands`: the `yastatus` command gains `prog="yastatus"`, the
  `argv: list[str] | None = None` testability parameter, the `0`/`1`/`2`
  exit-code contract, the AiiDA-default-output compatibility contract, the
  `mutually_exclusive_group` flag matrix with the `-o` requires `-v` rule, the
  `--json` output mode (9 raw-value fields, the second instance of the
  `--json` convention after `yanodes`), the connection-params bugfix
  (`_resolve_conn_params` mirroring orchestrator), the query/render separation,
  and a new module path (`entrypoints/cli/check_status.py`). The "other N CLI
  commands remain in `infra/cli/`" counter decrements. The `--json` convention
  requirement is updated to note `yastatus` as the second instance.
- `package-facades`: the R1 example listing `infra/cli/__init__.py` submodules
  drops `check_status` (it has moved to `entrypoints/cli/`). No layer-direction
  or facade-content requirement changes.

## Impact

- **Code**: `yascheduler/entrypoints/cli/check_status.py` (1 new file);
  `yascheduler/infra/cli/check_status.py` removed;
  `yascheduler/infra/cli/__init__.py` loses the `check_status` re-export +
  `__all__` entry + MODULE_MAP line (bump VERSION, CHANGE_SUMMARY);
  `yascheduler/entrypoints/cli/__init__.py` gets a declarative PURPOSE edit.
- **CLI**: `yastatus` behavior: `--help` works; `-o` without `-v` now exits 2
  with a clean argparse message instead of being silently ignored;
  `--json` is a new opt-in output mode (default output unchanged — AiiDA-
  compatible); `-v` on a cloud node behind a jump host now connects (previously
  failed silently with the wrong username); unexpected exceptions now exit 1
  with a clean stderr message instead of a traceback. Success path (default
  output, exit 0) unchanged. No **BREAKING** change to the command name, the
  success invocation, or the AiiDA scheduler plugin contract.
- **Config**: `pyproject.toml` (console_script target) updated.
  `[tool.importlinter]` unchanged.
- **Tests**: `tests/unit/test_cli_smoke.py` loses one test method;
  `tests/unit/test_cli_behavioral.py` loses the `TestCheckStatus` class and the
  `check_status_mod` module-level import; `tests/unit/test_cli_check_status.py`
  added with focused unit tests.
- **Specs**: `openspec/specs/cli-commands/spec.md` and
  `openspec/specs/package-facades/spec.md` modified.
- **Knowledge graph**: `docs/knowledge-graph.xml` — `M-CLI-COMMANDS` loses
  `<fn-check_status>`; new `M-ENTRYPOINTS-CLI-CHECK-STATUS` node + 3 CrossLinks
  added; 2 existing CrossLinks amended; no `DF-*` touched.
- **Docs**: any references to the `yastatus` command name only — unchanged.
- **Dependencies**: none added or removed.
