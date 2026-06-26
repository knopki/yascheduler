# ARCHITECTURE.md — yascheduler

> **Authoritative structure reference**: `docs/knowledge-graph.xml` is the
> canonical source for the module inventory, dependency edges, and data flows.
> This document provides the architectural rationale behind that graph. When
> the two diverge, the graph is correct; update this document afterwards.

---

## 1. Overview

yascheduler schedules scientific calculation jobs on SSH machines and
cloud-created nodes. It ships a daemon, six CLI tools, a Python client, and an
AiiDA scheduler plugin.

The codebase follows a **hexagonal (ports-and-adapters) architecture** with a
strict, import-linter-enforced layer order:

```txt
yascheduler.entrypoints   →  driving adapters + composition root (outermost)
yascheduler.infra         →  driven adapters: persistence, SSH, cloud, notifier
yascheduler.application   →  use cases, orchestrator, UoW boundary, message bus
yascheduler.domain        →  entities, ports, events, exceptions (stdlib only)
yascheduler.shared        →  typing shims consumed by ≥2 layers
```

The contract is declared in `[tool.importlinter]` (`pyproject.toml`) as the
"Clean architecture layers" contract and is enforced by `uv run lint-imports`.
`domain` imports nothing from `yascheduler`. `application` imports `domain`
only. `infra` imports `domain`/`application`. `entrypoints` (which contains the
composition root `di.py`) may import everything below.

A frozen-dataclass domain, async I/O ports, and a single composition root that
wires the graph per entry point are the load-bearing ideas of the design.

```txt
                    ┌─────────────────────────────────────────┐
   CLI / client ───▶│  entrypoints                            │
   AiiDA / daemon   │  client.py · cli/ · di.py · config*.py  │
                    └──────────────┬──────────────────────────┘
                                   │ wires
              ┌────────────────────┴────────────────────┐
              ▼                                          ▼
   ┌─────────────────────┐                  ┌───────────────────────┐
   │  application        │  async ports     │  infra (adapters)      │
   │  use cases · orch-  │◀─────uses────────│  pg8000 · asyncssh ·   │
   │  estrator · UoW ·   │                  │  cloud SDKs · webhook  │
   │  message bus        │                  └───────────────────────┘
   └──────────┬──────────┘
              ▼
   ┌─────────────────────┐
   │  domain (stdlib)    │
   │  Task · Node ·      │
   │  Engine · ports ·   │
   │  events · errors    │
   └─────────────────────┘
```

---

## 2. Component Reference

### 2.1 Domain (`yascheduler/domain/`)

Pure stdlib. Frozen dataclasses for entities, `typing.Protocol` for ports, a
`DomainError` hierarchy, and domain events.

- **`model.py`** — `Task`, `Node`, `ConnectedMachine`, `TaskContext`,
  `TaskStatus` (`IntEnum`: `TO_DO=0`, `RUNNING=1`, `DONE=2`), `MachineState`,
  `ProcessResult`. `Task` stores events in a private `_events` tuple and
  exposes immutable lifecycle transitions (`allocate_to`, `mark_running`,
  `complete`, `fail`, `reject`, `with_context`, `with_event`, `record_event`,
  `pull_events`), each returning a new frozen instance.
- **`engine.py`** — `Engine` value object with `validate_inputs()`, the frozen
  `EngineRepository` collection, and `Deploy` strategies
  (`LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`).
- **`ports.py`** — async ports `TaskRepository`, `NodeRepository`,
  `MachineGateway`, `CloudProvisioner`, plus the structural `CloudConfig`
  Protocol that cloud DTOs satisfy.
- **`settings.py`** — `LocalSettings` (daemon paths, webhook, concurrency
  limits) and `RemoteDefaults` (SSH paths, username, jump host), frozen
  dataclasses with validation in `__post_init__`.
- **`services.py`** — `match_task_to_node(task, engine, free_machines)`.
- **`events.py`** — `DomainEvent` base + `TaskCreated`, `TaskAllocated`,
  `TaskCompleted`, `TaskFailed`, `TaskAbandoned`; `Event` is the union alias.
- **`exceptions.py`** — `DomainError` hierarchy (see §4.2).

I/O ports declare `async def`. This does not couple the domain to asyncio —
the domain only declares the contract and never awaits.

