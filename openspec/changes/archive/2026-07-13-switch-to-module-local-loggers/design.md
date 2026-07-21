## Context

The `reform-grace-logging` change (active, not yet archived) introduced the
`get_logger(name) -> YaLogger` factory, M-ID-namespaced logger names, the
`LogFormatter`, and two guard tests (`test_no_raw_debug_calls_in_yascheduler`
and `test_logger_names_are_real_m_ids`). It converted ~30 callsites from
hand-assembled `[Module][function][BLOCK] kv` strings to `log.trace("BLOCK",
**fields)` calls. But it did NOT touch the pre-existing dependency-injection
pattern: `make_daemon` creates one logger and threads it into every
collaborator constructor.

Today's state:

- `make_daemon` (`di.py:137-138`): `log = get_logger("M-APPLICATION-ORCHESTRATOR")`,
  then passes `log` to `SSHMachineRepository(log=log)`, `TaskDeployer(log)`,
  `OutputDownloader(log)`, `OccupancyChecker(log)`, `CloudProvisionerImpl(...,
  log=log)`, and `Orchestrator(..., log=log)`.
- All six collaborators store `self._log = log` (or `self.log = log` for the
  frozen dataclass `CloudProvisionerImpl`) and use `self._log.trace(...)` /
  `self._log.info(...)` / etc.
- `SSHMachineRepository.__init__` and `SSHMachineSession.__init__` already use
  `log or get_logger("M-SSH-REPOSITORY")` / `log or get_logger("M-SSH-SESSION")`
  as fallbacks — a half-step that demonstrates the injection is not
  load-bearing.
- Additionally, several cloud provider functions (`az_create_node`,
  `hetzner_delete_node`, etc.), helper functions (`select_provider_pure`,
  `resolve_adapter`, `get_or_create_ssh_key`, `_write_remote_file`), and
  migration runner helpers take `log` as a positional/keyword parameter.
- The `CreateNodeCallable` and `DeleteNodeCallable` Protocols in
  `infra/cloud/protocols.py` declare `log: logging.Logger` as the first
  parameter of `__call__`.

The `reform-grace-logging` guard test `test_logger_names_are_real_m_ids` already
enforces "no `logging.getLogger(...)` module-level bindings outside `log.py`"
and "every `get_logger("M-...")` literal references a real M-ID". But there is
no guard against the injected-logger pattern — a module can accept `log` as a
constructor parameter and store it on `self` without violating any test.

## Goals / Non-Goals

**Goals:**

- Remove the `log` parameter from seven collaborator constructors and from
  `make_daemon`, so each module binds its own logger via
  `get_logger("M-...")` at module top.
- Remove the `log` parameter from function-level signatures (cloud providers,
  helpers, migration runner internals) and from the `CreateNodeCallable` /
  `DeleteNodeCallable` Protocols.
- Restore log provenance: each module's log lines carry that module's M-ID,
  not the composition root's M-ID.
- Add a guard test that statically prevents regressions (no collaborator
  `__init__` accepts a `log` parameter).
- Update the affected specs (`dependency-injection`, `cli`, `orchestrator`,
  `testing-unit`) to reflect the new contract.

**Non-Goals:**

- No change to the `Migration` base class — `log` is part of the
  migration-author API.
- No change to `run_daemon`'s `logger` parameter — it's used for signal-handler
  messages; switching it to module-local is a smaller follow-up.
- No change to `YaLogger`, `get_logger`, `LogFormatter`, or `configure_logger`.
- No change to emitted messages, levels, or trace blocks.
- No phased rollout — single big-bang change.

## Decisions

### Decision 1: Module-local `get_logger` binding, not constructor injection

**Choice.** Each affected module adds at module top:

```python
from yascheduler.shared import get_logger

logger = get_logger("M-SSH-REPOSITORY")  # or the module's M-ID
```

All `self._log` / `self.log` references become `logger`. The `log` parameter
is removed from every collaborator `__init__` and from `make_daemon`.

