# Explore Brief: prune-platform-protocols

## Goal

Two cleanups in `yascheduler/infra/ssh/platform/protocol.py`:

1. **Delete `PNode` Protocol** — dead code, zero consumers.
2. **Consolidate `PProcessInfo` into `ProcessInfo`** — move `ProcessInfo`
   dataclass from `common.py` to `protocol.py`; remove `PProcessInfo`;
   update all annotations and consumers to use `ProcessInfo`.

## Alternatives considered and rejected

- **Variant A (status quo)**: keep `PProcessInfo` as a cycle-breaker between
  `protocol.py` and `common.py`. Rejected because moving `ProcessInfo` into
  `protocol.py` makes it the single canonical contract location AND still
  breaks the cycle (since `common.py` only needs `QuoteCallable` from
  `protocol.py`, and `protocol.py` would now own `ProcessInfo` — no
  `protocol → common` edge anymore).
- **Variant C (type alias `PProcessInfo = ProcessInfo`)**: rejected — a
  type alias in `protocol.py` still requires importing `ProcessInfo` from
  `common.py`, recreating the cycle. No benefit over Variant B.

## Final approach (Variant B)

- `ProcessInfo` (frozen dataclass: `pid:int, name:str, command:str`) moves
  from `infra/ssh/platform/common.py` to `infra/ssh/platform/protocol.py`.
- `PProcessInfo` Protocol deleted.
- `PNode` Protocol deleted.
- `common.py` keeps `run` and `run_bg` only; its MODULE_CONTRACT/MODULE_MAP
  updated to drop `ProcessInfo`.
- All `AsyncGenerator[PProcessInfo, None]` annotations become
  `AsyncGenerator[ProcessInfo, None]`.

## Affected files (blast radius)

| File | Change |
|------|--------|
| `infra/ssh/platform/protocol.py` | +`ProcessInfo` dataclass; −`PProcessInfo`; −`PNode`; update MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY |
| `infra/ssh/platform/common.py` | −`ProcessInfo` class + import; update MODULE_CONTRACT SCOPE, MODULE_MAP, CHANGE_SUMMARY |
| `infra/ssh/platform/linux.py` | `from .common import ProcessInfo` → `from .protocol import ProcessInfo`; drop `PProcessInfo` import; update annotations (4 sites: import, 2 contracts, 2 signatures) |
| `infra/ssh/platform/windows.py` | same as linux.py |
| `infra/ssh/platform/__init__.py` | drop `PProcessInfo`, `PNode` from protocol re-export block and `__all__`; `ProcessInfo` import source changes from `.common` to `.protocol` (line 56) |
| `infra/ssh/gateway.py` | replace `PProcessInfo` import + 2 annotations with `ProcessInfo` |
| `tests/unit/test_ssh_gateway.py` | replace `PProcessInfo` (5 sites: import, 2 MagicMock spec=, 2 list[] annotations) with `ProcessInfo` |
| `docs/knowledge-graph.xml` | update M-PLATFORM-PROTOCOL annotations (add `class-ProcessInfo`, remove `class-PProcessInfo`, `class-PNode`) |

## Cross-module data flows (unchanged)

```
linux_list_processes(conn) -> AsyncGenerator[ProcessInfo, None]
  yields: ProcessInfo(int(parts[0]), *parts[1:3])

windows_list_processes(conn) -> AsyncGenerator[ProcessInfo, None]
  yields: ProcessInfo(**data)

gateway.pgrep(ip, pattern) -> AsyncGenerator[ProcessInfo, None]
  delegates to state.adapter.pgrep(...)
gateway.list_processes(ip) -> AsyncGenerator[ProcessInfo, None]
  delegates to state.adapter.list_processes(...)

ListProcessesCallable / PgrepCallable (in protocol.py)
  __call__ -> AsyncGenerator[ProcessInfo, None]   (was PProcessInfo)
```

No runtime behavior change. Pure type relocation + dead code removal.

## Open questions

- None material. Precedent for deleting `P*` Protocols in favor of domain
  types already established by `engine-to-domain-frozen` (deleted `PEngine`,
  `PEngineRepository`). The `platform-adapters` spec already documents
  those removals as scenarios — this change adds analogous scenarios for
  `PProcessInfo` (consolidated) and `PNode` (removed).

## Spec capability mapping

- **Modified capability `platform-adapters`**: add requirements/scenarios
  that `PProcessInfo` and `PNode` SHALL NOT exist; `ProcessInfo` SHALL live
  in `protocol.py`; platform modules import it from `protocol.py`, not
  `common.py`.
- **Modified capability `ssh-gateway`**: pgrep/list_processes annotations
  use `ProcessInfo` (was `PProcessInfo`). Likely a scenario-level note, not
  a new requirement.

## Precedent and constraints

- Public API stability (AGENTS.md): `ProcessInfo` is exported from
  `infra/ssh.platform` package `__all__` — its public name stays the same;
  only its source module within the package changes. No external break.
- GRACE-lite: update MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY on every
  edited governed file; update `docs/knowledge-graph.xml` annotations.
- Size limits: protocol.py grows by ~7 lines (the dataclass), shrinks by
  ~9 lines (two Protocol classes) — net smaller. common.py shrinks by ~6
  lines.