### 2.2 Application (`yascheduler/application/`)

Use cases orchestrate domain objects and adapter ports through
dependency-injected parameters. Every use case is UoW-based.

- **`submit_task.py`** — validates engine/inputs, creates a `TO_DO` task via
  `uow.tasks.insert()`, records `TaskCreated`, commits.
- **`query_tasks.py`** — read-only query by statuses XOR job IDs within a
  single UoW; no commit. Backs the client and `yastatus`/`yanodes`.
- **`allocate_task.py`** — matches a `TO_DO` task to a free compatible machine
  (or owns the cloud-fallback flow) and starts it. Records `TaskAllocated`
  (or `TaskFailed` on unsupported engine).
- **`consume_task.py`** — downloads outputs, finalizes the task
  (`complete`/`fail`), records `TaskCompleted`/`TaskFailed`, discards the
  allocation-tracker slot.
- **`deallocate_nodes.py`** — disables idle cloud nodes past `idle_tolerance`
  (`deallocate_nodes`) and deletes them (`deallocate_node`: gateway disconnect
  → UoW disable → `clouds.deallocate` → UoW remove).
- **`orchestrator.py`** — long-running daemon driving four producer-consumer
  loop pairs over de-duplicating queues (see §3).
- **`uow.py`** — `AbstractUnitOfWork` Protocol (`tasks`, `nodes`, `commit`,
  `rollback`).
- **`message_bus.py`** — type-keyed handler registry; `dispatch(events)`
  awaits async handlers and logs failures without skipping later handlers.
- **`allocation_tracker.py`** — in-memory set of `task_id`s with in-flight
  cloud allocations, owned by the orchestrator and injected into the
  allocate/consume use cases for dedup.
- **`queue.py`** — `UniqueQueue`/`UMessage`: async queue that skips duplicate
  messages by ID, used by every orchestrator loop.

`application/__init__.py` is the sole public surface, re-exporting
`AbstractUnitOfWork`, `Orchestrator`, `MessageBus`, `submit_task`,
`query_tasks`, `AllocationTracker`.

### 2.3 Persistence Adapter (`yascheduler/infra/persistence/`)

- **`postgres.py`** — `PostgresTaskRepository`, `PostgresNodeRepository`
  implementing the domain ports via pg8000. Each method runs a
  `load_query(name)` SQL file in a `ThreadPoolExecutor` and maps rows to
  domain entities.
- **`postgres_uow.py`** — `PostgresUnitOfWork`: one `pg8000.Connection` and
  one `ThreadPoolExecutor(max_workers=1)` per instance; runs `BEGIN` on enter,
  `COMMIT`/`ROLLBACK` on exit; dispatches events pulled from saved aggregates
  via the `MessageBus` **after** a successful commit.
- **`postgres_schema.py`** — `apply_schema(config_db)` applies `schema.sql`
  in a `BEGIN/COMMIT` transaction (used by `yainit` and test fixtures).
- **`db_config.py`** — `PostgresDbConfig` frozen dataclass.
- **`sql_loader.py`** — `load_query(name)` with `@functools.cache`.
- **`sql/`** — one file per query (`task/*.sql`, `node/*.sql`, `schema.sql`).
- **`exceptions.py`** — `UnitOfWorkNotInitializedError`.

pg8000 is synchronous. The single-worker executor serializes DB access within
one UoW; concurrent use cases each create their own UoW and executor. This is
intentional and adequate for current load.

### 2.4 SSH Adapter (`yascheduler/infra/ssh/`)

`SSHMachineGateway` implements `MachineGateway` via asyncssh: connects and
registers machines with occupancy state, runs commands, uploads/downloads
files, installs engine dependencies, and runs background occupancy checks.

Platform detection is delegated to `infra/ssh/platform/` (Linux and Windows
adapters behind a `RemoteMachineAdapter` registry, with `checks.py` for OS
detection and `common.py`/`linux.py`/`windows.py` for OS-specific commands).
`helpers.py` holds the SSH client factory, connection options, and platform
detection glue; `exceptions.py` re-exports the retry-exception tuples;
`keys.py` exposes the pure `list_private_keys(keys_dir)` discovery function
that the orchestrator consumes via injection.

