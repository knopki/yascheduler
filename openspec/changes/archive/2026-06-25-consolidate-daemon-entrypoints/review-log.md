# Review Log — consolidate-daemon-entrypoints

## proposal Round 1 — 2026-06-25

### 🔴 Fixed
(none)

### 🟡 Addressed
(none)

### 🔴 Outstanding
(none — frozen)

Reviewer: @k-reviewer-fast. Verdict: APPROVE on first round. All 12 verification points passed; no internal contradictions; ~101 lines, well-structured; BREAKING marker correctly scoped to systemd `--log-file` default change.

---

## design Round 1 — 2026-06-25

### 🔴 Fixed
(none)

### 🟡 Addressed
(none)

### 🔴 Outstanding
(none — frozen)

Reviewer: @k-reviewer-fast. Verdict: APPROVE on first round. All 12 decisions (D1–D12) sound and consistent with the frozen proposal and explore-brief; all 10 bugs (A–J) covered; risks and migration plan present; open questions correctly stated as none.

---

## specs Round 1 — 2026-06-25

### 🔴 Fixed
(none)

### 🟡 Addressed
(none — frozen)

### 🔴 Outstanding
(none — frozen)

Reviewer: @k-reviewer-fast. Verdict: APPROVE on first round. All 4 spec delta files (cli-args, daemon-common, cli-commands, package-facades) pass: helpers present, root-logger config correct, asyncio.run not @to_sync, MODIFIED sections contain full updated content, infra/cli/ liquidation reflected, exit-code contract matches design D12, defaults match design tables, no scope creep. `openspec validate` reports 0 issues after two SHALL-on-first-line fixes (cli-commands "Daemon launcher argparse and defaults", package-facades "Within-package relative imports (R1)").

---

## tasks Round 1 — 2026-06-25

### 🔴 Fixed
(none)

### 🟡 Addressed
(none)

### 🔴 Outstanding
- Ordering defect: section 6 (tests) was listed AFTER section 4 (liquidation of infra/cli/), which would break `test_cli_smoke.py` (imports `from yascheduler.infra.cli import daemonize`) between task 4.1 and task 6.1.

Reviewer: @k-reviewer-fast. Verdict: REQUEST CHANGES — reorder section 6 before section 4. All other checks (coverage, granularity, format, verifiability, no scope creep, GRACE-lite) passed.

---

## tasks Round 2 — 2026-06-25

### 🔴 Fixed
- Reordered sections: tests (now section 4) come BEFORE liquidation (now section 5). New ordering: 1 → 2 → 3 → 4 (tests) → 5 (liquidation) → 6 (pyproject) → 7 (graph) → 8 (validation). Task 4.1 updates `test_cli_smoke.py` before task 5.1 deletes `infra/cli/daemonize.py`. Task 5.4 grep reference updated to "tasks 1-4". All cross-references in task 8.4 (test file names) verified correct.

### 🟡 Addressed
(none)

### 🔴 Outstanding
(none — frozen)

Reviewer: @k-reviewer-fast. Verdict: APPROVE. The ordering fix resolves the only outstanding issue; all other checks still hold. `openspec validate` reports 0 issues.

---

## implementation Round 1 — 2026-06-25

Three parallel @k-reviewer-fast sessions reviewed (a) implementation correctness & bug-hunting, (b) GRACE-lite compliance, (c) tests & coverage.

