# Explore Brief — cleanup-unused-repository-symbols

## Problem

`yascheduler/infra/ssh/repository.py` (505 ln) and the matching
`MachineRepository` Protocol in `yascheduler/domain/ports.py` carry nine
methods with zero production callers — dead code accumulated during
`decompose-ssh-gateway`. They enlarge the public port surface and the
concrete class for no benefit, and they will all be removed anyway by the
follow-up `session-based-machine-handle` change. Removing them first in a
zero-risk change keeps the later refactor diff honest.

## Alternatives considered

### A. Fold the deletions into the entity-handle change proposal
Rejected — mixing mechanical dead-code removal with semantic refactoring
forces reviewers to context-switch between two review modes (verify-zero-
callers vs. preserve-invariants). GRACE-lite prefers proportional,
focused changes. Also, the entity-handle change's `tasks.md` will
reference method names that this change removes; landing this first
prevents merge conflicts on `repository.py` and `ports.py`.

### B. Delete only the concrete-class methods, keep the Protocol intact
Rejected — leaves the Protocol declaring methods no concrete class
implements, breaking `@runtime_checkable` semantics for any future
implementer.

### C. Delete everything in one sweep (concrete + Protocol + tests)
Accepted — this is the change.

## Mapping table — symbols to remove

| Symbol                                | Location                                | Prod callers | Test callers          | Action |
|---|---|---|---|---|
| `SSHMachineRepository.get_conn`         | `infra/ssh/repository.py`                 | 0            | 0                     | DELETE |
| `SSHMachineRepository.keys`             | `infra/ssh/repository.py`                 | 0            | `test_ssh_gateway.py` | DELETE |
| `SSHMachineRepository.items`            | `infra/ssh/repository.py`                 | 0            | `test_ssh_gateway.py` | DELETE |
| `SSHMachineRepository.register_machine` | `infra/ssh/repository.py`                 | 0            | `test_ssh_gateway.py` | DELETE |
| `SSHMachineRepository.get_adapter`      | `infra/ssh/repository.py`                 | 0            | `test_ssh_gateway.py` | DELETE |
| `SSHMachineRepository.get_platforms`    | `infra/ssh/repository.py`                 | 0            | `test_ssh_gateway.py` | DELETE |
| `SSHMachineRepository.get_data_dir`     | `infra/ssh/repository.py`                 | 0            | `test_ssh_gateway.py` | DELETE |
| `SSHMachineRepository.get_engines_dir`  | `infra/ssh/repository.py`                 | 0            | `test_full_cycle.py` (e2e) | DELETE |
| `SSHMachineRepository.get_tasks_dir`    | `infra/ssh/repository.py`                 | 0            | `test_ssh_gateway.py` | DELETE |
| `MachineRepository.get_conn` (Protocol) | `domain/ports.py`                         | 0            | —                     | DELETE |
| `MachineRepository.get_adapter` (Protocol) | `domain/ports.py`                      | 0            | —                     | DELETE |
| `MachineRepository.get_platforms` (Protocol) | `domain/ports.py`                   | 0            | —                     | DELETE |
| `MachineRepository.get_data_dir` (Protocol) | `domain/ports.py`                    | 0            | —                     | DELETE |
| `MachineRepository.get_engines_dir` (Protocol) | `domain/ports.py`                | 0            | —                     | DELETE |
| `MachineRepository.get_tasks_dir` (Protocol) | `domain/ports.py`                    | 0            | —                     | DELETE |

Symbols that STAY (have production callers and are NOT in scope):
`connect`, `disconnect`, `disconnect_all`, `list_free`, `list_connected`,
`contains`, `__contains__`, `__len__`, `get_machine_state`, `update_machine`,
`occupy`, `release`, `get_path`, `get_quote`, `get_hostname`,
`install_monitor`, `cancel_monitor`, `_get_machine_state` (private),
`register_machine` is removed despite being a "test hook" — see Q1 below.

## Cross-module data flows

None. Pure deletion — no method gains new callers, no method changes
signature, no caller migrates. The only edits outside `repository.py` /
`ports.py` are test removals.

## Open questions (resolved)

### Q1. Should `register_machine` stay as a documented test hook?
**Decision:** DELETE. It is referenced only by `test_ssh_gateway.py:649`
to set up fixture state. Tests can construct the state via the public
`connect` path, or via a fixture-local helper that pokes
`repository._machines[ip] = state` directly (the existing tests already
do this in `test_ssh_gateway_bg_tasks.py:215`). Removing it eliminates
a back-door that bypasses the connect lifecycle.

### Q2. Should `_get_machine_state` (private, used 11× in production) be touched?
**Decision:** NO, out of scope. It is the de-facto operations API and
will be replaced by the entity-handle redesign. This change is purely
about zero-caller dead code.

### Q3. Are specs (delta specs) needed?
**Decision:** YES — `ssh-machine-repository` and `domain-ports` both
list these methods as Requirements. Removing them is a spec-level
requirement change (the Method Inventory requirements explicitly
enumerate each method). Delta specs will mark the methods removed.
