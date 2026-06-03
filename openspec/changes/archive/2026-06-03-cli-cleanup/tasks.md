## 1. CLI Commands

- [x] 1.1 Create `adapters/cli/__init__.py` and `adapters/cli/commands.py`
- [x] 1.2 Move `submit()` function — parse args, call SubmitTask, print task_id
- [x] 1.3 Move `check_status()` function — parse args, call query use case, display
- [x] 1.4 Move `show_nodes()` function — parse args, call query use case, display
- [x] 1.5 Move `manage_node()` function — parse args, call ManageNode use case
- [x] 1.6 Move `init()` function — systemd/sysv service + DB init via use case
- [x] 1.7 Move `daemonize()` function — call make_daemon(), await orchestrator.start()
- [x] 1.8 Replace direct DB/SSH calls in CLI with use case calls
- [x] 1.9 Add GRACE-lite markup

## 2. Entry Points

- [x] 2.1 Update `pyproject.toml` console_scripts paths to adapters.cli.commands
- [x] 2.2 Verify `uv run yasubmit --help` works
- [x] 2.3 Verify `uv run yastatus --help` works
- [x] 2.4 Verify all 6 commands are callable

## 3. Utils Wrapper

- [x] 3.1 Replace `utils.py` body with re-exports from adapters.cli.commands
- [x] 3.2 Verify `from yascheduler.utils import submit` still works

## 4. Tests

- [x] 4.1 Write smoke test for each CLI command (subprocess or direct call)
- [x] 4.2 Verify output format unchanged for yasubmit, yastatus, yanodes

## 5. Verification

- [x] 5.1 Run `grace_check.py`
- [x] 5.2 Update `docs/knowledge-graph.xml`
- [x] 5.3 Run `openspec validate --all --json`
- [x] 5.4 Run full test suite — no regressions