**Rationale.** The standard Python convention is `logger =
logging.getLogger(__name__)` at module top. The `reform-grace-logging` change
already established this convention for modules that DON'T use injection
(`allocate_task.py`, `consume_task.py`, `webhook.py`, `postgres_migrations.py`,
etc. all bind `get_logger("M-...")` at module top). The seven collaborator
classes are the inconsistent outliers — they use injection because the
composition root historically created the logger. With the `get_logger` factory
in place, the injection provides no benefit: the factory is idempotent (same
name → same cached `YaLogger` instance), so `get_logger("M-SSH-REPOSITORY")`
called at module top in `repository.py` returns the same object that
`make_daemon` would have passed via `log = get_logger("M-SSH-REPOSITORY")`.

**Tradeoff accepted.** Modules lose the ability to receive a custom logger at
construction time. In practice, no test or production code actually swaps the
logger — the parameter is always `get_logger("M-...")` or `None` (falling
back to the same `get_logger`). The `caplog` fixture and `log_records` e2e
fixture work via handler attachment on the `"yascheduler"` parent logger, which
captures all descendant records regardless of how the logger was bound. So
test observability is unchanged.

### Decision 2: `CloudProvisionerImpl` — remove `log` dataclass field

**Choice.** `CloudProvisionerImpl` is a `@dataclass(frozen=True)` with `log:
YaLogger` as a field. Remove the field; the module binds
`logger = get_logger("M-CLOUD-PROVISIONER")` at module top. All `self.log`
references become `logger`.

**Rationale.** A frozen dataclass field for a logger is the worst of both
worlds: it forces every construction site to pass `log=`, and the field is
not configuration — it's infrastructure. Removing it simplifies the dataclass
to its actual configuration fields (`adapters`, `configs`,
`machine_repository`, `local_config`, `remote_config`, `engines`).

### Decision 3: Cloud provider functions and Protocols — drop `log` parameter

**Choice.** The provider functions (`az_create_node`, `az_delete_node`,
`hetzner_create_node`, `hetzner_delete_node`, `upcloud_create_node`,
`upcloud_delete_node`, `vastai_create_node`, `vastai_delete_node`) and helper
functions (`get_or_create_ssh_key`, `resolve_adapter`,
`select_provider_pure`, `_write_remote_file`) drop the `log` parameter. Each
owning module binds `logger = get_logger("M-...")` at module top.

The `CreateNodeCallable` and `DeleteNodeCallable` Protocols in
`infra/cloud/protocols.py` drop `log: logging.Logger` from their `__call__`
signatures.

**Rationale.** These functions are called from `CloudProvisionerImpl` methods,
which currently pass `self.log` (soon to be the module-local `logger`). The
functions are stateless — they don't store the logger; they just call
`log.trace(...)` / `log.error(...)` within their body. A module-local logger
serves identically. The Protocol signature change is forced: the concrete
implementations no longer accept `log`, so the Protocol must drop it too.

**Tradeoff accepted.** The provider functions lose the ability to log under a
caller-chosen logger name. In practice, the caller was always
`CloudProvisionerImpl` passing `self.log`, which was `get_logger("M-APPLICATION-ORCHESTRATOR")`
— the wrong M-ID for a cloud-provider function anyway. With module-local
binding, `az_create_node` logs under `yascheduler.M-CLOUD-PROVIDER-AZ`, which
is correct.

### Decision 4: `run_daemon` keeps `logger`, stops forwarding to `make_daemon`

**Choice.** `run_daemon(config, logger)` is unchanged in signature. It keeps
`logger` for signal-handler messages (`logger.info(f"Received signal
{signame}")`). But the `make_daemon` call inside it changes from
`make_daemon(config, logger)` to `make_daemon(config)`.

**Rationale.** Switching `run_daemon` to a module-local logger is a clean
follow-up but requires changing the `cli` spec's `run_daemon` signature
requirement. Keeping `run_daemon(config, logger)` and only dropping the
`make_daemon` forwarding minimizes the spec delta. The `logger` parameter in
`run_daemon` is the root logger returned by `configure_logger` — it's used
directly for a handful of signal-handler `info()` calls, not threaded into
collaborators.

