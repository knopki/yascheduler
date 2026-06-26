## 1. protocol.py — relocate ProcessInfo, remove dead Protocols

- [x] 1.1 Add `from dataclasses import dataclass` to `protocol.py` imports; add the frozen `ProcessInfo` dataclass (fields `pid: int`, `name: str`, `command: str`) immediately after `AllSSHRetryExc` (before the callable Protocol classes).
- [x] 1.2 Delete the `PProcessInfo` Protocol class from `protocol.py`.
- [x] 1.3 Delete the `PNode` Protocol class from `protocol.py`.
- [x] 1.4 Update `ListProcessesCallable.__call__` and `PgrepCallable.__call__` return annotations from `AsyncGenerator[PProcessInfo, None]` to `AsyncGenerator[ProcessInfo, None]`.
- [x] 1.5 Update `protocol.py` MODULE_CONTRACT SCOPE list (remove `PProcessInfo`, `PNode`; add `ProcessInfo`).
- [x] 1.6 Update `protocol.py` MODULE_MAP entries (remove `PProcessInfo`, `PNode`; add `ProcessInfo - frozen dataclass holding pid, name, command`).
- [x] 1.7 Add a `START_CHANGE_SUMMARY` entry for this change (v1.2.0 — consolidate ProcessInfo into protocol.py, remove PProcessInfo and PNode Protocols).

## 2. common.py — drop ProcessInfo

- [x] 2.1 Delete the `ProcessInfo` class from `common.py`.
- [x] 2.2 Remove the `from dataclasses import dataclass` import from `common.py` if it is no longer used by `run`/`run_bg` (verify before removing).
- [x] 2.3 Update `common.py` MODULE_CONTRACT SCOPE (drop "ProcessInfo data class"; keep "run and run_bg command execution helpers").
- [x] 2.4 Update `common.py` MODULE_MAP (remove the `ProcessInfo` line).
- [x] 2.5 Update `common.py` `START_CHANGE_SUMMARY` (new LAST_CHANGE entry for v1.2.0 — relocate ProcessInfo to protocol.py; module now hosts only run/run_bg).

## 3. linux.py — switch import + annotations

- [x] 3.1 Change `from .common import ProcessInfo` to `from .protocol import ProcessInfo` (or merge into the existing `from .protocol import ...` line).
- [x] 3.2 Remove `PProcessInfo` from the `from .protocol import OuterRunCallable, PProcessInfo, QuoteCallable` line.
- [x] 3.3 Update `linux_list_processes` return annotation: `AsyncGenerator[PProcessInfo, None]` → `AsyncGenerator[ProcessInfo, None]`.
- [x] 3.4 Update the `linux_list_processes` START_CONTRACT OUTPUTS line accordingly.
- [x] 3.5 Update `linux_pgrep` return annotation: `AsyncGenerator[PProcessInfo, None]` → `AsyncGenerator[ProcessInfo, None]`.
- [x] 3.6 Update the `linux_pgrep` START_CONTRACT OUTPUTS line accordingly.
- [x] 3.7 Update `linux.py` `START_CHANGE_SUMMARY` (new LAST_CHANGE entry).

## 4. windows.py — switch import + annotations

- [x] 4.1 Change `from .common import ProcessInfo` to `from .protocol import ProcessInfo`.
- [x] 4.2 Remove `PProcessInfo` from the `from .protocol import OuterRunCallable, PProcessInfo, QuoteCallable` line.
- [x] 4.3 Update `windows_list_processes` return annotation: `AsyncGenerator[PProcessInfo, None]` → `AsyncGenerator[ProcessInfo, None]`.
- [x] 4.4 Update the `windows_list_processes` START_CONTRACT OUTPUTS line accordingly.
- [x] 4.5 Update `windows_pgrep` return annotation: `AsyncGenerator[PProcessInfo, None]` → `AsyncGenerator[ProcessInfo, None]`.
- [x] 4.6 Update the `windows_pgrep` START_CONTRACT OUTPUTS line accordingly.
- [x] 4.7 Update `windows.py` `START_CHANGE_SUMMARY` (new LAST_CHANGE entry).

## 5. __init__.py — re-export block + __all__

- [x] 5.1 In the `from .common import ProcessInfo, run, run_bg` line, drop `ProcessInfo` (keep `run, run_bg`).
- [x] 5.2 Add `ProcessInfo` to the `from .protocol import (...)` block.
- [x] 5.3 Remove `PNode` and `PProcessInfo` from the `from .protocol import (...)` block.
- [x] 5.4 Remove `PNode` and `PProcessInfo` from `__all__`. Keep `ProcessInfo` in `__all__` unchanged.
- [x] 5.5 Update `__init__.py` `START_CHANGE_SUMMARY` (new LAST_CHANGE entry — relocate ProcessInfo import source to .protocol; drop PNode, PProcessInfo from re-export and __all__).

