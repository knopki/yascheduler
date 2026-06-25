## 1. Create the new module scaffold

- [x] 1.1 Create `yascheduler/entrypoints/cli/check_status.py` with the `FILE`/`VERSION`/`START_MODULE_CONTRACT`/`START_MODULE_MAP`/`START_CHANGE_SUMMARY` header (VERSION 1.0.0; PURPOSE: yastatus CLI command; DEPENDS: M-CONFIG, M-DI, M-SSH-GATEWAY, M-DOMAIN-MODEL, M-SHARED, M-APPLICATION-UOW; LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS, M-DI, M-SSH-GATEWAY)
- [x] 1.2 Add module-level imports: `argparse`, `json`, `os`, `sys`, `tempfile`, `from pathlib import Path`, `from typing import Optional`, `from dataclasses import dataclass`; `from yascheduler.config import Config`; `from yascheduler.di import make_cli_deps`; `from yascheduler.domain import Node, Task, TaskStatus`; `from yascheduler.infra import SSHMachineGateway`; `from yascheduler.shared import CONFIG_FILE, to_sync` (add `logging` only if the implementation emits structured log entries — the current `check_status.py` has none, so omit it to avoid a ruff F401)
- [x] 1.3 Add the `START_CHANGE_SUMMARY` block: LAST_CHANGE v1.0.0 — Reimplemented at entrypoints/cli/ in relocate-check-status-command (moved from infra/cli/, added prog/argv/exit-codes/--json/full mutex/-o requires -v/connection-params bugfix/UoW lifecycle fix/tempfile)

## 2. Implement argparse flag matrix (design D3)

- [x] 2.1 Add `START_CONTRACT: _parse_status_args` + implement `_parse_status_args(argv: list[str] | None = None) -> argparse.Namespace` using `ArgumentParser(prog="yastatus", description="Show status of tasks")`
- [x] 2.2 Add `-j/--jobs` (`nargs="*"`, `default=None`) as the orthogonal job filter
- [x] 2.3 Create `mutex = parser.add_mutually_exclusive_group()` with `-v/--view`, `-i/--info`, `--json` (each `action="store_true"`, `default=False`)
- [x] 2.4 Add `-o/--convergence` (`action="store_true"`, `default=False`) OUTSIDE the mutex group; add the body-check `if args.convergence and not args.view: parser.error("--convergence requires --view")` after `parser.parse_args(argv)`
- [x] 2.5 Return the parsed Namespace

## 3. Implement the query phase (design D8)

- [x] 3.1 Add `START_CONTRACT: _query_tasks` + implement `_query_tasks(uow, args) -> list[Task]`: if `args.jobs` → `await uow.tasks.list_by_jobs(job_ids=args.jobs)`; else → `await uow.tasks.list_by_status({TaskStatus.RUNNING, TaskStatus.TO_DO})`
- [x] 3.2 Verify `_query_tasks` is the ONLY task query; it runs inside the single query-phase UoW

## 4. Implement renderers

- [x] 4.1 Implement `_render_default(tasks: list[Task]) -> None`: moved as-is from `_print_status_default` — `for task in tasks: print(f"{task.task_id}   {task.status.name}")`. Add `START_CONTRACT: _render_default` noting this is the AiiDA compatibility contract (do NOT decorate)
- [x] 4.2 Implement `_render_info(tasks: list[Task]) -> None`: moved as-is from `_print_status_info` — tab-separated `task_id=...\tstatus=...\tlabel=...\tip=...`
- [x] 4.3 Add `START_CONTRACT: _render_json` + implement `_render_json(tasks: list[Task], nodes_by_ip: dict[str, Node]) -> str`: build a list of 9-field objects (`task_id`, `status` as `.name`, `label`, `allocated_ip` or null, `port` or null via `nodes_by_ip`, `cloud` or null via `nodes_by_ip`, `engine` from `task.context.engine`, `local_folder` from `task.context.local_folder`, `remote_folder` from `task.context.remote_folder`); return `json.dumps(objects)`
- [x] 4.4 Verify `_render_json` uses raw domain values (no display transformations: port=22 stays 22, not "-"; cloud=None stays null, not "-")

