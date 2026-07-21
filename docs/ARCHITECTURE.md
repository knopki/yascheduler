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

- **`model.py`** — `Task`, `NewTask`, `Node`, `ConnectedMachine`, `TaskStatus`
  (`IntEnum`: `TO_DO=0`, `RUNNING=1`, `DONE=2`), `MachineState`,
  `ProcessResult`. `Task` stores events in a private `_events` tuple and exposes
  immutable lifecycle transitions (`allocate_to`, `mark_running`, `complete`,
  `fail`, `reject`, `with_remote_folder`, `with_download_results`, `with_event`,
  `record_event`, `pull_events`), each returning a new frozen instance.
- **`engine.py`** — `Engine` value object with `validate_inputs(extra)` (reads
  input-file payloads from the task's `extra: Mapping[str, object]`), the frozen
  `EngineRepository` collection, and `Deploy` strategies
  (`LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`).
- **`ports.py`** — async ports `TaskRepository`, `NodeRepository`,
  `MachineRepository`, `MachineSession`, `MachineOperations`,
  `CloudProvisioner`, plus the structural `CloudConfig` Protocol (7-field
  surface: `prefix`, `max_nodes`, `idle_tolerance`, `connect_grace`,
  `username`, `jump_username`, `jump_host`) that cloud DTOs satisfy.
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
  allocation-tracker slot. Returns `bool`: `True` when finalised (DONE
  applied, remote dir cleaned, tracker slot discarded) or the task row no
  longer exists (tracker slot discarded); `False` when deferred —
  transient-only SFTP failures leave the task `RUNNING`, preserve the
  remote dir, and retain the tracker slot so the orchestrator re-consumes
  on the next tick.
- **`abandon_node.py`** —
  `abandon_node(node, repository, clouds, uow_factory, tracker)`
  cleans up a never-connected cloud node: best-effort
  `clouds.deallocate`, `uow.nodes.remove + commit`, then locates the
  originating `TO_DO` task by `allocated_ip == ip` (via
  `uow.tasks.list_by_status({TO_DO})` + in-memory filter) and calls
  `tracker.discard(task_id)` so the task re-enters allocation on the next
  cycle.
- **`deallocate_nodes.py`** — disables idle cloud nodes past `idle_tolerance`
  (`deallocate_nodes`) and deletes them (`deallocate_node`: session
  disconnect → UoW disable → `clouds.deallocate` → UoW remove).
- **`orchestrator.py`** — long-running daemon driving four producer-consumer
  loop pairs over de-duplicating queues (see §3), plus a per-IP
  never-connected-node failure timer (`connect_grace`) that dispatches to
  `abandon_node`, an in-flight consume guard (`self._consuming: set[int]`)
  preventing two workers from concurrently consuming the same `RUNNING`
  task, and producer/consumer error resilience (see §4.7).
- **`uow.py`** — `AbstractUnitOfWork` Protocol (`tasks`, `nodes`, `commit`,
  `rollback`).
- **`message_bus.py`** — type-keyed handler registry; `dispatch(events)`
  awaits async handlers and logs failures without skipping later handlers.
- **`allocation_tracker.py`** — in-memory set of `task_id`s with in-flight
  cloud allocations, owned by the orchestrator and injected into the
  allocate/consume use cases for dedup.
- **`queue.py`** — `UniqueQueue`/`UMessage`: async queue that skips duplicate
  messages by ID, used by every orchestrator loop. `put()` is serialised
  by an `asyncio.Lock` so the check-then-act dedup window cannot admit a
  duplicate under concurrent `put()` on a full queue.

`application/__init__.py` is the sole public surface, re-exporting
`AbstractUnitOfWork`, `Orchestrator`, `MessageBus`, `submit_task`,
`query_tasks`, `abandon_node`, `AllocationTracker`.

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
  `schema.sql` is the **full latest snapshot**: every `CREATE TABLE` carries
  all current columns, no inline `ALTER`s, and it begins with a PL/pgSQL DO
  block that bootstraps the `yascheduler_migrations` tracker with three-case
  logic (seed to latest on a fresh DB; create empty on a legacy DB that
  already has `yascheduler_nodes`; no-op on a modern DB that already has the
  tracker).
- **`postgres_migrations.py`** — `apply_migrations(config_db)` is the
  forward-only migration runner. It scans `sql/migrations/` for `*.sql` and
  `*.py` files named `{prefix_id}_{rest}.{sql,py}`, reads
  `SELECT MAX(migration_id) FROM yascheduler_migrations`, and applies pending
  migrations in string-sorted `prefix_id` order, each in its own transaction,
  recording each in the tracker after success. `.sql` migrations run as a
  multi-statement string (pg8000 Simple Query); `.py` migrations define
  exactly one `Migration` subclass (discovered via `inspect`) instantiated
  with `(config, conn, log)`. `yainit` calls `apply_migrations` immediately
  after `apply_schema`. There is no "down"/rollback path and no generation
  tool. `prefix_id` uniqueness is enforced by a unit test, not the runner.
- **`migration_base.py`** — `Migration` base class for `.py` migrations:
  injected `(config, conn, log)` with `begin()`/`commit()` helpers for
  non-transactional operations (`CREATE INDEX CONCURRENTLY`, `VACUUM`).
- **`db_config.py`** — `PostgresDbConfig` frozen dataclass.
- **`sql_loader.py`** — `load_query(name)` with `@functools.cache`.
- **`sql/`** — one file per query (`task/*.sql`, `node/*.sql`, `schema.sql`).
  `task/update_by_id.sql` and `task/update_status.sql` use
  `RETURNING task_id` so the repository can detect a 0-row outcome and
  raise `TaskRowNotFoundError`. `sql/migrations/` holds the migration files
  (`001_add_username_port.sql` is the first; the inline ALTERs that used to
  live in `schema.sql` were moved here).
- **`exceptions.py`** — `UnitOfWorkNotInitializedError`,
  `TaskRowNotFoundError`. The latter is raised by
  `PostgresTaskRepository.save`/`update_status` when an `UPDATE` targets a
  non-existent `task_id` (the SQL uses `RETURNING task_id` so a 0-row
  outcome is detectable). Programming-error / contract precondition
  violation, not a domain exception — callers SHALL NOT catch it.

When adding a migration, three edits are required (documented in the
`db-migrations` spec): create the file under `sql/migrations/`, update the
`last_migration` CONSTANT in the `schema.sql` DO block, and — if the
migration changes the schema — update the snapshot DDL in `schema.sql`. A
unit test asserts the CONSTANT matches the latest migration's `prefix_id`.

pg8000 is synchronous. The single-worker executor serializes DB access within
one UoW; concurrent use cases each create their own UoW and executor. This is
intentional and adequate for current load.

### 2.4 SSH Adapter (`yascheduler/infra/ssh/`)

The SSH adapter splits the connected-machine collection from operations on
a single machine. Three concrete modules (`repository.py`, `session.py`,
`operations/`) implement three domain ports (`MachineRepository`,
`MachineSession`, `MachineOperations`).

- **`repository.py`** — `SSHMachineRepository` implements `MachineRepository`.
  Owns the connected-machine collection
  (`_sessions: dict[str, MachineSession]`).
  Seven-method surface: `connect → MachineSession`,
  `disconnect(ip)`, `disconnect_all()`,
  `list_free(platforms) → list[MachineSession]`,
  `list_connected() → list[MachineSession]`,
  `get_session(ip) → MachineSession \| None`,
  plus `**contains**`/`**len**`.
  State transitions (`occupy`/`release`/`update`), accessor getters
  (`path`/`quote`/`hostname`), and the monitor mechanism live on the
  session — the repository only hands sessions out and tracks them by IP.
  `disconnect(ip)` pops `_sessions[ip]` and delegates teardown to
  `session._close()`; it SHALL NOT touch any other session's monitor.
  Connection-building bits (`MySSHClient`, `DEFAULT_CONN_OPTS`,
  `_build_tunnel_options`) live here.
- **`session.py`** — `SSHMachineSession` implements `MachineSession`, the
  connected-machine entity handle. Carries domain identity (`ip`, mutable
  `machine` snapshot, `occupy`/`release`/`update` transitions), read-only
  connect-time config (`adapter`, `platforms`, `data_dir`, `engines_dir`,
  `tasks_dir`), adapter-derived accessors (`path`, `quote`, `hostname`),
  base SSH primitives (`run`, `run_full`, `run_bg`, `upload`, `open_sftp`,
  `get_cpu_cores`, `setup_node`, `pgrep`, `list_processes`), and the
  per-session monitor mechanism (`install_monitor`/`cancel_monitor`). The
  session owns its own monitor task — the repository holds no `_monitors`
  dict. `_close()` is private, called only by
  `SSHMachineRepository.disconnect`.
- **`operations/`** — `SSHMachineOperations` (the `MachineOperations`
  facade) composes three stateless sibling collaborators:
  `TaskDeployer` (`start_task_on_machine` + upload + spawn + rollback,
  `_write_remote_file`, `_safe_b64decode`),
  `OutputDownloader` (`download_outputs` + error classification, with
  per-file SFTP isolation and a single post-loop `rmtree` gate on
  `not transient_errors AND not permanent_errors`),
  `OccupancyChecker` (`occupancy_check`, `_by_pgrep`, `_by_cmd`,
  `start_occupancy_check` — calls `session.occupy()` +
  `session.install_monitor(...)`). The facade also exposes pass-throughs
  (`run`/`run_full`/`run_bg`/`get_cpu_cores`/`setup_node`) that delegate
  to the `session`. All machine-reference parameters are typed
  `session: MachineSession`; the orchestrator resolves a session per
  tick via `repository.get_session(ip)` before calling an operations
  method. `run_bg`, `upload`, and `download` are single-attempt (spawn,
  `sftp.put`, and `sftp.get` are non-idempotent); `get_cpu_cores` keeps its
  backoff (idempotent read).
- **`platform/`** — platform detection (Linux and Windows adapters behind a
  `RemoteMachineAdapter` registry) and `checks.py` (OS detection),
  `common.py`/`linux.py`/`windows.py` (OS-specific commands),
  `paths.py` (path normalization), `registry.py`/`detect.py`/`run_fn.py`
  (adapter registry, platform detection, run-fn closure).
- **`keys.py`** — the pure `list_private_keys(keys_dir)` discovery function
  the orchestrator consumes via injection.

### 2.5 Cloud Adapter (`yascheduler/infra/cloud/`)

`CloudProvisionerImpl` (`manager.py`) implements `CloudProvisioner` — pure
cloud-API adapter (create/delete VM, setup, SSH keys), no DB access.
`provider_selection.py` picks the best provider by priority, capacity, and
platform support.

Provider SDK integration lives in `providers/` (**Azure, Hetzner, UpCloud,
VastAI**); `adapters.py` registers provider factories and resolves them by
config prefix. `cloud_configs.py` holds the frozen cloud-config DTOs (one per
provider) that satisfy the domain `CloudConfig` Protocol (each declares a
per-provider `connect_grace` default: Hetzner/UpCloud = 60s, Azure/VastAI =
120s); `cloud_init.py` renders cloud-init user-data; `ssh_keys.py` loads or
generates SSH keys. `protocols.py` defines the node create/delete callables
and `provider_selection.py` picks the best provider by priority, capacity, and
platform support. Azure/Hetzner/UpCloud SDKs are optional extras; VastAI uses a
REST API with no extra dependency.

### 2.6 Notifier (`yascheduler/infra/notifier/`)

`webhook_handler(event, http)` is registered on the `MessageBus` for all five
event types. It maps each event to a `WebhookPayload`, POSTs to
`event.webhook_url` over a shared `aiohttp.ClientSession` with fibonacci
backoff (`max_time=60`) and a 10-concurrent `Semaphore`. Failures are logged
and swallowed after backoff exhausts.

### 2.7 CLI & Daemon (`yascheduler/entrypoints/cli/`)

Six per-command modules, each parsing argparse, calling use cases via DI, and
formatting output:

| Script | Module | Purpose |
| --- | --- | --- |
| `yasubmit` | `submit.py` | Parse AiiDA script, submit a task |
| `yastatus` | `check_status.py` | Query tasks; verbose mode tails OUTPUT |
| `yanodes` | `show_nodes.py` | List nodes and running tasks |
| `yasetnode` | `manage_node.py` | Add / soft-remove / hard-remove a node |
| `yainit` | `init.py` | Install service unit files and/or apply schema + migrations |
| `yascheduler` | `daemonize.py` | Start the daemon in the foreground |

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
  `PostgresUnitOfWork` factory, `CloudProvisionerImpl`, one
  `SSHMachineRepository` and one `SSHMachineOperations` (shared between
  `CloudProvisionerImpl.machine_repository`/`machine_operations` and the
  `Orchestrator.repository`/`operations` ports so `_setup_vm` connections
  are visible to the orchestrator), the `AllocationTracker`, the
  `allocation_lock`, and injects `list_private_keys` as
  `list_private_keys_fn`. Returns a wired `Orchestrator`. Does not create a
  DB or run schema migration (the operator runs `yainit` first). Accepts
  pre-built `clouds` for tests.
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
  from `entrypoints.client`, preserving `from yascheduler.client import Yascheduler`.
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

| Loop | Producer scans | Consumer does | Limit knob |
| --- | --- | --- | --- |
| **Connect** | `uow.nodes.list_enabled()` | `repository.connect()` newly enabled nodes | `conn_machine` |
| **Allocate** | `uow.tasks.list_by_status({TO_DO})` | `allocate_task()` (engine → free machine → cloud) | `allocate` |
| **Consume** | `uow.tasks.list_by_status({RUNNING})` | completion check; if done → `consume_task()` | `consume` |
| **Deallocate** | idle free machines | `deallocate_node()` sweep | `deallocate` |

Per-loop concurrency limits and queue sizes come from `LocalSettings`; the
sleep interval is `min(engine.sleep_interval)` across engines. Shutdown is
cooperative: SIGTERM/SIGINT → `orch.stop()` (idempotent, exception-safe) sets
the `_stopped` guard, drains the queues, cancels workers (registered in
`self._bg_jobs` so the cancel cascade reaches them even if a parent coroutine
died), then `clouds.stop()` and `repository.disconnect_all()`.
`run_daemon` wraps `await orch.start()` in `try/finally: await orch.stop()` so
cleanup runs on every exit path (normal `start()` return, `start()` exception,
signal-driven shutdown where the handler's `stop()` runs first and the
`finally`'s `stop()` is an idempotent no-op).

**Cloud fallback** (`allocate_task`): if no free compatible machine exists,
`tracker.add(task_id)` dedups; under the shared `allocation_lock` it runs a
capacity check, inserts a temporary node, and commits; the cloud VM is then
provisioned and the temp node replaced with the real one. On any
post-allocate failure the VM is best-effort deallocated and the temp node
cleaned up.

**Never-connected-node cleanup**: a cloud node that is provisioned and
persisted (`enabled=True`) but fails to establish its SSH connection is
bounded by `connect_grace`. The connect consumer tracks `first_seen`
(monotonic) per IP on `MachineConnectionError`; on each failure it compares
elapsed age against the node's cloud `connect_grace`; on success it pops the
entry. Once `connect_grace` is exhausted it dispatches to `abandon_node`
(best-effort VM delete + DB-row remove + tracker discard for the stuck
`TO_DO` task).

**Lost-node detection**: after 20 consecutive consume passes where a task's
machine is gone, the consumer records `TaskAbandoned`, fails the task, and
discards the tracker slot.

**Consume error handling**: `consume_task` returns `False` on transient-only
SFTP failures (task stays `RUNNING`, remote dir preserved, tracker slot
retained, re-consumed next tick) and `True` on finalisation (success or any
permanent error → `DONE` with `task.fail()`, `rmtree` runs). An in-flight
consume guard (`self._consuming: set[int]`) prevents two workers from
concurrently consuming the same `RUNNING` task across overlapping producer
cycles.

```txt
submit_task ──▶ TO_DO ──allocate_task──▶ RUNNING ──consume_task──▶ DONE
                  │                          │
                  │              cloud fallback (tracker + allocation_lock)
                  │                          │
                  ├──── never-connected cloud node (connect_grace) ──▶ abandon_node ──▶ TO_DO (re-allocate)
                  │
                  └──────── TaskAbandoned (20 lost-node passes) ─────────────────────▶ DONE
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
TaskRowNotFoundError                      (infra/persistence/exceptions.py,
                                           sibling of the above — programming-error,
                                           not a domain exception; raised by
                                           PostgresTaskRepository.save/update_status
                                           on a 0-row UPDATE)
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
  `schema.sql` is the **full latest snapshot** (all current columns in the
  `CREATE TABLE`s, no inline `ALTER`s) and begins with a DO block that
  bootstraps the `yascheduler_migrations` tracker.
- Schema **evolution** is expressed via migration files under
  `sql/migrations/` (`{prefix_id}_{rest}.sql` or `.py`), applied by
  `apply_migrations()`. `yainit` runs `apply_schema` then `apply_migrations`.
  See §2.3 for the migration model and edit procedure.
- `TaskRepository.save(task)` runs `task/update_by_id.sql` with
  `RETURNING task_id`; a 0-row outcome raises `TaskRowNotFoundError`
  (predecessor-violation, not a domain error). `update_status` uses
  `task/update_status.sql` with the same `RETURNING` guard.

### 4.6 Public API Stability

- The facade `class Yascheduler` lives in `entrypoints/client.py`; `client.py`
  at the package root is a compat shim re-exporting it.
- CLI commands (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`, `yainit`,
  `yascheduler`) preserve their user-facing behavior.
- INI config format (including `[engine.*]` sections and `%(key)s`
  interpolation) is preserved.
- DB schema (`schema.sql`) is preserved; schema changes require migrations.
- The AiiDA plugin entry point is preserved under the name `yascheduler`.

### 4.7 Orchestrator & Daemon Resilience

The daemon self-heals through transient failures and shuts down without
leaking resources.

- **Producer error resilience**: `_create_producer_consumers` wraps
  `async for msg in producer()` in `try/except Exception` — a producer
  failure (DB timeout, gateway error) is logged and the loop continues on
  the next `_sleep_interval` tick. `asyncio.CancelledError` is a
  `BaseException` (not `Exception`) since 3.8, so graceful shutdown still
  propagates to the existing `except CancelledError` drain path. `_print_stats`
  has the identical wrap. Worker tasks are registered in `self._bg_jobs` so
  `stop()`'s cancel cascade reaches them.
- **Consumer error resilience**: the inner `worker()` in
  `_create_producer_consumers` wraps `await consumer(msg)` in
  `try/except Exception` (log + continue next message), symmetric to the
  producer wrap; `finally: queue.item_done(msg)` is preserved so the item
  is still dequeued on raise. This also covers `TaskRowNotFoundError` from
  the orchestrator's task-abandon path (which races the row's lifetime).