### 2.5 Cloud Adapter (`yascheduler/infra/cloud/`)

`CloudProvisionerImpl` (`manager.py`) implements `CloudProvisioner` — pure
cloud-API adapter (create/delete VM, setup, SSH keys), no DB access.
`provider_selection.py` picks the best provider by priority, capacity, and
platform support.

Provider SDK integration lives in `providers/` (**Azure, Hetzner, UpCloud,
VastAI**); `adapters.py` registers provider factories and resolves them by
config prefix. `cloud_configs.py` holds the frozen cloud-config DTOs (one per
provider) that satisfy the domain `CloudConfig` Protocol; `cloud_init.py`
renders cloud-init user-data; `ssh_keys.py` loads or generates SSH keys.
Azure/Hetzner/UpCloud SDKs are optional extras; VastAI uses a REST API with no
extra dependency.

### 2.6 Notifier (`yascheduler/infra/notifier/`)

`webhook_handler(event, http)` is registered on the `MessageBus` for all five
event types. It maps each event to a `WebhookPayload`, POSTs to
`event.webhook_url` over a shared `aiohttp.ClientSession` with fibonacci
backoff (`max_time=60`) and a 10-concurrent `Semaphore`. Failures are logged
and swallowed after backoff exhausts.

### 2.7 CLI & Daemon (`yascheduler/entrypoints/cli/`)

Six per-command modules, each parsing argparse, calling use cases via DI, and
formatting output:

| Script        | Module            | Purpose                                  |
| ------------- | ----------------- | ---------------------------------------- |
| `yasubmit`    | `submit.py`       | Parse AiiDA script, submit a task        |
| `yastatus`    | `check_status.py` | Query tasks; verbose mode tails OUTPUT   |
| `yanodes`     | `show_nodes.py`   | List nodes and running tasks             |
| `yasetnode`   | `manage_node.py`  | Add / soft-remove / hard-remove a node   |
| `yainit`      | `init.py`         | Install service unit files and/or schema |
| `yascheduler` | `daemonize.py`    | Start the daemon in the foreground       |

Three daemon launchers (`daemonize.py`, `daemon_systemd.py`, `daemon_sysv.py`)
share the daemon core in `daemon_common.py` (`configure_logger` + `run_daemon`)
and the argparse helpers in `args.py` (`existing_path`, `add_config_arg`,
`add_log_level_arg`, `add_log_file_arg`). All commands accept `--config` and
`--log-level`. `daemon_systemd` runs in the foreground (stderr → journald);
`daemon_sysv` opens a `DaemonContext` (double-fork, pidfile); `daemonize`
runs in the foreground for debug/container use. Each launcher registers
SIGTERM/SIGINT handlers that call `orch.stop()`.

### 2.8 Composition Root (`yascheduler/entrypoints/di.py`)

- **`make_daemon(config, log, *, clouds=None)`** — builds the `MessageBus`
  (registers `webhook_handler` for all event types), an aiohttp session, a
  `PostgresUnitOfWork` factory, `CloudProvisionerImpl`, `SSHMachineGateway`,
  the `AllocationTracker`, the `allocation_lock`, and injects
  `list_private_keys` as `list_private_keys_fn`. Returns a wired
  `Orchestrator`. Does not create a DB or run schema migration (the operator
  runs `yainit` first). Accepts pre-built `clouds` for tests.
- **`make_cli_deps(config)`** — returns a lightweight `CLIDeps` container
  (`engines`, `uow_factory`, `remote_tasks_dir`, `submit()`). No
  SSH/cloud/daemon dependencies.

### 2.9 Public API & AiiDA Plugin

- **`entrypoints/client.py`** — the real public API. `class Yascheduler` lives
  here. `queue_submit_task_async()` → `make_cli_deps()` → `CLIDeps.submit()`
  → `submit_task` use case over a UoW (no daemon graph). Query methods route
  through the `query_tasks` use case over a UoW. Sync wrappers use a private
  `to_sync` helper.
