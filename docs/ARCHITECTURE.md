# ARCHITECTURE.md — yascheduler

> **Authoritative structure reference**: `docs/knowledge-graph.xml` is the
> canonical source for module inventory, dependency edges, data flows, and
> cross-module relationships. This document provides architectural rationale
> and design decisions not captured in the graph. When the two diverge, the
> graph is correct; update this document afterwards.

---

## 1. Overview

yascheduler follows a hexagonal (ports-and-adapters) architecture with a
domain core and four adapter families. The domain layer has no yascheduler
imports. The application layer orchestrates use cases against domain ports
and the Unit-of-Work boundary. Adapters implement ports for PostgreSQL,
SSH, cloud providers, CLI, and webhook notifications. A single composition
root (`di.py`) wires the graph per entry point.

```txt
┌─────────────────────────────────────────────────────────────────┐
│  DOMAIN                                                          │
│  model.py        Task, Node, ConnectedMachine, Engine,           │
│                  TaskContext, TaskStatus, ProcessResult          │
│                  (frozen dataclasses; Task records/pulls events) │
│  services.py     match_task_to_node                              │
│  ports.py        TaskRepository, NodeRepository,                 │
│                  MachineGateway, CloudProvisioner (Protocols)    │
│  events.py       DomainEvent, Event union, Task* events          │
│  exceptions.py   DomainError hierarchy                           │
│                  (depends on: stdlib only)                        │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  ADAPTERS: PERSISTENCE                                           │
│  postgres.py         PostgresTaskRepository,                     │
│                      PostgresNodeRepository                      │
│  postgres_uow.py     PostgresUnitOfWork                          │
│  postgres_schema.py  apply_schema (BEGIN/COMMIT DDL)             │
│  sql_loader.py       load_query(name) → cached SQL strings       │
│  exceptions.py       UnitOfWorkNotInitializedError               │
│  sql/                task/*.sql, node/*.sql, schema.sql          │
│                  (depends on: domain, message bus)               │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  APPLICATION                                                     │
│  submit_task.py      SubmitTask use case                         │
│  allocate_task.py    AllocateTask use case                       │
│  consume_task.py     ConsumeTask use case                        │
│  deallocate_nodes.py DeallocateNodes use case                    │
│  orchestrator.py     Producer-consumer daemon loops              │
│  uow.py              AbstractUnitOfWork Protocol                 │
│  message_bus.py      In-process event dispatcher                 │
│                  (depends on: domain)                            │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  ADAPTERS: SSH, CLOUD, CLI, NOTIFIER                             │
│  ssh/gateway.py             SSHMachineGateway (MachineGateway)   │
│  ssh/helpers.py             Shared SSH infra                     │
│  ssh/exceptions.py          Retry exception types                │
│  ssh/platform/              Linux/Windows platform detection     │
│  cloud/manager.py           CloudProvisionerImpl                 │
│  cloud/adapters.py          Azure/Hetzner/UpCloud adapter factory│
│  cloud/providers/           Provider SDK adapters                │
│  cloud/ssh_keys.py          SSH key load/generate                │
│  cloud/cloud_config.py      CloudConfig for cloud-init           │
│  cli/                       Per-command modules (6)              │
│  notifier/webhook.py        Webhook event handler                │
│                  (depends on: domain, application)               │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│                     COMPOSITION ROOT (di.py)                     │
│  make_daemon()      Async factory: Orchestrator with all deps    │
│  make_cli_deps()    Sync factory: CLIDeps for CLI/AiiDA          │
│  make_aiida()       Stub (NotImplementedError)                   │
│                  (depends on: everything — wires the graph)      │
└──────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  ENTRY POINTS & LEGACY WRAPPERS                                  │
│  client.py           Public API — Yascheduler facade             │
│  aiida_plugin.py     AiiDA scheduler integration                 │
│  config/             INI config tree (attrs)                     │
│  daemon_systemd.py   Systemd entry point                         │
│  daemon_sysv.py      SysV entry point                            │
└──────────────────────────────────────────────────────────────────┘
```

