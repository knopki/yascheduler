## 1. Pre-flight audit re-verification

- [x] 1.1 Re-run `rg "\.(get_conn|get_adapter|get_platforms|get_data_dir|get_engines_dir|get_tasks_dir|register_machine)\(" yascheduler/` and confirm ZERO production hits (any hit blocks the change pending scope re-evaluation)
- [x] 1.2 Re-run `rg "repository\.(keys|items)\(\)|repo\.(keys|items)\(\)" yascheduler/ tests/` and confirm ONLY test hits in `tests/unit/test_ssh_gateway.py`
- [x] 1.3 Re-confirm `tests/unit/test_ssh_gateway.py:649` is the sole `register_machine` caller and no conftest/fixture transitively depends on it

## 2. Concrete class methods removal (`infra/ssh/repository.py`)

- [x] 2.1 Delete the 9 methods from `SSHMachineRepository`: `get_conn`, `keys`, `items`, `register_machine`, `get_adapter`, `get_platforms`, `get_data_dir`, `get_engines_dir`, `get_tasks_dir`. Also delete the now-unused `ItemsView` and `KeysView` imports from the `TYPE_CHECKING` block at `repository.py:42` (they were only used by the deleted `keys()`/`items()` methods). ⚠ The e2e test at `tests/e2e/test_full_cycle.py:64` calls `repository.get_engines_dir(...)` and WILL fail with `AttributeError` until step 5.3 lands — do not run the e2e suite mid-section.
- [x] 2.2 Update `MODULE_MAP` (remove the 9 `<symbol> - description` lines) and `CHANGE_SUMMARY` (add `PREVIOUS_CHANGE` line referencing `decompose-ssh-gateway v1.0.0`; new `LAST_CHANGE` describing this cleanup) per GRACE-lite
- [x] 2.3 Run `uv run pytest -m unit tests/unit/test_ssh_gateway.py -x` — confirm no `AttributeError` from tests that previously exercised surviving methods

## 3. Protocol narrowing (`domain/ports.py`)

- [x] 3.1 Delete the 6 method declarations from the `MachineRepository` Protocol: `get_conn`, `get_adapter`, `get_platforms`, `get_data_dir`, `get_engines_dir`, `get_tasks_dir`
- [x] 3.2 Update `CHANGE_SUMMARY` in `domain/ports.py` per GRACE-lite

## 4. Test-fake lockstep (`tests/unit/test_domain_ports.py`)

- [x] 4.1 Delete the same 6 Protocol methods from `StubMachineRepository` (the actual class name in `tests/unit/test_domain_ports.py`)
- [x] 4.2 Run `rg "class .*MachineRepository|MachineRepository\)" tests/` and confirm `StubMachineRepository` is the only test fake implementing the Protocol; if any other is found, delete the same 6 methods there too

## 5. Test removals

- [x] 5.1 Delete the `TestPropertyHelpers` class from `tests/unit/test_ssh_gateway.py` (covers `test_get_adapter`, `test_get_platforms`, `test_get_data_dir`, `test_get_engines_dir`, `test_get_tasks_dir`, and any sibling tests for `get_hostname`/`get_path`/`get_quote` that fall in the same class — verify class scope before deletion)
- [x] 5.2 Delete the `test_keys`, `test_items`, `test_register_machine` methods from `tests/unit/test_ssh_gateway.py` — these are inside `class TestMachineState` (line 598), NOT `TestMachineStateMethods`; verify exact location before deletion
- [x] 5.3 Migrate `tests/e2e/test_full_cycle.py:64` from `repository.get_engines_dir(ssh_container["host"])` to `config.remote.engines_dir` (verified in scope at line 48; same value passed to `connect()` at line 59)
- [x] 5.4 Run `uv run pytest -m unit` and `uv run pytest -m e2e` — confirm green

## 6. Knowledge-graph cleanup (`docs/knowledge-graph.xml`)

- [x] 6.1 Delete the 9 `<fn-*>` annotations under `M-SSH-REPOSITORY` (lines 935, 943, 944, 947, 948, 949, 954, 955, 956): `fn-get_conn`, `fn-get_adapter`, `fn-get_platforms`, `fn-get_data_dir`, `fn-get_engines_dir`, `fn-get_tasks_dir`, `fn-register_machine`, `fn-keys`, `fn-items`
- [x] 6.2 Do NOT change the `<path>`, `<purpose>`, `<depends>`, or any `<CrossLink>` — only the annotation list narrows
- [x] 6.3 Manually verify the 9 annotations are gone (visual diff inspection) — note that `scripts/grace_check.py` validates XML structure and marker consistency but does NOT cross-check annotation names against source symbols, so a missed annotation would not be caught by 7.4 alone

## 7. Final validation suite

- [x] 7.1 `uv run pytest -m unit` — green
- [x] 7.2 `uv run pytest -m integration` — green (requires PostgreSQL testcontainer via Docker)
- [x] 7.3 `uv run pytest -m e2e` — green (requires PostgreSQL + SSH testcontainers via Docker); specifically confirm `test_full_cycle.py` passes after the `get_engines_dir` migration
- [x] 7.4 `python3 scripts/grace_check.py` — exit 0 (validates XML structure + source markers, NOT annotation-source consistency)
- [x] 7.5 `uv run ruff check . && uv run ruff format --check .` — clean
- [x] 7.6 `uv run lint-imports` — clean (no project config file; uses packaged default rules per AGENTS.md mandate)
- [x] 7.7 `uv run zuban check` — clean
- [x] 7.8 `openspec validate --all --json` — `cleanup-unused-repository-symbols` returns `"valid": true`
