## Why

The `reform-grace-logging` change established `get_logger("M-...")` as the
canonical module-level logger binding and added guard tests enforcing M-ID
validity and trace-only DEBUG discipline. However, it did NOT touch the
pre-existing pattern of injecting a `log: YaLogger` parameter into collaborator
constructors and threading it from the composition root. Today, `make_daemon`
creates a single `get_logger("M-APPLICATION-ORCHESTRATOR")` instance and passes
the SAME object into `Orchestrator`, `SSHMachineRepository`, `TaskDeployer`,
`OutputDownloader`, `OccupancyChecker`, and `CloudProvisionerImpl`.

This produces three concrete problems:

1. **Lost provenance.** All six collaborators log under the same logger name
   `yascheduler.M-APPLICATION-ORCHESTRATOR`. An operator reading the log file
   cannot distinguish a line from the orchestrator, the SSH repository, the
   cloud provisioner, or the download adapter. The `funcName` field helps, but
   the `[Module]` slot (the M-ID) is identical for all — defeating the purpose
   of M-ID-namespaced logger names.

2. **Constructor ceremony without a seam.** The `log` parameter is typed as
   `YaLogger` (a concrete class, not a Protocol). In tests, the same `YaLogger`
   or a mock is always supplied — the parameter provides no real swap point.
   `Orchestrator.__init__` has 16 parameters; `log` is one of four+ that exist
   only to be forwarded to collaborators. The `SSHMachineRepository` and
   `SSHMachineSession` constructors already use `log or get_logger("M-...")` as
   a fallback — a half-step that proves the injection is not load-bearing.

3. **Knowledge-graph ID leaking into runtime logger names.** The composition
   root (`di.py:138`) passes `get_logger("M-APPLICATION-ORCHESTRATOR")` as the
   logger for ALL collaborators. An operator sees `M-APPLICATION-ORCHESTRATOR`
   in every log line regardless of which module emitted it. With module-local
   binding, each module binds `get_logger("M-SSH-REPOSITORY")`,
   `get_logger("M-CLOUD-PROVISIONER")`, etc. — the M-ID in the log line matches
   the emitting module, as the `reform-grace-logging` design intended.

## What Changes

- Remove the `log` parameter from the `__init__` of seven collaborator
  classes: `Orchestrator`, `SSHMachineRepository`, `SSHMachineSession`,
  `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`,
  `CloudProvisionerImpl`. Each module SHALL bind its logger at module top
  via `logger = get_logger("M-...")` using the M-ID matching its
  `docs/knowledge-graph.xml` `<path>` mapping. **BREAKING** for any caller
  that passes `log=` to these constructors.

- Remove the `log` parameter from `make_daemon(config, log=None, *, clouds=None)`.
  The factory SHALL NOT create or thread a logger; each collaborator binds its
  own. **BREAKING** for any caller that passes `log=` to `make_daemon`.

- Remove the `log` parameter from function-level signatures: cloud provider
  `*_create_node` / `*_delete_node` callables (`az`, `hetzner`, `upcloud`,
  `vastai`), `get_or_create_ssh_key`, `resolve_adapter`,
  `select_provider_pure`, `_write_remote_file`, and the migration runner
  helpers (`_apply_sql_migration`, `_apply_py_migration`, `_record_py_tracker`,
  `_run_py_migrate`). Each owning module binds its own module-local logger.

- Remove `log: logging.Logger` from the `CreateNodeCallable` and
  `DeleteNodeCallable` Protocol `__call__` signatures in
  `infra/cloud/protocols.py`.

- `run_daemon(config, logger)` SHALL retain its `logger` parameter (used for
  signal-handler messages) but SHALL call `make_daemon(config)` without
  forwarding `logger`.

- Add a third guard test to `tests/unit/test_log_scope_discipline.py`:
  `test_no_injected_logger_in_collaborator_constructors` — AST-walk the seven
  collaborator modules and fail if any `__init__` method accepts a parameter
  named `log`.