### Adapters layer facade

`yascheduler/infra/__init__.py` is the sole public surface for cross-layer
consumers. Application code and the composition root import gateway,
cloud provisioner, persistence UoW, and webhook handler **only** through
this facade — never through submodule paths. Subpackage `__init__.py`
files (`ssh/`, `cloud/`, `persistence/`, `notifier/`) mirror this rule at
the sub layer.

---

## 2. Component Reference

| Component            | Responsibility                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------- |
| `domain/`            | Entities, value objects, ports, services, exceptions, events                                            |
| `infra/persistence/` | PostgreSQL repositories, UoW, SQL loader, schema applier                                                |
| `infra/ssh/`         | `SSHMachineGateway` + platform adapters                                                                 |
| `infra/cloud/`       | `CloudProvisionerImpl` + provider SDK adapters                                                          |
| `infra/cli/`         | 6 per-command modules                                                                                   |
| `infra/notifier/`    | Webhook event handler                                                                                   |
| `application/`       | Use cases, `Orchestrator`, `AbstractUnitOfWork`, `MessageBus`                                           |
| `di.py`              | Composition root: `make_daemon()`, `make_cli_deps()`                                                    |
| `client.py`          | Public Python API (`class Yascheduler`) — uses `make_cli_deps()` for submit, routes queries through UoW |
| `aiida_plugin.py`    | AiiDA scheduler plugin (uses `Yascheduler` client)                                                      |
| `config/`            | Config tree parsed from INI (uses attrs)                                                                |

### 2.1 Domain (`yascheduler/domain/`)

Frozen dataclasses for entities, `typing.Protocol` for ports, a `DomainError`
hierarchy, and domain events. Pure stdlib; no yascheduler imports.

- **`model.py`** — `Task`, `Node`, `ConnectedMachine`, `Engine`,
  `TaskContext`, `TaskStatus`, `MachineState`, `ProcessResult`. `Task`
  stores events in a `_events` tuple and exposes `record_event` /
  `pull_events`.
- **`ports.py`** — `TaskRepository`, `NodeRepository`, `MachineGateway`,
  `CloudProvisioner` (async). Pure-computation contracts such as
  `OccupancyConfig` and `TaskExecutionEngine` are sync.
- **`services.py`** — `match_task_to_node(task, engine, free_machines)`.
- **`events.py`** — `DomainEvent` base + `TaskCreated`, `TaskAllocated`,
  `TaskCompleted`, `TaskFailed`, `TaskAbandoned`. `Event` is the union
  alias.
- **`exceptions.py`** — `DomainError` with `ValidationError`,
  `TaskError`, `MachineBusyError`, `SchedulingError`,
  `MachineConnectionError` subtrees (see §3.2).

I/O ports declare `async def`. This does not couple the domain to
asyncio — ports only declare the contract; the domain never awaits.

### 2.2 Persistence Adapter (`yascheduler/infra/persistence/`)

- **`postgres.py`** — `PostgresTaskRepository`, `PostgresNodeRepository`
  implementing the domain ports via pg8000. Each method runs a
  `load_query(name)` SQL file in a `ThreadPoolExecutor` and maps rows to
  domain entities.
- **`postgres_uow.py`** — `PostgresUnitOfWork` implementing the UoW
  pattern. Owns one `pg8000.Connection` and one
  `ThreadPoolExecutor(max_workers=1)` per instance; commits/rolls back on
  exit; dispatches events pulled from saved aggregates via the injected
  `MessageBus` after `commit()`.
- **`postgres_schema.py`** — `apply_schema(config_db)` applies
  `schema.sql` in a `BEGIN/COMMIT` transaction (used by CLI `init` and
  test fixtures).
- **`sql_loader.py`** — `load_query(name)` with `@functools.cache`.
- **`sql/`** — one file per query: `task/*.sql`, `node/*.sql`,
  `schema.sql`.