## 5. Implement connection-params bugfix (design D7)

- [x] 5.1 Define `@dataclass(frozen=True) class _ConnParams:` with `username: str`, `port: int`, `jump_host: str | None`, `jump_username: str | None`
- [x] 5.2 Add `START_CONTRACT: _resolve_conn_params` + implement `_resolve_conn_params(node: Node, config: Config) -> _ConnParams`: start with `jump_host = config.remote.jump_host`, `jump_username = config.remote.jump_username`; loop `for cloud in config.clouds: if cloud.prefix == node.cloud:` and if both `cloud.jump_host` and `cloud.jump_username` are set, override; `break` after the match; return `_ConnParams(username=node.username, port=node.port, jump_host=jump_host, jump_username=jump_username)`
- [x] 5.3 Add a NOTE to the contract: "mirrors orchestrator._connect_machine_consumer:209-214; duplicated (not shared) because the shape differs; promotion to a shared helper awaits a third consumer"

## 6. Implement view mode + remote output (design D5, D10)

- [x] 6.1 Move `_download_convergence_snippet(gateway, ip, remote_folder, local_path) -> bool` as-is (SFTP download with `OSError` → `False` fallback)
- [x] 6.2 Move `_parse_convergence(filepath: Path) -> str` as-is with deferred imports (`from numpy import nan`; `from pycrystal import CRYSTOUT, CRYSTOUT_Error`) inside the function body
- [x] 6.3 Update `_display_remote_output(task, ssh_user, config)` → `_display_remote_output(task, conn_params: _ConnParams, config: Config)`: use `conn_params.username`/`conn_params.port`/`conn_params.jump_host`/`conn_params.jump_username` in the `gateway.connect(...)` call instead of the old `ssh_user` argument; keep the `_get_machine_state(ip)` access with the updated FIXME framing (see task 7.3)
- [x] 6.4 Refactor `_print_status_view` → `_render_view(tasks, nodes_by_ip, config, fetch_convergence, deps) -> Optional[Path]`: receive `nodes_by_ip` as an argument (no longer open its own UoW); for each RUNNING task with an allocated IP, resolve `_resolve_conn_params(node, config)`, print the separator+header line, call `_display_remote_output`, optionally download+parse convergence into a `tempfile`-created snippet
- [x] 6.5 Replace the fixed-name `Path(config.local.data_dir, "local_calc_snippet.tmp")` with `tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")` (or `tempfile.mkstemp`); pass the temp path to `_download_convergence_snippet` and `_parse_convergence`

## 7. Implement the entry point + lifecycle (design D4, D8, D10)

- [x] 7.1 Add `START_CONTRACT: check_status` + implement `@to_sync async def check_status(argv: list[str] | None = None) -> None` with a top-level `try/except Exception as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)`
- [x] 7.2 Inside the try: parse args, load config, build deps once (`make_cli_deps`), open ONE query-phase UoW (`async with deps.uow_factory() as uow:`), fetch `tasks = await _query_tasks(uow, args)`, conditionally fetch `nodes_by_ip` (only when `args.view or args.json`), CLOSE the UoW, then dispatch to the selected renderer (`_render_view` / `_render_info` / `print(_render_json(...))` / `_render_default`)
- [x] 7.3 Add the carried-forward FIXME with updated framing: `# FIXME: _display_remote_output reaches into gateway._get_machine_state(ip) to bridge to run_full(state.machine, ...). A public SSHMachineGateway.run_command(ip, cmd) should replace this; tracked for a cross-cutting follow-up (not this relocation).`
- [x] 7.4 Wrap the view-mode temp-snippet cleanup in `try/finally` so the file is removed even when `_render_view` raises (the `except` path that exits 1 must still clean up)
- [x] 7.5 Verify `sys.exit(0)` is NOT called on success — the function returns normally (the `0` exit code is implicit)

## 8. Update wiring (design D1, D12)