## 6. gateway.py — import + annotations

- [x] 6.1 Replace the `PProcessInfo` import (line ~76) with `ProcessInfo` from the same source (`infra.ssh.platform` re-export or `.protocol`).
- [x] 6.2 Update `SSHMachineGateway.pgrep` return annotation: `AsyncGenerator[PProcessInfo, None]` → `AsyncGenerator[ProcessInfo, None]`.
- [x] 6.3 Update `SSHMachineGateway.list_processes` return annotation: `AsyncGenerator[PProcessInfo, None]` → `AsyncGenerator[ProcessInfo, None]`.
- [x] 6.4 Update `gateway.py` `START_CHANGE_SUMMARY` (new LAST_CHANGE entry).

## 7. tests/unit/test_ssh_gateway.py — replace PProcessInfo

- [x] 7.1 Replace the `PProcessInfo` import with `ProcessInfo` (from `yascheduler.infra.ssh.platform`).
- [x] 7.2 Update `MagicMock(spec=PProcessInfo)` at line ~99 to `MagicMock(spec=ProcessInfo)`.
- [x] 7.3 Update `MagicMock(spec=PProcessInfo)` at line ~108 to `MagicMock(spec=ProcessInfo)`.
- [x] 7.4 Update `results: list[PProcessInfo]` at line ~930 to `results: list[ProcessInfo]`.
- [x] 7.5 Update `results: list[PProcessInfo]` at line ~945 to `results: list[ProcessInfo]`.
- [x] 7.6 The test file carries GRACE MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY markers. Update `START_CHANGE_SUMMARY` with a new LAST_CHANGE entry for v1.2.0 (replace `PProcessInfo` with `ProcessInfo` at 5 sites). No MODULE_CONTRACT/MODULE_MAP change needed unless the SCOPE/DEPENDS shift — verify `DEPENDS: M-PLATFORM-PROTOCOL` is still correct (it is: `ProcessInfo` now lives in protocol.py).

## 8. Knowledge graph + validation

- [x] 8.1 Update `docs/knowledge-graph.xml` `M-PLATFORM-PROTOCOL` `<annotations>`: add `<class-ProcessInfo PURPOSE="Frozen dataclass holding pid, name, command for a remote process" />`; remove `<class-PProcessInfo>` and `<class-PNode>` annotation elements.
- [x] 8.2 Update `M-PLATFORM-COMMON` `<annotations>`: remove the `<class-ProcessInfo PURPOSE="Attrs struct holding pid, name, command" />` line (ProcessInfo no longer lives here). Update `M-PLATFORM-COMMON` `<purpose>` from "Shared helpers for remote machine operations: process info, command execution." to "Shared helpers for remote machine operations: command execution." (drop "process info").
- [x] 8.3 Update `M-PLATFORM-LINUX` `<depends>`: remove `M-PLATFORM-COMMON` (after the import switch, `linux.py` imports `ProcessInfo` from `.protocol`, not `.common`; `run`/`run_bg` are consumed via `OuterRunCallable`, not direct import). New value: `M-PLATFORM-PROTOCOL, M-DOMAIN-ENGINE`.
- [x] 8.4 Update `M-PLATFORM-WINDOWS` `<depends>`: same as 8.3 — remove `M-PLATFORM-COMMON`. New value: `M-PLATFORM-PROTOCOL, M-DOMAIN-ENGINE`.
- [x] 8.5 Confirm `M-PLATFORM-PROTOCOL` `<depends>` stays `M-DOMAIN-ENGINE` (no change — protocol.py still TYPE_CHECKING-imports `EngineRepository` from domain).
- [x] 8.6 Run `python3 scripts/grace_check.py` — expect exit 0.
- [x] 8.7 Run `uv run ruff check .` — expect clean.
- [x] 8.8 Run `uv run ruff format --check .` — expect clean.
- [x] 8.9 Run `uv run lint-imports` — expect clean (watch for any new cycle: protocol.py must not import from common.py).
- [x] 8.10 Run `uv run pytest -m unit` — expect all unit tests pass, including `tests/unit/test_ssh_gateway.py` pgrep/list_processes tests.
- [x] 8.11 Run `openspec validate --all --json` — expect all items valid (change + main specs).

## 9. Spec sync (optional, can be done at archive time)

- [x] 9.1 After implementation is verified, sync the delta specs from `openspec/changes/prune-platform-protocols/specs/` into the main `openspec/specs/platform-adapters/spec.md` and `openspec/specs/ssh-gateway/spec.md` (run `/opsx-sync` or do it during archive).
- [x] 9.2 Re-run `openspec validate --all --json` after the sync to confirm main specs still validate.