### 🔴 Fixed
- **Signal-handler late-binding closure (BLOCKER)** — `daemon_common.py:run_daemon` registered two signal handlers in a `for sig in [SIGTERM, SIGINT]` loop with a bare closure capturing `sig` by reference (the `# noqa: B023` suppressed the bugbear warning but the bug manifested: both handlers dispatched SIGINT when fired, misreporting SIGTERM in logs). Fixed by wrapping the handler in a factory `_make_handler(sig)` so `sig` binds by value. Added regression test `test_each_signal_handler_dispatches_its_own_signal` (verifies each handler's closure cell holds the correct signal; confirmed it FAILS on the buggy code and PASSES on the fix). Bumped daemon_common.py to v1.0.1.
- **Inconsistent logger setup in `submit.py`/`manage_node.py`** — these two set the root logger level and called `captureWarnings(True)` but added no `StreamHandler`, relying on `logging.lastResort` (WARNING only) — so `--log-level DEBUG` produced no visible output. Added the `if not log.handlers: log.addHandler(logging.StreamHandler(sys.stderr))` guard, matching `show_nodes.py`/`check_status.py`/`init.py`. Bumped to v1.1.1 / v1.2.1.
- **`_init_schema` type annotation** — `init.py:_init_schema(config_path: str = CONFIG_FILE)` but argparse passes a `Path` (via `existing_path`). Widened signature to `str | Path` and aligned MODULE_CONTRACT INPUTS. Bumped init.py to v1.2.1.

### 🟡 Addressed (GRACE-lite graph)
- `M-ENTRYPOINTS-CLI-ARGS` `<depends>` corrected from `none` to `M-SHARED` (args.py imports `CONFIG_FILE` from shared).
- `M-DAEMON-SYSTEMD` depends `M-SHARED` → `M-CONFIG` (daemon_systemd.py imports Config, not shared).
- `M-DAEMON-SYSV` depends added `M-CONFIG` (imports Config); `M-SHARED` retained (imports LOG_FILE/PID_FILE).
- `M-ENTRYPOINTS-CLI-INIT`, `M-ENTRYPOINTS-CLI-SHOW-NODES`, `M-ENTRYPOINTS-CLI-SUBMIT`, `M-ENTRYPOINTS-CLI-MANAGE-NODE`, `M-ENTRYPOINTS-CLI-CHECK-STATUS` depends all gained `M-ENTRYPOINTS-CLI-ARGS` (each imports from args.py).
- Removed stale `fn-_existing_path` annotation from `M-ENTRYPOINTS-CLI-SUBMIT` (private helper deleted in this change).
- Added `fn-_submit_async`, `fn-_show_nodes_async`, `fn-_manage_node_async`, `fn-_check_status_async` annotations and aligned the sync entry-point PURPOSE descriptions across the five CLI module graph entries.

### 🟡 Addressed (tests)
- Bumped VERSION headers 1.0.0 → 1.1.0 in the 5 modified test files (test_cli_submit/show_nodes/manage_node/check_status/init) to match their CHANGE_SUMMARY LAST_CHANGE v1.1.0.
- `test_cli_manage_node.py:690` misleading `assert root.level == logging.WARN` → `logging.WARNING` (WARN is the deprecated alias; the code sets level via `getLevelName("WARNING")`).
- Removed empty dead-code `TestManageNodeHelpersReturnNone` class (leftover after task 4.2 deleted `test_manage_node_is_to_sync_decorated`).
- Simplified `test_cli_daemonize.py:test_default_log_file_is_none` — removed redundant first `configure_logger` monkeypatch (overwritten by the second) and dead `captured` dict / `_peek` inner coroutine.
- Added missing `--config /nonexistent` → exit 2 coverage to `test_cli_daemon_systemd.py` and `test_cli_daemon_sysv.py` (the spec scenario applied to all 9 entry points but only 7 were tested; a regression removing `type=existing_path` from these parsers would now be caught).

### 🟢 NIT (outstanding, accepted)
- `configure_logger` in daemon_common.py always adds handlers (no guard); acceptable because daemon entry points run once per process. Tests use an autouse `_reset_root_logger` fixture. The CLI commands guard with `if not root.handlers:`. No action — intentional daemons-run-once vs CLI-may-reenter split.
- `orch.stop()` mock set up but never exercised in `test_daemon_common.py` (signal handlers not triggered); the new closure-cell regression test exercises the binding without triggering the full signal path. Acceptable.
- Root-logger cleanup uses autouse fixture in daemon tests, try/finally in CLI tests; consistent enough within each file's scope. Factoring a shared conftest fixture is a separate cleanup change.

### 🔴 Outstanding
(none — frozen)

Reviewer: @k-reviewer-fast (3 parallel sessions). Verdict: REQUEST CHANGES on round 1 (1 BLOCKER + SHOULD-FIX items). All fixes applied; `uv run pytest -m unit` → 230 passed; `python3 scripts/grace_check.py` → exit 0 (0 errors, 35 warnings — all pre-existing soft-limit); `openspec validate --all --json` → 32/32 pass; `uv run ruff check .` → clean; `uv run ruff format --check .` → 144 files formatted; `uv run lint-imports` → 2 contracts kept.