- [x] 8.1 Update `pyproject.toml`: change `yastatus = "yascheduler.infra.cli.check_status:check_status"` → `yastatus = "yascheduler.entrypoints.cli.check_status:check_status"`
- [x] 8.2 Edit `yascheduler/infra/cli/__init__.py`: remove `from .check_status import check_status`; remove `"check_status"` from `__all__`; remove the `check_status - Re-exported from .check_status` line from `MODULE_MAP`; bump VERSION; add CHANGE_SUMMARY entry (drop check_status re-export; check_status moved to entrypoints/cli/ in relocate-check-status-command)
- [x] 8.3 Edit `yascheduler/entrypoints/cli/__init__.py`: update the PURPOSE declarative wording to include `check_status` (e.g., "Init, show_nodes, submit, and check_status CLI entry point subpackage facade."); update SCOPE and LINKS to include `M-ENTRYPOINTS-CLI-CHECK-STATUS`; bump VERSION; add CHANGE_SUMMARY entry
- [x] 8.4 Delete `yascheduler/infra/cli/check_status.py`

## 9. Update tests

- [x] 9.1 In `tests/unit/test_cli_smoke.py`: delete `test_check_status_function_exists` (low-value smoke test)
- [x] 9.2 In `tests/unit/test_cli_behavioral.py`: delete the `TestCheckStatus` class and the `check_status_mod = importlib.import_module(...)` line; update the file's MODULE_CONTRACT SCOPE to note check_status moved; bump VERSION; add CHANGE_SUMMARY entry
- [x] 9.3 Create `tests/unit/test_cli_check_status.py` with MODULE_CONTRACT (PURPOSE: unit tests for yastatus; DEPENDS: M-ENTRYPOINTS-CLI-CHECK-STATUS), `pytestmark = pytest.mark.unit`, and shared mock helpers (`make_mock_config`, `make_mock_uow`, `make_mock_deps`, `make_task` — mirror `test_cli_show_nodes.py`)
- [x] 9.4 Add `TestCheckStatusParsing`: `--help` exits 0 (assert prog="yastatus", all flags listed); `--bogus` exits 2; `-v -i` exits 2 (mutex); `--json -v` exits 2 (mutex); `--json -i` exits 2 (mutex); `-o` without `-v` exits 2; `-o -v` does NOT exit (valid)
- [x] 9.5 Add `TestCheckStatusAiiDAContract` (the golden regression test — design D9): render tasks of all 3 statuses (TO_DO, RUNNING, DONE) via `_render_default`; capture stdout; parse with the plugin's EXACT logic `[job.split() for job in stdout.split("\n") if job]`; assert the `for job_id, status in pairs` unpack yields exactly 2 elements per line; assert `set(statuses) <= {"TO_DO", "RUNNING", "DONE"}`; assert the mapping is correct
- [x] 9.6 Add `TestCheckStatusDefault`: default invocation (no flags) calls `list_by_status({RUNNING, TO_DO})` and prints `<id>   <STATUS>`; DONE excluded by default; `-j 1 2` calls `list_by_jobs(job_ids=["1","2"])`
- [x] 9.7 Add `TestCheckStatusInfo`: `-i` prints tab-separated `task_id=...\tstatus=...\tlabel=...\tip=...`
- [x] 9.8 Add `TestCheckStatusJson`: `--json` emits valid JSON list; 9 fields present with raw values (port=22 not "-"; status="RUNNING" not 1); TO_DO task has null `allocated_ip`/`port`/`cloud`; `engine` always present; empty result is `[]`; `--json -j 1` composes
- [x] 9.9 Add `TestCheckStatusExitCodes`: exit 0 on success (no SystemExit raised); exit 1 on DB error (`list_by_status` side_effect=RuntimeError → SystemExit(1), stderr has "Error:"); exit 1 on config error; exit 1 on unexpected exception
- [x] 9.10 Add `TestCheckStatusArgvInjection`: invoke `check_status(["--json"])` directly (no `patch sys.argv`); verify the argv parameter is threaded through to argparse
- [x] 9.11 Add `TestResolveConnParams`: matching cloud (`node.cloud="hetzner"`, hetzner cloud has jump_host+jump_username) → returns the cloud's jump host; static node (`node.cloud=None`) → returns `config.remote.jump_host`/`jump_username`; always returns `username=node.username` (NOT a cloud username); always returns `port=node.port`
- [x] 9.12 Add `TestCheckStatusViewHappyPath` (mock `SSHMachineGateway`): `-v` against a RUNNING task → `_resolve_conn_params` called with the task's node; `gateway.connect` called with `node.username`/`node.port`/jump-host; `_display_remote_output` tails OUTPUT; `gateway.disconnect` called; nodes_by_ip fetched (verify `uow.nodes.get_by_ips` called); default/-i do NOT call `uow.nodes.get_by_ips` (lazy lookup invariant)
- [x] 9.13 Add `TestCheckStatusQueryRenderSeparation`: verify by mock call ordering that the UoW `__aexit__` is called BEFORE any SSH operation (`gateway.connect`) — assert `uow.__aexit__` call precedes `gateway.connect` call in the mock history