- **`client.py`** (package root) — compat shim re-exporting `Yascheduler`
  from `entrypoints.client`, preserving `from yascheduler.client import
Yascheduler`.
- **`entrypoints/paths.py`** — `CONFIG_FILE`/`LOG_FILE`/`PID_FILE`.
- **`entrypoints/aiida_plugin.py`** — AiiDA scheduler plugin (`YaScheduler`).
  Talks to yascheduler over SSH transport (runs `yasubmit`/`yastatus`
  remotely); it does **not** use the `Yascheduler` client. Discovered by AiiDA
  via `[project.entry-points."aiida.schedulers"]` under the name
  `yascheduler` → `yascheduler.entrypoints.aiida_plugin:YaScheduler`.

### 2.10 Configuration

INI-parsed configuration assembled entirely as **frozen stdlib dataclasses**
(no attrs). `entrypoints/config_parser.py` (`parse_config`) reads the INI and
builds:

- `domain/settings.py` — `LocalSettings`, `RemoteDefaults`
- `infra/persistence/db_config.py` — `PostgresDbConfig`
- `infra/cloud/cloud_configs.py` — `ConfigCloudAzure`, `ConfigCloudHetzner`,
  `ConfigCloudUpcloud`, `ConfigCloudVastAI` (union `ConfigCloud`)
- `domain/engine.py` — `Engine` per `[engine.*]` section, gathered into an
  `EngineRepository`

These are bundled by `entrypoints/config.py` into the `Config` aggregate
(`db`, `local`, `remote`, `clouds`, `engines`), consumed only by the
composition root. The INI format (including `[engine.*]` sections and
`%(key)s` interpolation) is a stable public interface.

---

## 3. Daemon & Task Lifecycle

The daemon's runtime work is the `Orchestrator`. `start()` launches four
**producer-consumer loop pairs**, each wired through a de-duplicating
`UniqueQueue` (keyed so the same task/node is not processed twice):

| Loop           | Producer scans                        | Consumer does                                     | Limit knob     |
| -------------- | ------------------------------------- | ------------------------------------------------- | -------------- |
| **Connect**    | `uow.nodes.list_enabled()`            | `gateway.connect()` newly enabled nodes           | `conn_machine` |
| **Allocate**   | `uow.tasks.list_by_status({TO_DO})`   | `allocate_task()` (engine → free machine → cloud) | `allocate`     |
| **Consume**    | `uow.tasks.list_by_status({RUNNING})` | completion check; if done → `consume_task()`      | `consume`      |
| **Deallocate** | idle free machines                    | `deallocate_node()` sweep                         | `deallocate`   |

Per-loop concurrency limits and queue sizes come from `LocalSettings`; the
sleep interval is `min(engine.sleep_interval)` across engines. Shutdown is
cooperative: SIGTERM/SIGINT → `orch.stop()` sets a cancellation event, drains
the queues, cancels workers, then `clouds.stop()` and
`gateway.disconnect_all()`.

**Cloud fallback** (`allocate_task`): if no free compatible machine exists,
`tracker.add(task_id)` dedups; under the shared `allocation_lock` it runs a
capacity check, inserts a temporary node, and commits; the cloud VM is then
provisioned and the temp node replaced with the real one. On any
post-allocate failure the VM is best-effort deallocated and the temp node
cleaned up.

**Lost-node detection**: after 20 consecutive consume passes where a task's
machine is gone, the consumer records `TaskAbandoned`, fails the task, and
discards the tracker slot.

```txt
submit_task ──▶ TO_DO ──allocate_task──▶ RUNNING ──consume_task──▶ DONE
                  │                          │
                  │              cloud fallback (tracker + allocation_lock)
                  │                          │
                  └──────── TaskAbandoned (20 lost-node passes) ───────────▶ DONE
```

---

## 4. Key Design Topics

### 4.1 Sync Domain / Async Adapters

- Domain methods are synchronous — compute, validate, return.
- I/O ports declare `async def`; the domain never awaits, it only declares the
  contract.
- Use cases are `async def` — they await repository calls, pass results to
  sync domain services, await persistence back.
- pg8000 is synchronous; runs in a `ThreadPoolExecutor` inside the
  persistence adapter.

### 4.2 Exception Hierarchy

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
├── MachineConnectionError
└── CloudError
    ├── CloudAllocateError
    └── CloudSetupError