### Decision 5: Migration base class is out of scope

**Choice.** The `Migration` base class (`infra/persistence/migration_base.py`)
keeps its `log: Logger` constructor parameter. Migration scripts (`.py` files
in `sql/migrations/`) subclass `Migration` and use `self.log.info(...)`.

**Rationale.** Each `.py` migration is a standalone script authored by a
migration writer. The `log` parameter is part of the migration-author API
contract: the runner instantiates `Migration(config, conn, log)` and the
subclass uses `self.log`. Switching to module-local binding would require
every migration script to bind its own `get_logger(...)` at module top — but
migration scripts are not in `yascheduler/` (they're in `sql/migrations/`) and
are not governed by the knowledge graph. This is a different concern with its
own trade-offs and is left for a separate change.

### Decision 6: Guard test — AST scan for `log` parameters in collaborator `__init__`

**Choice.** Add a third test to `tests/unit/test_log_scope_discipline.py`:
`test_no_injected_logger_in_collaborator_constructors`. The test AST-walks the
seven collaborator modules and fails if any `__init__` method (or the class
itself for the frozen dataclass) accepts a parameter named `log`.

The seven checked modules:
- `yascheduler/application/orchestrator.py` — `Orchestrator`
- `yascheduler/infra/ssh/repository.py` — `SSHMachineRepository`
- `yascheduler/infra/ssh/session.py` — `SSHMachineSession`
- `yascheduler/infra/ssh/operations/deployment.py` — `TaskDeployer`
- `yascheduler/infra/ssh/operations/download.py` — `OutputDownloader`
- `yascheduler/infra/ssh/operations/occupancy.py` — `OccupancyChecker`
- `yascheduler/infra/cloud/manager.py` — `CloudProvisionerImpl`

**Rationale.** The existing two guard tests enforce M-ID validity and
trace-only DEBUG discipline. A third guard test prevents the injected-logger
pattern from silently returning — without it, a developer could reintroduce
`log: YaLogger` in a constructor and no test would catch it. The AST check is
cheap, deterministic, and runs under `-m unit` with no external resources.

## Risks / Trade-offs

- **BREAKING constructor signatures** → Any external code constructing the
  seven collaborator classes or calling `make_daemon` with `log=` breaks.
  Mitigation: `make_daemon` is NOT in the AGENTS.md public-interface-stability
  list (only the six CLI commands and `Yascheduler` class are). The seven
  collaborator classes are internal. The only callers are `make_daemon`
  (composition root), `run_daemon` (daemon core), and tests — all updated in
  the same change.

- **Log lines change M-ID** → Operators grepping logs for
  `yascheduler.M-APPLICATION-ORCHESTRATOR` will see fewer lines (only
  orchestrator-emitted ones). Lines from SSH/cloud collaborators now appear
  under their own M-IDs. Mitigation: this is the intended improvement —
  provenance is restored. The `log_records` test fixture captures via the
  `"yascheduler"` parent logger, so test assertions are unaffected (they
  filter by `record.block` and `record.fields`, not by `record.name`).

- **Protocol signature change breaks provider implementations** → All eight
  `*_create_node` / `*_delete_node` functions must drop `log` from their
  signatures in the same change. Mitigation: the change is mechanical and
  big-bang; the four provider modules (`az.py`, `hetzner.py`, `upcloud.py`,
  `vastai.py`) are all in `yascheduler/infra/cloud/providers/`.

- **`CloudProvisionerImpl` frozen dataclass field removal** → Removing a field
  from a frozen dataclass changes its `__init__` signature, `__eq__`,
  `__hash__`, and `repr`. Mitigation: no test asserts on the `log` field's
  presence in `__eq__`/`__hash__`/`repr`; the field was infrastructure, not
  identity.

- **Guard test false positives** → A class with a method that legitimately
  accepts `log` as a parameter name (unrelated to logger injection) would trip
  the guard. Mitigation: the test scopes to the seven named modules only, not
  a package-wide AST walk. Adding an eighth class requires explicitly updating
  the test's module list.
