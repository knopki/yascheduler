## Why

`SSHMachineRepository` (`infra/ssh/repository.py`, 505 ln) and the matching
`MachineRepository` Protocol (`domain/ports.py`) carry nine methods with
**zero production callers** — `get_conn`, `keys`, `items`, `register_machine`,
`get_adapter`, `get_platforms`, `get_data_dir`, `get_engines_dir`,
`get_tasks_dir`. They accumulated during `decompose-ssh-gateway` as the
former god-class surface was preserved wholesale "just in case." They
inflate the public port surface for no benefit, mislead readers into
thinking the methods are reachable, and will all be removed by the
planned follow-up `session-based-machine-handle` change anyway. Removing
them first in a zero-risk focused change keeps the later refactor's diff
honest (every remaining line in that diff then means something).

## What Changes

- **DELETE** nine concrete methods from `SSHMachineRepository`:
  `get_conn`, `keys`, `items`, `register_machine`, `get_adapter`,
  `get_platforms`, `get_data_dir`, `get_engines_dir`, `get_tasks_dir`.
- **DELETE** six method declarations from the `MachineRepository`
  Protocol in `domain/ports.py`: `get_conn`, `get_adapter`,
  `get_platforms`, `get_data_dir`, `get_engines_dir`, `get_tasks_dir`.
  (The other three — `keys`, `items`, `register_machine` — were never
  on the Protocol; they were concrete-class-only test hooks.)
- **DELETE** the matching test methods/fakes:
  - `tests/unit/test_ssh_gateway.py`: `TestPropertyHelpers` class
    (`test_get_adapter`, `test_get_platforms`, `test_get_hostname`'s
    siblings, `test_get_data_dir`, `test_get_engines_dir`,
    `test_get_tasks_dir`, `test_keys`, `test_items`,
    `test_register_machine`). Note: the file's `repository()` fixture
    does NOT use `register_machine` — tests requiring pre-populated
    state already poke `repository._machines[ip] = state` directly.
  - `tests/unit/test_domain_ports.py`: the corresponding declarations
    on the test fake `FakeMachineRepository` (if any).
  - `tests/e2e/test_full_cycle.py`: the single
    `repository.get_engines_dir(ssh_container["host"])` call site
    replaced by reading the same value from the existing
    `remote_defaults.engines_dir` config (which is the value that
    `connect` was called with — the e2e test was using the accessor
    as a round-trip check; the config value is the source of truth).
- **NO BEHAVIOR CHANGE.** No method signature changes for the symbols
  that stay. No caller migrates. No production call site is touched.
- **NOT IN SCOPE** (explicitly deferred to `session-based-machine-handle`):
  `_get_machine_state` (private, 11 prod callers), `get_path` /
  `get_quote` / `get_hostname` / `occupy` / `release` / `update_machine`
  (wrappers with prod callers), `install_monitor` / `cancel_monitor`
  (genuine mechanism), and any structural redesign.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `ssh-machine-repository`: The `MachineRepository port` requirement's
  method inventory shrinks — `get_conn`, `get_adapter`, `get_platforms`,
  `get_data_dir`, `get_engines_dir`, `get_tasks_dir` are removed from
  the Protocol's accessor-getters and connection-lifecycle clauses. The
  `SSHMachineRepository implements MachineRepository` requirement's
  concrete-class inventory additionally loses `keys`, `items`,
  `register_machine` (test-only hooks that were never on the Protocol).
  See delta spec.
- `domain-ports`: The `MachineRepository port` requirement's accessor
  list (mirror of `ssh-machine-repository`'s) is updated identically.
  See delta spec.

## Impact

- **Code:**
  - MODIFIED: `yascheduler/infra/ssh/repository.py` (lose 9 methods,
    ~50 ln), `yascheduler/domain/ports.py` (lose 6 Protocol methods,
    ~10 ln), `tests/unit/test_domain_ports.py` (drop matching fake
    methods).
  - MODIFIED (test removals): `tests/unit/test_ssh_gateway.py` (drop
    `TestPropertyHelpers` + `register_machine`-based fixture setup,
    ~80 ln), `tests/e2e/test_full_cycle.py` (1 line: replace accessor
    with config read).
  - REMOVED total: ~150 ln across 5 files
    (`infra/ssh/repository.py`, `domain/ports.py`,
    `tests/unit/test_domain_ports.py`, `tests/unit/test_ssh_gateway.py`,
    `tests/e2e/test_full_cycle.py`).
- **APIs:** The `MachineRepository` Protocol narrows. This is a
  **narrowing** (removing requirements is non-breaking for consumers —
  any class that satisfied the old Protocol still satisfies the new
  one). No production consumer of the Protocol called any removed
  method (audit-verified). The `yascheduler` package's public surface
  (CLI commands, `Yascheduler` class, INI, DB schema, AiiDA plugin) is
  **unaffected** — `MachineRepository` is internal infrastructure.
- **Dependencies:** Unchanged.
- **DB schema:** Unchanged.
- **INI config:** Unchanged.
- **CLI commands:** Unchanged.
- **AiiDA scheduler plugin:** Unaffected.
- **Tests:** Net deletion. The removed tests were pure coverage of the
  removed symbols (no behavior loss). The `test_full_cycle.py` edit
  preserves the e2e assertion intent (read the engines_dir that
  `connect` was called with) by sourcing it from the same config object
  the daemon wiring uses.
- **GRACE-lite:** `M-SSH-REPOSITORY` annotation list in
  `docs/knowledge-graph.xml` loses the corresponding `<fn-*>` entries.
  `grace_check.py` must pass.
- **Rollback:** `git revert` — no persisted state, no config, no flag.
