## Why

`infra/ssh/platform/protocol.py` carries two Protocol classes whose cost now
exceeds their value. `PNode` (ip, username) is dead code with zero consumers
outside its own re-export. `PProcessInfo` (pid, name, command) is a structural
shadow of the `ProcessInfo` dataclass in `common.py`, kept only to break an
import cycle that no longer needs breaking once `ProcessInfo` itself moves
into `protocol.py`. Removing both eliminates duplicate field definitions and
makes `protocol.py` the single canonical location for the platform's data
contracts. Precedent: `engine-to-domain-frozen` already deleted `PEngine` and
`PEngineRepository` from this same module for the same reason.

## What Changes

- **Remove `PNode` Protocol** from `infra/ssh/platform/protocol.py` and from
  the `__init__.py` re-export block and `__all__`.
- **Remove `PProcessInfo` Protocol** from `infra/ssh/platform/protocol.py` and
  from the `__init__.py` re-export block and `__all__`.
- **Move `ProcessInfo` dataclass** (frozen, fields `pid:int, name:str,
  command:str`) from `infra/ssh/platform/common.py` to
  `infra/ssh/platform/protocol.py`.
- **Update `common.py`** to drop the `ProcessInfo` class and its
  `from dataclasses import dataclass` (when no longer used there); update its
  MODULE_CONTRACT SCOPE and MODULE_MAP to reflect that it now hosts only
  `run` and `run_bg`.
- **Update platform modules** (`linux.py`, `windows.py`) to import
  `ProcessInfo` from `.protocol` instead of `.common`, and to annotate
  `list_processes`/`pgrep` return types as `AsyncGenerator[ProcessInfo, None]`
  instead of `AsyncGenerator[PProcessInfo, None]`.
- **Update `infra/ssh/platform/__init__.py`** so `ProcessInfo` is imported
  from `.protocol` (instead of `.common`); `run` and `run_bg` continue to be
  imported from `.common`. `ProcessInfo` stays in `__all__` unchanged.
- **Update `gateway.py`** to import `ProcessInfo` from
  `infra.ssh.platform` (re-export unchanged) or `.protocol`, replacing
  `PProcessInfo` in the `pgrep` and `list_processes` annotations.
- **Update `tests/unit/test_ssh_gateway.py`** to replace `PProcessInfo`
  (import, two `MagicMock(spec=...)`, two `list[...]` annotations) with
  `ProcessInfo`.
- **Update GRACE-lite artifacts**: MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY
  on every governed file touched; update
  `docs/knowledge-graph.xml` `M-PLATFORM-PROTOCOL` annotations (add
  `class-ProcessInfo`, remove `class-PProcessInfo` and `class-PNode`).
- No runtime behavior change. `ProcessInfo` remains exported from the public
  package surface `yascheduler.infra.ssh.platform` under the same name; only
  its source module within the package changes.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `platform-adapters`: require that `PProcessInfo` and `PNode` Protocols
  SHALL NOT exist in `infra/ssh/platform/protocol.py`; require that
  `ProcessInfo` SHALL be defined in `infra/ssh/platform/protocol.py` and
  imported from there (or the package re-export) by platform modules and the
  gateway, not from `common.py`.
- `ssh-gateway`: `SSHMachineGateway.pgrep` and `SSHMachineGateway.list_processes`
  return `AsyncGenerator[ProcessInfo, None]` (was `PProcessInfo`). No new
  requirement, scenario-level clarification under the existing gateway
  requirement.

## Impact

**Code**: `yascheduler/infra/ssh/platform/protocol.py` (move dataclass in,
delete two Protocols), `common.py` (dataclass out), `linux.py`, `windows.py`,
`__init__.py`, `gateway.py` (import/annotation changes), one test file.

**Public API surface**: `yascheduler.infra.ssh.platform.ProcessInfo` is
unchanged (still in `__all__`). `PProcessInfo` and `PNode` are removed from
the public re-export — they were never used by external consumers (verified:
zero references outside `infra/ssh/platform/` and its test). No documented
external user of the `P*` names exists.

**Dependencies**: none added or removed.

**DB schema / config / CLI**: untouched.

**Knowledge graph**: `docs/knowledge-graph.xml` `M-PLATFORM-PROTOCOL`
annotations updated in the same change.

**Specs**: `openspec/specs/platform-adapters/spec.md` gains scenarios for
the two Protocol removals and the `ProcessInfo` relocation;
`openspec/specs/ssh-gateway/spec.md` gains a scenario noting the
`ProcessInfo` return type of `pgrep`/`list_processes`.