## 10. Update knowledge graph (design D13)

- [x] 10.1 In `docs/knowledge-graph.xml`: add `<M-ENTRYPOINTS-CLI-CHECK-STATUS NAME="yastatus CLI entry point" TYPE="ENTRY_POINT" STATUS="implemented">` with `<purpose>`, `<path>yascheduler/entrypoints/cli/check_status.py</path>`, `<depends>M-CONFIG, M-DI, M-SSH-GATEWAY, M-DOMAIN-MODEL, M-SHARED, M-APPLICATION-UOW</depends>`, and `<annotations>` for `fn-check_status` (and private helpers as appropriate)
- [x] 10.2 In `M-CLI-COMMANDS`: delete `<fn-check_status PURPOSE="Show status of tasks (infra/cli/check_status.py)" />`
- [x] 10.3 Add three CrossLinks: `from="M-ENTRYPOINTS-CLI-CHECK-STATUS" to="M-DI" relation="uses make_cli_deps for CLI status"`; `from="M-ENTRYPOINTS-CLI-CHECK-STATUS" to="M-APPLICATION-UOW" relation="reads tasks and nodes via UoW"`; `from="M-ENTRYPOINTS-CLI-CHECK-STATUS" to="M-SSH-GATEWAY" relation="verbose mode connects, tails OUTPUT, downloads convergence"`
- [x] 10.4 Amend the existing `<CrossLink from="M-CLI-COMMANDS" to="M-DI" relation="uses make_daemon for daemon entry" />` to `relation="uses make_cli_deps for CLI node management; make_daemon for daemon entry"` (manage_node stays and uses make_cli_deps)
- [x] 10.5 Amend the existing `<CrossLink from="M-CLI-COMMANDS" to="M-DOMAIN-MODEL" relation="imports Node, Task, TaskStatus for CLI status and node management" />` to `relation="imports Node, TaskStatus for CLI node management"` (drop "Task" and "status" — check_status was the importer and has moved)

## 11. Validation

- [x] 11.1 Run `uv run pytest -m unit` — all unit tests pass (including the new `test_cli_check_status.py` and the updated smoke/behavioral files)
- [x] 11.2 Run `uv run ruff check .` and `uv run ruff format --check .` — no violations in the new module
- [x] 11.3 Run `uv run lint-imports` — the `layers` contract passes (no `infra → entrypoints` violation from the deleted shim; `entrypoints → infra` is the legal direction)
- [x] 11.4 Run `uv run zuban check` — no type errors in the new module
- [x] 11.5 Run `python3 scripts/grace_check.py` — GRACE-lite validation passes (XML well-formed, source markup present, no orphan anchors)
- [x] 11.6 Run `openspec validate --all --json` — spec validation passes after the delta specs are applied
- [x] 11.7 Manually verify `yastatus --help` shows `prog="yastatus"` and all flags; verify `yastatus` (no args) still prints the default `<id>   <STATUS>` format