- **`exceptions.py`** — `UnitOfWorkNotInitializedError`.

pg8000 is synchronous. `PostgresUnitOfWork` owns a
`ThreadPoolExecutor(max_workers=1)`; this serializes DB access within a
single UoW instance. Concurrent use cases each create their own UoW and
therefore their own executor. This is intentional and adequate for
current load.

### 2.3 Application (`yascheduler/application/`)

Use cases orchestrate domain objects and adapter ports through
dependency-injected parameters. Every use case is UoW-based.

- **`submit_task.py`** — validates engine and inputs, creates a `TO_DO`
  task via `uow.tasks.insert()`, records `TaskCreated`, commits.
- **`allocate_task.py`** — matches a `TO_DO` task to a free compatible
  machine via `gateway.list_free` + `match_task_to_node`, starts the
  task on the machine through the injected `start_task_on_machine`
  callback, starts occupancy check, records `TaskAllocated` (or
  `TaskFailed` on validation failure), falls back to
  `clouds.allocate_with_tracking` if no machine is free.
- **`consume_task.py`** — downloads outputs via
  `gateway.download_outputs`, applies `Task.complete()` / `Task.fail()`,
  records `TaskCompleted` / `TaskFailed`, notifies `CloudProvisionerImpl`.
- **`deallocate_nodes.py`** — disables idle cloud nodes exceeding
  tolerance, returns their IPs for VM deletion by the orchestrator.
- **`orchestrator.py`** — long-running daemon driving four
  producer-consumer loop pairs (connect-machines, allocate, consume,
  deallocate) over `UniqueQueue` with configurable concurrency. Holds
  SSH helpers (`_start_task_on_machine`) and records `TaskAbandoned` for
  lost nodes.
- **`uow.py`** — `AbstractUnitOfWork` Protocol.
- **`message_bus.py`** — `MessageBus` with type-keyed handler
  registry; `dispatch(events)` awaits async handlers and logs failures
  without skipping subsequent handlers.

`application/__init__.py` is the sole public surface: it re-exports
`AbstractUnitOfWork`, `Orchestrator`, `MessageBus`, and `submit_task`.

### 2.4 SSH Adapter (`yascheduler/infra/ssh/`)

`SSHMachineGateway` implements `MachineGateway` via asyncssh. Tracks
connected machines with their occupancy state, runs commands, uploads and
downloads files, installs engine dependencies, and runs background
occupancy checks. Platform detection delegated to `ssh/platform/`
adapters (Linux, Windows). `ssh/helpers.py` holds the SSH client factory,
connection options, and platform detection glue; `ssh/exceptions.py`
re-exports retry exception tuples.

### 2.5 Cloud Adapter (`yascheduler/infra/cloud/`)

`CloudProvisionerImpl` implements `CloudProvisioner`. Provider SDK
integration lives in `cloud/providers/` (Azure, Hetzner, UpCloud);
`cloud/adapters.py` registers provider factories and resolves them by
config prefix. `cloud/ssh_keys.py` loads or generates SSH keys;
`cloud/cloud_config.py` renders cloud-init configuration.

### 2.6 CLI Adapter (`yascheduler/infra/cli/`)

Six per-command modules, each parsing argparse, calling use cases via DI,
and formatting output: `submit.py`, `check_status.py`, `init.py`,
`show_nodes.py`, `manage_node.py`, `daemonize.py`. The package
`__init__.py` re-exports all six. There is no monolithic `commands.py`.

### 2.7 Notifier (`yascheduler/infra/notifier/`)

`webhook_handler(event, http)` is registered on the `MessageBus` for all
five event types. It maps events to `WebhookPayload`, posts to
`event.webhook_url` via the shared `aiohttp.ClientSession` with fibonacci
backoff (`@backoff.on_exception`) and a 10-concurrent semaphore.
Failures are logged and swallowed after backoff exhausts.

### 2.8 Composition Root (`yascheduler/di.py`)