- **Idempotent, exception-safe `stop()`**: a `_stopped` guard (set
  synchronously, no `await` between check and set) makes the cleanup body
  run exactly once across concurrent/interleaved/repeated callers. Each
  cleanup step (`clouds.stop()`, `repository.disconnect_all()`,
  `http_session.close()`) is isolated in its own `try/except Exception` so
  one failing step cannot skip the others. `await task` on cancelled
  background jobs tolerates a non-`CancelledError` exception via
  `except Exception`. `http_session` is nulled after close.
- **`run_daemon` cleanup guarantee**: `await orch.start()` is wrapped in
  `try/finally: await orch.stop()` so cleanup runs on every exit path
  (normal `start()` return, `start()` exception, signal-driven shutdown
  where the handler's `stop()` runs first and the `finally`'s `stop()` is
  an idempotent no-op).

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
│   ├── ssh/                     #   asyncssh
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
  (`TaskRepository`, `NodeRepository`, `MachineRepository`,
  `MachineSession`, `MachineOperations`, `CloudProvisioner`). No real DB,
  SSH, or cloud.
- **Integration** (`tests/integration`) — persistence and use cases against
  real PostgreSQL and Docker SSH servers via `testcontainers[postgres]`.
- **End-to-end** (`tests/e2e`) — full task lifecycle
  (`TO_DO → RUNNING → DONE`), node deallocation, and webhook dispatch against
  real PostgreSQL and SSH containers.

Run with `uv run pytest -m unit|integration|e2e`. Static checks:
`uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`,
`uv run lint-imports`.