- Update the `dependency-injection`, `cli`, `orchestrator`, and `testing-unit`
  specs to reflect the removed parameters and the new guard test.

## Capabilities

### Modified Capabilities

- `dependency-injection`: `make_daemon` drops its `log` parameter; the three
  stateless collaborators (`TaskDeployer`, `OutputDownloader`,
  `OccupancyChecker`) are constructed without `log`; `CloudProvisionerImpl`
  is constructed without `log`; `SSHMachineRepository` is constructed without
  `log`. Each collaborator binds its own module-local logger.

- `cli`: `run_daemon` calls `make_daemon(config)` instead of
  `make_daemon(config, logger)`. The `run_daemon` signature itself is
  unchanged (it still takes `logger` for signal-handler messages).

- `orchestrator`: the `Orchestrator.__init__` SHALL NOT accept a `log`
  parameter; the orchestrator module binds `get_logger("M-APPLICATION-ORCHESTRATOR")`
  at module top.

- `testing-unit`: a third guard test enforces that none of the seven
  collaborator classes accept a `log` parameter in `__init__`.

## Impact

- **Constructor signatures change** (BREAKING) for: `Orchestrator`,
  `SSHMachineRepository`, `SSHMachineSession`, `TaskDeployer`,
  `OutputDownloader`, `OccupancyChecker`, `CloudProvisionerImpl`,
  `make_daemon`.

- **Function signatures change** (BREAKING) for: `az_create_node`,
  `az_delete_node`, `hetzner_create_node`, `hetzner_delete_node`,
  `upcloud_create_node`, `upcloud_delete_node`, `vastai_create_node`,
  `vastai_delete_node`, `get_or_create_ssh_key`, `resolve_adapter`,
  `select_provider_pure`, `_write_remote_file`, migration runner helpers.

- **Protocol signatures change** (BREAKING) for: `CreateNodeCallable.__call__`,
  `DeleteNodeCallable.__call__`.

- **Wiring**: `yascheduler/entrypoints/di.py` (remove `log` threading),
  `yascheduler/entrypoints/cli/daemon_common.py` (drop `logger` from
  `make_daemon` call).

- **Callsite rewrites**: each of the ~12 affected modules adds
  `from yascheduler.shared import get_logger` (if not already present) and
  `logger = get_logger("M-...")` at module top; replaces `self._log` / `self.log`
  references with the module-local `logger`.

- **Test updates**: tests constructing the affected classes must drop the `log=`
  argument. The `test_log_scope_discipline.py` guard test gains a third
  assertion. Provider-selection unit tests (`test_provider_selection.py`) drop
  the `log` fixture parameter.

- **No new runtime dependencies.** No DB schema changes. No CLI surface changes
  (the six entry points and `Yascheduler` public API are untouched).

### Non-Goals

- Does NOT remove `log` from the `Migration` base class
  (`infra/persistence/migration_base.py`). The `log` parameter there is part
  of the migration-author API contract: each `.py` migration script subclasses
  `Migration` and uses `self.log.info(...)`. Removing it would break every
  existing migration script and change the migration authoring surface. This
  is a separate concern.

- Does NOT change `run_daemon`'s `logger` parameter. The daemon runtime uses
  it for signal-handler messages (`logger.info("Received signal ...")`).
  Switching `run_daemon` to a module-local logger is a smaller follow-up that
  also requires updating the `cli` spec's `run_daemon` signature.

- Does NOT change the `LogFormatter`, the `configure_logger` function, or the
  `YaLogger` / `get_logger` factory. Those are owned by `reform-grace-logging`.

- Does NOT change the set of emitted log messages or their levels. Only the
  logger binding mechanism changes (injected → module-local).

- Does NOT phase or stage the migration — single big-bang change, consistent
  with the `reform-grace-logging` approach.