- **`make_daemon(config, log=None, *, clouds=None)`** — creates
  `_setup_domain_events()` (MessageBus + aiohttp session + webhook
  handler registration), a `PostgresUnitOfWork` factory,
  `CloudProvisionerImpl`, and `SSHMachineGateway`; returns a wired
  `Orchestrator`. Accepts pre-built `clouds` for tests. Does not create
  a `DB` or run schema migration (operator runs `yainit` first).
- **`make_cli_deps(config)`** — returns a `CLIDeps` dataclass with
  `engines`, `uow_factory`, `remote_tasks_dir`, and a `submit()`
  method. No SSH/cloud/daemon dependencies.
- **`make_aiida(config)`** — stub, raises `NotImplementedError`.

### 2.9 Public API & Legacy Wrappers

- **`client.py`** — `class Yascheduler` facade.
  `queue_submit_task_async()` uses `make_cli_deps()` → `CLIDeps.submit()`
  (no daemon graph). Query methods (`queue_get_tasks*`,
  `queue_get_task*`) route through the `query_tasks` use case over a UoW
  (no `DB` construction); see `openspec/changes/client-query-uow/`.
- **`aiida_plugin.py`** — AiiDA plugin uses `Yascheduler` client
  directly.

### 2.10 Configuration (`yascheduler/config/`)

INI-parsed configuration tree built on `attrs`: `Config` (root),
`ConfigDb`, `ConfigLocal`, `ConfigRemote`, `ConfigCloud*` (Azure,
Hetzner, UpCloud), `Engine`, `EngineRepository`. Domain uses stdlib
dataclasses; config uses attrs (see §6, Planned).

---

## 3. Key Design Topics

### 3.1 Sync Domain / Async Adapters

- Domain methods are synchronous — compute, validate, return.
- All I/O ports (`TaskRepository`, `MachineGateway`, `CloudProvisioner`)
  declare `async def`. The domain never awaits; it only declares the
  contract.
- Use cases are `async def` — they await repository calls, pass results
  to sync domain services, and await persistence back.
- pg8000 is synchronous; runs in `ThreadPoolExecutor` inside the
  persistence adapter.

### 3.2 Exception Hierarchy

```txt
DomainError                              (domain/exceptions.py)
├── ValidationError
│   ├── UnsupportedEngineError
│   └── MissingInputFileError
├── TaskError
│   ├── TaskAlreadyAllocatedError
│   ├── TaskNotAllocatedError
│   ├── TaskNotTodoError
│   └── TaskNotRunningError
├── MachineBusyError
├── SchedulingError
│   ├── NoCompatibleNodeError
│   └── CloudCapacityExhaustedError
└── MachineConnectionError

UnitOfWorkNotInitializedError            (infra/persistence/exceptions.py)
```

`DomainError` subclasses carry domain context (task_id, engine name,
ip). Use cases catch `ValidationError` → mark task with error,
`SchedulingError` → retry later, infrastructure failures → log and
retry. A planned `ApplicationError` / `InfrastructureError` hierarchy
for adapter-layer errors is captured in §6.

### 3.3 Unit of Work

- Each use case call gets a fresh UoW via the injected factory.
- UoW manages the transaction: `commit()` on success, `rollback()` on
  exception.
- Repositories within one UoW share one connection and one transaction.
- Aggregates record events via `Task.record_event(...)`. On
  `uow.commit()`, the UoW pulls events via `pull_events()` and
  dispatches them through the `MessageBus` **after** the commit
  succeeds.

### 3.4 Domain Events

```txt
Task aggregate ──record_event──> _events tuple
                                        │
PostgresUnitOfWork.commit() ─pull_events─┘
                  │
                  ▼
           MessageBus.dispatch(events)
                  │
                  ▼ (per event type)
        webhook_handler (notifier adapter)
                  │
                  ▼
       HTTP POST (fibonacci backoff, 10-concurrent semaphore)
```