UnitOfWorkNotInitializedError            (infra/persistence/exceptions.py)
```

`DomainError` subclasses carry domain context (task_id, engine name, ip). Use
cases catch `ValidationError` → mark the task with an error, `SchedulingError`
→ retry later, infrastructure failures → log and retry.

### 4.3 Unit of Work

- Each use case call gets a fresh UoW via the injected factory.
- The UoW manages the transaction: `commit()` on success, `rollback()` on
  exception. Repositories within one UoW share one connection and one
  transaction.
- Aggregates record events via `Task.record_event(...)`. On `uow.commit()`,
  the UoW pulls events via `pull_events()` and dispatches them through the
  `MessageBus` **after** the commit succeeds — so notifications never fire for
  rolled-back work.

### 4.4 Domain Events

```txt
Task aggregate ──record_event──> _events tuple
                                         │
PostgresUnitOfWork.commit() ─pull_events─┘
                  │
                  ▼
           MessageBus.dispatch(events)
                  │
                  ▼  (per event type)
        webhook_handler (notifier adapter)
                  │
                  ▼
     HTTP POST (fibonacci backoff, 10-concurrent semaphore)
```

Events decouple side effects from use cases. The orchestrator and use cases
only record events; the message bus dispatches them to handlers registered by
the composition root. Adding a side effect (metrics, audit log) means
registering a new handler — no use case changes.

### 4.5 SQL in Files

- One file per query, named `entity/operation.sql`.
- Lazy-loaded via `load_query(name)` → `@functools.cache` → plain string.
- Parameter placeholders use pg8000 `:param` style.
- Schema DDL lives in `sql/schema.sql`; applied by `apply_schema()`.
- `TaskRepository.save(task)` does a full-row `UPDATE`.

### 4.6 Public API Stability

- The facade `class Yascheduler` lives in `entrypoints/client.py`; `client.py`
  at the package root is a compat shim re-exporting it.
- CLI commands (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`, `yainit`,
  `yascheduler`) preserve their user-facing behavior.
- INI config format (including `[engine.*]` sections and `%(key)s`
  interpolation) is preserved.
- DB schema (`schema.sql`) is preserved; schema changes require migrations.
- The AiiDA plugin entry point is preserved under the name `yascheduler`.

---

## 5. Project Structure

```txt
yascheduler/
├── entrypoints/                 # driving adapters + composition root (outermost layer)
│   ├── client.py                #   Yascheduler facade (real public API)
│   ├── paths.py                 #   CONFIG_FILE / LOG_FILE / PID_FILE
│   ├── aiida_plugin.py          #   AiiDA scheduler plugin (SSH transport)
│   ├── di.py                    #   composition root: make_daemon / make_cli_deps
│   ├── config.py                #   Config aggregate (frozen dataclass)
│   ├── config_parser.py         #   parse_config (INI → frozen dataclasses)
│   ├── _config_utils.py         #   ConfigWarning / unknown-key warnings
│   └── cli/                     #   six CLI commands + three daemon launchers
│       ├── daemon_common.py     #     shared daemon core (configure_logger, run_daemon)
│       └── args.py              #     shared argparse helpers
├── infra/                       # driven adapters
│   ├── persistence/             #   pg8000: repos, UoW, schema, SQL files
│   ├── ssh/                     #   asyncssh gateway + platform/ (Linux, Windows)
│   ├── cloud/                   #   CloudProvisionerImpl + providers/ (4 providers)
│   └── notifier/                #   webhook handler
├── application/                 # use cases, orchestrator, UoW, message bus
├── domain/                      # entities, ports, events, exceptions (stdlib only)
└── shared/                      # typing shims (Self, Unpack)
```

---

## 6. Testing Strategy

Tests are split into three pytest markers (`unit`, `integration`, `e2e`):

- **Unit** (`tests/unit`) — use cases driven by in-memory fakes for every port
  (`TaskRepository`, `NodeRepository`, `MachineGateway`, `CloudProvisioner`).
  No real DB, SSH, or cloud.
- **Integration** (`tests/integration`) — persistence and use cases against
  real PostgreSQL and Docker SSH servers via `testcontainers[postgres]`.
- **End-to-end** (`tests/e2e`) — full task lifecycle
  (`TO_DO → RUNNING → DONE`), node deallocation, and webhook dispatch against
  real PostgreSQL and SSH containers.

Run with `uv run pytest -m unit|integration|e2e`. Static checks:
`uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`,
`uv run lint-imports`.