Events decouple side effects from use cases. The orchestrator and use
cases only record events; the message bus dispatches them to handlers
registered by the composition root. Adding a new side effect (metrics,
audit log) means registering a new handler — no use case changes.

### 3.5 SQL in Files

- One file per query, named `entity/operation.sql`.
- Lazy-loaded via `load_query(name)` → `@functools.cache` → plain string.
- Parameter placeholders use pg8000 `:param` style.
- Schema DDL lives in `sql/schema.sql`; applied by `apply_schema()`.
- `TaskRepository.save(task)` does a full-row `UPDATE` (all columns).

### 3.6 Import Rules

```txt
domain/       → may NOT import from yascheduler at all (stdlib only)
application/  → may import domain/ only (via facade)
infra/        → may import domain/, application/ (via facades)
di.py         → may import everything (top of dependency graph)
config/       → may import nothing from yascheduler
```

Subpackage `__init__.py` files are the sole public surface for their
sub tree. Cross-layer consumers import from facades, not from submodules.

Enforcement via tooling (e.g., `import-linter`) is out of scope for the
architecture description; add via a separate proposal if needed.

### 3.7 Public API Stability

- `class Yascheduler` in `client.py` remains the public Python facade.
  Method signatures are preserved.
- CLI commands (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`,
  `yainit`, `yascheduler`) preserve their user-facing behavior.
- INI config format (including `[engine.*]` sections and `%(key)s`
  interpolation) is preserved.
- DB schema (`schema.sql`) is preserved; schema changes require
  migrations (see §6).
- AiiDA plugin entry point is preserved.

### 3.8 `class Yascheduler` (Public API)

- `queue_submit_task_async()` → `make_cli_deps()` → `CLIDeps.submit()`
  → `submit_task` use case → UoW. Submitting a task does not
  instantiate the daemon graph.
- Query methods (`queue_get_tasks*`, `queue_get_task*`) route through
  the `query_tasks` use case over a UoW (no `DB` construction); see
  `openspec/changes/client-query-uow/`.

---

## 4. Project Structure

```txt
yascheduler/
├── domain/
│   ├── __init__.py            # facade: events, model, exceptions, ports
│   ├── model.py
│   ├── services.py
│   ├── ports.py
│   ├── events.py
│   └── exceptions.py
├── infra/
│   ├── __init__.py            # adapters layer facade
│   ├── persistence/
│   │   ├── __init__.py        # facade
│   │   ├── postgres.py
│   │   ├── postgres_uow.py
│   │   ├── postgres_schema.py
│   │   ├── sql_loader.py
│   │   ├── exceptions.py
│   │   └── sql/
│   │       ├── schema.sql
│   │       ├── task/*.sql
│   │       └── node/*.sql
│   ├── ssh/
│   │   ├── __init__.py        # facade
│   │   ├── gateway.py
│   │   ├── helpers.py
│   │   ├── exceptions.py
│   │   └── platform/
│   ├── cloud/
│   │   ├── __init__.py        # facade
│   │   ├── manager.py         # CloudProvisionerImpl
│   │   ├── adapters.py
│   │   ├── protocols.py
│   │   ├── providers/
│   │   ├── ssh_keys.py
│   │   ├── cloud_config.py
│   │   └── utils.py
│   ├── cli/
│   │   ├── __init__.py        # facade
│   │   ├── submit.py
│   │   ├── check_status.py
│   │   ├── init.py
│   │   ├── show_nodes.py
│   │   ├── manage_node.py
│   │   └── daemonize.py
│   └── notifier/
│       ├── __init__.py        # facade
│       └── webhook.py
├── application/
│   ├── __init__.py            # facade: AbstractUnitOfWork, Orchestrator,
│   │                          # MessageBus, submit_task
│   ├── submit_task.py
│   ├── allocate_task.py
│   ├── consume_task.py
│   ├── deallocate_nodes.py
│   ├── orchestrator.py
│   ├── uow.py
│   ├── message_bus.py
│   └── queue.py                # UniqueQueue (relocated from root)
├── shared/
│   └── async_utils.py          # to_sync, asleep_until (gained from time.py)
├── di.py                      # composition root
├── client.py                  # Yascheduler facade
├── aiida_plugin.py            # AiiDA plugin
├── config/                    # INI config (attrs)
├── daemon_systemd.py
└── daemon_sysv.py
```

---

## 5. Testing Strategy

### 5.1 Fake Adapters (unit tests)

For every port in `domain/ports.py`, an in-memory fake exists for unit
testing:

| Port               | Fake                                |
| ------------------ | ----------------------------------- |
| `TaskRepository`   | dict-backed fake                    |
| `NodeRepository`   | dict-backed fake                    |
| `MachineGateway`   | stubbed SSH, returns canned results |
| `CloudProvisioner` | stubbed cloud, returns canned IPs   |

Use cases are tested with fakes — no real DB, SSH, or cloud.

### 5.2 Integration Tests

| Layer              | Tool                            |
| ------------------ | ------------------------------- |
| Persistence        | `testcontainers[postgres]`      |
| Use case + real DB | testcontainers + fake SSH/cloud |
| SSH adapter        | Docker SSH server               |
| Cloud adapter      | staged (manual) or mock HTTP    |

### 5.3 End-to-End Tests

Full task lifecycle against real PostgreSQL and SSH containers via
testcontainers: TO_DO → RUNNING → DONE transitions, node deallocation,
webhook dispatch.

### 5.4 Smoke Tests (Public API)

Before and after any change, run smoke tests that cover:

- All CLI entry points (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`,
  `yainit`, `yascheduler`).
- `class Yascheduler` public methods (submit, get, list — sync and
  async).
- AiiDA plugin scheduler entry point.

Run with `uv run pytest -m unit|integration|e2e`.

---

## 6. Planned

Active OpenSpec change proposals live in `openspec/changes/`. Anything
not listed there is intentionally out of scope.

### 6.1 Schema migrations (`openspec/changes/schema-migrations/`)

Replace the ad-hoc `db.migrate()` (hardcoded `ALTER TABLE ADD COLUMN IF
NOT EXISTS`) with versioned SQL migrations:

- `infra/persistence/sql/migrations/` directory with
  `NNN_description.sql` files.
- `yascheduler_migrations` tracking table.
- Sequential, transactional application of unapplied migrations.
- `schema.sql` remains the ground truth for fresh installations.

Enables schema evolution without modifying application code.

### 6.2 `make_aiida()` implementation

`make_aiida()` in `di.py` currently raises `NotImplementedError`. The
AiiDA plugin still imports the `Yascheduler` client directly. Wiring the
plugin through DI is deferred until the plugin is ready for refactoring;
no active proposal.

### 6.3 `client.py` query methods via use cases

**Resolved** by `openspec/changes/remove-legacy-db/`: `yascheduler/db.py` and
its legacy models have been deleted; all test fixtures now use
`PostgresUnitOfWork` + repos + `domain.TaskStatus`.

### 6.5 Application-layer exception hierarchy

A planned `ApplicationError` / `InfrastructureError` hierarchy
(`PersistenceError`, `MachineCommunicationError`,
`CloudProvisioningError`) would give adapter-layer failures first-class
types distinct from string-based status codes. Not yet proposed; capture
in a change proposal before implementing.

---

## 7. Open Questions

| Topic                           | Status                                                                     |
| ------------------------------- | -------------------------------------------------------------------------- |
| AiiDA plugin evolution          | Keep importing `Yascheduler` facade until §6.3 lands                       |
| `db.py` retirement              | **Resolved** by `remove-legacy-db` — module deleted, tests migrated to UoW |
| Config attrs → dataclasses      | §6.2, open proposal                                                        |
| Schema versioning               | §6.1, open proposal                                                        |
| Application exception hierarchy | §6.5, no proposal yet                                                      |
