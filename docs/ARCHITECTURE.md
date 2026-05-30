# ARCHITECTURE.md — yascheduler

> **Authoritative structure reference**: `docs/knowledge-graph.xml` is the
> canonical source for module inventory, dependency edges, data flows, and
> cross-module relationships. This document provides architectural
> rationale, a migration roadmap, and design-decisions not captured in the
> graph. When the two diverge, the graph is correct; update this document
> afterwards.

---

## 1. Current Architecture

### 1.1 Overview

yascheduler is midway through a migration from a monolithic structure to a
hexagonal (ports-and-adapters) architecture. Two layers are already in place:
**domain** (entities, ports, exceptions, services) and **persistence adapter**
(PostgreSQL repositories, UoW, SQL loader). The remaining layers —
application (use cases, orchestrator, DI), SSH/cloud adapters, CLI, and
domain events — are still planned.

The daemon orchestrator (`scheduler.py`) remains the hub. `db.py` is now a
wrapper that delegates to `PostgresTaskRepository` / `PostgresNodeRepository`
internally while preserving its legacy public API.

```txt
┌─────────────────────────────────────────────────────────────────┐
│  DOMAIN (implemented)                                            │
│  model.py        Task, Node, ConnectedMachine, Engine,           │
│                  TaskContext, TaskStatus (frozen dataclasses)     │
│  services.py     match_task_to_node                              │
│  ports.py        TaskRepository, NodeRepository,                 │
│                  MachineGateway, CloudProvisioner (Protocols)     │
│  exceptions.py   DomainError hierarchy                           │
│                  (depends on: stdlib only)                        │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  ADAPTERS: PERSISTENCE (implemented)                             │
│  postgres.py       PostgresTaskRepository, PostgresNodeRepository│
│  postgres_uow.py   PostgresUnitOfWork                            │
│  sql_loader.py     load_query(name) → cached SQL strings         │
│  sql/              task/*.sql, node/*.sql, schema.sql             │
│                  (depends on: domain)                             │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  LEGACY (not yet migrated)                                       │
│                        scheduler.py                               │
│  (allocator, consumer, deallocator, webhooks, stats, …)          │
│  ───┬───────┬──────────┬───────────┬──────────┬────────────────── │
│     │       │          │           │          │                   │
│     ▼       ▼          ▼           ▼          ▼                   │
│  db.py   clouds/   remote_mach/  config/    queue                │
│ (wrapper) (az/hz/uc  (SSH/SFTP)  (INI/attrs) (UniqueQueue)       │
│           upcloud)                                                │
│  client.py → imports scheduler.py (full daemon graph)            │
│  utils.py → CLI commands (monolithic)                            │
│                  (depends on: domain, persistence, legacy peers)  │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Components

| Component               | Responsibility                                          |
| ----------------------- | ------------------------------------------------------- |
| `domain/`               | Entities, value objects, ports, services, exceptions    |
| `adapters/persistence/` | PostgreSQL repositories, UoW, SQL loader                |
| `scheduler.py`          | God object: all producer-consumer loops, task lifecycle |
| `db.py`                 | Wrapper delegating to PostgresTaskRepository / NodeRepo |
| `clouds/`               | Multi-cloud VM provisioning (Azure, Hetzner, UpCloud)   |
| `remote_machine/`       | SSH connection, platform detection, command execution   |
| `config/`               | Config tree parsed from INI (uses attrs)                |
| `utils.py`              | CLI entry points (6 commands), ~540 LOC                 |
| `client.py`             | Public Python API (`class Yascheduler`)                 |
| `aiida_plugin.py`       | AiiDA scheduler integration                             |

### 1.3 Pain Points (remaining)

- **`scheduler.py` is ~800 LOC** — still violates single responsibility; not
  yet thinned to use-case calls.
- **Unclear error handling** in legacy code — mix of `RuntimeError("string")`,
  `assert`, status-code strings in DB, and generic `except Exception: log`.
  Domain exceptions exist but are not yet used by the scheduler.
- **`pg8000` in `ThreadPoolExecutor(max_workers=1)`** — serializes all DB
  access (now inside the persistence adapter).
- **Webhook logic scattered across 5 call sites** with inconsistent ordering
  relative to `commit()`.
- **`client.py` imports `scheduler.py`** — submitting a task instantiates the
  entire daemon dependency graph just to insert a DB row.
- **`utils.py` CLI commands mix** argparse, DB, SSH, and cloud-init in one file.
- **`config/` uses attrs** — domain uses dataclasses; config still attrs
  (low priority, deferred to phase 5.6).
- **No DI, no use cases, no orchestrator** — the application layer is the
  next migration target.

---

## 2. Target Architecture

### 2.1 Hexagonal + DDD (remaining layers)

Domain and persistence are in place. The remaining work adds the application
layer, SSH/cloud adapters, CLI decoupling, and domain events.

```txt
┌─────────────────────────────────────────────────────────────────┐
│  DOMAIN ✅ (done)                                                │
│  — see §1.1 for current contents                                │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  ADAPTERS: PERSISTENCE ✅ (done)                                 │
│  — see §1.1 for current contents                                │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│                       APPLICATION (planned)                      │
│  *_task.py        SubmitTask, AllocateTask, ConsumeTask,         │
│                   DeallocateIdleNodes (use cases)                 │
│  uow.py           AbstractUnitOfWork (Protocol)                  │
│  events.py        TaskCreated, TaskAllocated, … (phase 3.5)      │
│  message_bus.py   Event dispatch after commit (phase 3.5)        │
│  orchestrator.py  Long-running daemon: poll loops + use cases    │
│                  (depends on: domain)                             │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  ADAPTERS: SSH, CLOUD, CLI (planned)                             │
│  ssh/gateway.py               SSHMachineGateway (phase 4)        │
│  cloud/                       Azure/Hetzner/UpCloud (phase 4)    │
│  cli/commands.py              Thin CLI wrappers (phase 5)        │
│  notifier/webhook.py          aiohttp webhook dispatcher         │
│                  (depends on: domain, application)                │
└──────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│                     COMPOSITION ROOT (planned)                   │
│  di.py             Factories: make_cli_deps(), make_daemon(),    │
│                    make_aiida()                                   │
│                  (depends on: everything — wires the graph)       │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 Design Decisions

| Decision                 | Choice                            | Rationale                                        |
| ------------------------ | --------------------------------- | ------------------------------------------------ |
| Domain model library     | stdlib `dataclasses`              | Zero dependencies in domain ✅                   |
| Port definitions         | `typing.Protocol`                 | Structural subtyping, no inheritance required ✅ |
| Domain layer concurrency | Synchronous                       | Simpler, testable, no I/O ✅                     |
| Application/adapters     | Async (`async def`)               | Matches existing asyncssh, aiohttp, asyncio      |
| Persistence              | pg8000, raw SQL in `.sql` files   | No ORM overhead, SQL tooling friendly ✅         |
| DI                       | Manual, no container              | Project size doesn't justify framework overhead  |
| Unit of Work             | Factory-injected into use case    | Transaction per use case, testable with fakes    |
| Domain Events            | Deferred to phase 3.5             | Requires stable UoW first                        |
| Bounded contexts         | Monolith with internal boundaries | Avoids cross-context boilerplate                 |
| Project structure        | Layered (domain/app/adapters)     | "Screaming architecture", clear import rules     |
| Config library           | attrs → dataclasses               | Deferred to phase 5.6 (no functional gain)       |

### 2.3 Import Rules

```txt
domain/       → may NOT import from yascheduler at all (stdlib only) ✅
application/  → may import domain/
adapters/     → may import domain/, application/
di.py         → may import everything (top of dependency graph)
config.py     → may import nothing from yascheduler
```

Enforcement via tooling (e.g., `import-linter` or `layer-lint`) is out of
scope for the architecture migration; add via a separate proposal.

---

## 3. Layer Details

### 3.1 Domain (`yascheduler/domain/`) — ✅ implemented

**`model.py`** — Entities and value objects as frozen dataclasses.

```python
import time
from dataclasses import dataclass, field, replace
from enum import Enum, IntEnum

class TaskStatus(IntEnum):
    TO_DO = 0
    RUNNING = 1
    DONE = 2

class MachineState(Enum):
    FREE = "free"
    BUSY = "busy"

@dataclass(frozen=True)
class Engine:
    name: str
    spawn: str
    input_files: tuple[str, ...]
    output_files: tuple[str, ...]
    platforms: tuple[str, ...]
    check_cmd: str | None = None
    check_pname: str | None = None

    def validate_inputs(self, context: TaskContext) -> None: ...

@dataclass(frozen=True)
class TaskContext:
    engine: str
    remote_folder: str | None = None
    local_folder: str | None = None
    webhook_url: str | None = None
    webhook_custom_params: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class Task:
    task_id: int
    label: str
    status: TaskStatus
    context: TaskContext
    allocated_ip: str | None = None
    def allocate_to(self, ip: str) -> "Task": ...
    def mark_running(self) -> "Task": ...
    def complete(self) -> "Task": ...
    def fail(self, reason: str) -> "Task": ...

@dataclass(frozen=True)
class Node:
    ip: str
    ncpus: int
    enabled: bool
    cloud: str | None = None
    username: str = "root"
    port: int = 22

@dataclass(frozen=True)
class ConnectedMachine:
    ip: str
    platform: str
    ncpus: int
    state: MachineState
    free_since: float | None = None
    def is_compatible(self, platforms: tuple[str, ...]) -> bool: ...
    def occupy(self) -> "ConnectedMachine": ...
    def release(self) -> "ConnectedMachine": ...

@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
```

**`ports.py`** — Abstract interfaces as Protocols.

```python
from typing import Protocol

class TaskRepository(Protocol):
    async def get(self, task_id: int) -> Task: ...
    async def save(self, task: Task) -> None: ...
    async def list_by_status(self, statuses: set[TaskStatus]) -> list[Task]: ...

class NodeRepository(Protocol):
    async def get(self, ip: str) -> Node: ...
    async def list_enabled(self) -> list[Node]: ...
    async def list_disabled(self) -> list[Node]: ...
    async def add(self, node: Node) -> None: ...
    async def add_tmp(self, ip: str, cloud: str) -> None: ...
    async def update(self, node: Node) -> None: ...
    async def enable(self, ip: str) -> None: ...
    async def disable(self, ip: str) -> None: ...
    async def remove(self, ip: str) -> None: ...

class MachineGateway(Protocol):
    async def list_free(self, platforms: list[str] | None = None) -> list[ConnectedMachine]: ...
    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult: ...
    async def upload(self, machine: ConnectedMachine, local: Path, remote: str) -> None: ...
    async def download(self, machine: ConnectedMachine, remote: str, local: Path) -> None: ...

class CloudProvisioner(Protocol):
    async def allocate(self, platforms: list[str]) -> Node: ...
    async def deallocate(self, ip: str) -> None: ...
    async def capacity(self) -> dict[str, int]: ...
```

I/O ports use `async def`. This does **not** couple the domain to asyncio —
ports merely _declare_ the signature the domain expects. The domain never
awaits or schedules coroutines; it treats port methods as abstract contracts.

Pure-computation ports (e.g., `AllocationPolicy`) use synchronous signatures.

**`services.py`** — Cross-entity domain logic.

```python
def match_task_to_node(
    task: Task,
    engine: Engine,
    free_machines: list[ConnectedMachine],
) -> ConnectedMachine | None: ...
```

**`exceptions.py`** — Domain error hierarchy (see §4.2).

### 3.2 Persistence Adapter (`yascheduler/adapters/persistence/`) — ✅ implemented

**`postgres.py`** — `PostgresTaskRepository` and `PostgresNodeRepository`
implementing the domain ports via pg8000. Maps between DB rows and domain
entities (`Task`/`Node` ↔ `TaskModel`/`NodeModel` conversions happen in
`db.py` wrapper).

**`postgres_uow.py`** — `PostgresUnitOfWork` implementing the UoW pattern:
manages a shared pg8000 `Connection` across repositories with
`commit()`/`rollback()` semantics.

**`sql_loader.py`** — `load_query(name)` loads `.sql` files from
`sql/` directory with `@functools.lru_cache`.

**`sql/`** — SQL files organized by entity:

```txt
sql/
├── schema.sql
├── task/
│   ├── get_by_id.sql
│   ├── list_by_status.sql
│   ├── list_by_jobs.sql
│   ├── insert.sql
│   ├── update.sql
│   └── count_by_status.sql
└── node/
    ├── get_by_ip.sql
    ├── list_enabled.sql
    ├── list_disabled.sql
    ├── insert.sql
    ├── insert_tmp.sql
    ├── update.sql
    ├── enable.sql
    ├── disable.sql
    └── remove.sql
```

`db.py` wraps these repositories, converting between its legacy
`TaskModel`/`NodeModel` (attrs) and domain `Task`/`Node` (dataclasses).
The legacy public API of `db.py` is unchanged — cloud modules and scheduler
still call `DB` methods. `db.py` delegates internally to the new
repositories.

### 3.3 Application (`yascheduler/application/`) — planned

**Use cases** orchestrate domain objects through ports. Each use case is a
single function or small class.

```python
# application/allocate_task.py
async def allocate_task(
    task_id: int,
    uow_factory: Callable[[], AbstractUnitOfWork],
    machines: MachineGateway,
    engine: Engine,
    notifier: Notifier | None = None,
) -> None:
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
        engine.validate_inputs(task.context)
        free_machines = await machines.list_free(engine.platforms)
        node = match_task_to_node(task, engine, free_machines)
        if node is None:
            raise NoCompatibleNodeError(task_id, engine.platforms)
        task = task.allocate_to(node.ip)
        machine = node.occupy()
        await uow.tasks.save(task)
        await uow.commit()
    if notifier:
        await notifier.task_allocated(task)
```

**Daemon orchestrator** — Long-running daemon polls the database, enqueues
tasks, dispatches to use cases. Producer-consumer loops live here, not in
`scheduler.py`. Manages `UniqueQueue`, concurrency limits, cancellation,
and the poll-sleep-dispatch cycle.

**Unit of Work** (`uow.py`) — Protocol. `PostgresUnitOfWork` already exists
in the persistence adapter; `AbstractUnitOfWork` Protocol will live here.

```python
class AbstractUnitOfWork(Protocol):
    tasks: TaskRepository
    nodes: NodeRepository
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *args) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

**Domain Events** (phase 3.5) — Use cases record events on aggregates.
After `uow.commit()`, the message bus dispatches them to handlers.

### 3.4 Remaining Adapters — planned

**`ssh/gateway.py`** (phase 4) — Implements `MachineGateway` using asyncssh.
Replaces the domain/infrastructure mixing currently in `remote_machine/`.

**`cloud/`** (phase 4) — Cloud providers as adapters implementing
`CloudProvisioner`.

**`notifier/webhook.py`** — `aiohttp`-based webhook dispatcher. Handles
retry, rate limiting, and error logging. Becomes a domain-event handler in
phase 3.5.

**`cli/commands.py`** (phase 5) — Thin wrappers calling use cases. Replaces
the current monolithic `utils.py`.

### 3.5 Configuration & DI — planned

**`di.py`** — Composition root. Multiple factory functions, one per entry
point:

```python
def make_cli_deps(config: Config) -> CLIDeps: ...
def make_daemon(config: Config) -> Orchestrator: ...
def make_aiida(config: Config) -> ...: ...
```

Each factory creates only the adapters and use cases needed by that entry
point. `yastatus` does not instantiate SSH connections or cloud providers.

Config (`config/`) currently uses attrs. Migration to dataclasses is
deferred to phase 5.6 — no functional benefit, purely consistency.

---

## 4. Key Design Topics

### 4.1 Sync Domain / Async Adapters

- Domain methods are synchronous — they compute, validate, and return.
- All I/O ports (`TaskRepository`, `MachineGateway`, `CloudProvisioner`) use
  `async def`. This does **not** violate domain purity: the domain only
  _declares_ the contract; it never executes coroutines.
- Use cases are `async def` — they `await` repository calls, pass results to
  sync domain services, and `await` the result back to storage.
- pg8000 is synchronous; it runs in a `ThreadPoolExecutor` inside the
  persistence adapter.

### 4.2 Exception Hierarchy

```txt
DomainError                      (domain/exceptions.py) ✅
├── ValidationError
│   ├── UnsupportedEngineError
│   └── MissingInputFileError
├── TaskError
│   ├── TaskAlreadyAllocatedError
│   └── TaskNotAllocatedError
├── MachineBusyError
└── SchedulingError
    ├── NoCompatibleNodeError
    └── CloudCapacityExhaustedError

ApplicationError                  (yascheduler/exceptions.py — planned)
└── InfrastructureError
    ├── PersistenceError
    ├── MachineCommunicationError
    └── CloudProvisioningError
```

- `DomainError` subclasses carry domain context (task_id, engine name, etc.).
- Use cases catch `ValidationError` → mark task DONE with error (fatal),
  `SchedulingError` → retry later (transient),
  `InfrastructureError` → log and retry.
- New exception classes replace old `RuntimeError("string")` and string-based
  status codes as each use case is migrated.

### 4.3 Unit of Work

- Each use case gets a fresh UoW via factory.
- UoW manages transaction boundaries: `commit()` succeeds or `rollback()` on
  exception.
- Multiple repositories within one use case share the same connection and
  transaction.
- Domain events are collected during the UoW and dispatched **after** commit
  (phase 3.5).

### 4.4 SQL in Files

- One file per query, named `entity/operation.sql`.
- Lazy-loaded via `load_query(name)` → `@functools.lru_cache` → plain string.
- Parameter placeholders use pg8000 `:param` style.
- Schema DDL lives in `sql/schema.sql`; migrations in `sql/migrations/`.
- `TaskRepository.save(task)` does a full-row `UPDATE` (all columns).

### 4.5 `class Yascheduler` (Public API)

- Remains in `client.py` as a **facade**.
- Internally delegates to use cases obtained from `di.make_cli_deps()`.
- Public API (method signatures) is preserved — no breaking change.
- **Phase 3 requirement**: `client.py` must stop importing `scheduler.py` and
  switch to calling `SubmitTask` use case directly. Currently
  `queue_submit_task_async()` does `from .scheduler import Scheduler` and
  calls `Scheduler.create()` — this instantiates the entire daemon graph
  just to insert a task row.
- AiiDA plugin continues to import `Yascheduler` unchanged.

### 4.6 GRACE-lite

- GRACE-lite markup rules unchanged.
- Before each phase: update contracts in affected files, update knowledge
  graph.
- After implementation: validate with `grace_check.py`.

---

## 5. Project Structure

Current state with planned additions marked `← planned`:

```txt
yascheduler/
├── domain/                          ✅
│   ├── __init__.py
│   ├── model.py
│   ├── services.py
│   ├── ports.py
│   └── exceptions.py
├── adapters/
│   ├── __init__.py
│   └── persistence/                 ✅
│       ├── __init__.py
│       ├── postgres.py
│       ├── postgres_uow.py
│       ├── sql_loader.py
│       └── sql/
│           ├── schema.sql
│           ├── task/*.sql
│           └── node/*.sql
├── application/                     ← planned (phase 3)
│   ├── submit_task.py
│   ├── allocate_task.py
│   ├── consume_task.py
│   ├── deallocate_nodes.py
│   ├── orchestrator.py
│   ├── uow.py
│   ├── events.py                    ← phase 3.5
│   └── message_bus.py               ← phase 3.5
├── adapters/
│   ├── persistence/                 ✅ (see above)
│   ├── ssh/                         ← planned (phase 4)
│   │   ├── gateway.py
│   │   └── platform/
│   ├── cloud/                       ← planned (phase 4)
│   │   ├── manager.py
│   │   └── providers/
│   ├── cli/                         ← planned (phase 5)
│   │   └── commands.py
│   └── notifier/
│       └── webhook.py
├── config.py                        ← planned (single module, phase 5.6)
├── di.py                            ← planned (phase 3)
├── exceptions.py                    ← planned (ApplicationError hierarchy)
│
├── client.py                        # facade — to delegate to use cases
├── scheduler.py                     # to thin: loops + use-case calls
├── aiida_plugin.py                  # unchanged
├── db.py                            # wrapper delegating to persistence
├── utils.py                         # to replace → adapters/cli/
├── clouds/                          # to migrate → adapters/cloud/
├── remote_machine/                  # to migrate → adapters/ssh/
├── config/                          # to merge → config.py (phase 5.6)
├── queue.py                         # retained (no domain coupling)
├── time.py                          # retained (utility)
├── compat.py                        # retained (compatibility shim)
└── variables.py                     # retained (path constants)
```

---

## 6. Migration Plan

### Phase 3 — Application Layer & DI

**Goal**: Use cases replace inline logic in `scheduler.py`. Scheduler thins.

- Create `application/submit_task.py`, `allocate_task.py`,
  `consume_task.py`, `deallocate_nodes.py`.
- Create `application/orchestrator.py` — daemon poll loops and concurrency
  management (extracted from `scheduler.py` start/stop and
  `create_producer_consumers`).
- Create `di.py` with `make_daemon()` and `make_cli_deps()` factories.
- `scheduler.py` producer-consumer loops call use cases instead of inline
  methods.
- `utils.py` CLI commands call use cases via `make_cli_deps()`.
- **Break `client.py` → `scheduler.py` import**: `class Yascheduler` switches
  from `Scheduler.create()` to `SubmitTask` use case via `make_cli_deps()`.
- `class Yascheduler` delegates to use cases.

### Phase 3.5 — Domain Events (optional but recommended)

**Goal**: Decouple webhook and side-effects from use cases.

- Create `application/events.py` with event dataclasses.
- Create `application/message_bus.py` with dispatch loop.
- Create `adapters/notifier/webhook.py` as event handler.
- Use cases record events; message bus dispatches after `uow.commit()`.
- Remove scattered `do_task_webhook()` calls from use cases.

### Phase 4 — SSH & Cloud Adapters

**Goal**: Move `remote_machine/` and `clouds/` into `adapters/`.

- Split `RemoteMachine` → `ConnectedMachine` (domain) + `SSHMachineGateway`
  (adapter). Ephemeral connection wrapping `Node`.
- Move cloud providers into `adapters/cloud/providers/`.

  At this point cloud modules switch from `db.py` (old wrapper) to
  `NodeRepository` (port). The `db.py` wrapper can be retired for cloud
  code paths.

- Old modules (`remote_machine/`, `clouds/`) become re-export wrappers, then
  removed.
- Tests updated to use adapter interfaces.

### Phase 5 — CLI Decoupling

**Goal**: `utils.py` becomes thin CLI wrappers in `adapters/cli/`.

- Move CLI command functions to `adapters/cli/commands.py`.
- Each command calls use cases from `di.make_cli_deps()`.
- `utils.py` becomes re-export wrapper, then removed.
- `Yascheduler` facade in `client.py` validated against existing API consumers.

### Phase 5.5 — Connection Pool (optional)

**Goal**: Replace `ThreadPoolExecutor(max_workers=1)` with a connection pool.

- Implement `PgPool` (asyncio.Queue-based) in persistence adapter.
- UoW acquires/releases connections from pool.
- Enables parallel DB access across concurrent use cases.
- Low priority — the single-executor design is not a proven bottleneck.

### Phase 5.6 — Config attrs → dataclasses (optional)

**Goal**: Remove attrs from the config package for consistency.

- Replace attrs decorators and `make_default_field()` with stdlib
  `dataclasses`.
- No functional change, purely for dependency hygiene.
- Lowest priority — can be done incrementally or deferred indefinitely.

---

## 7. Testing Strategy

### 7.1 Fake Adapters (unit tests)

For every port in `domain/ports.py`, provide an in-memory fake:

| Port               | Fake                                                       |
| ------------------ | ---------------------------------------------------------- |
| `TaskRepository`   | `FakeTaskRepository` (dict-backed, like current `FakeDB`)  |
| `NodeRepository`   | `FakeNodeRepository` (dict-backed)                         |
| `MachineGateway`   | `FakeMachineGateway` (stubbed SSH, returns canned results) |
| `CloudProvisioner` | `FakeCloudProvisioner` (stubbed cloud, returns canned IPs) |

Use cases are tested with fakes: no real DB, no real SSH, no real cloud.

### 7.2 Integration Tests

| Layer              | Tool                            | When    |
| ------------------ | ------------------------------- | ------- |
| Persistence        | `testcontainers[postgres]`      | ✅ done |
| Use case + real DB | testcontainers + fake SSH/cloud | Phase 3 |
| SSH adapter        | Docker SSH server               | Phase 4 |
| Cloud adapter      | Staged (manual) or mock HTTP    | Phase 4 |

### 7.3 Smoke Tests (Public API)

Before and after each phase, run smoke tests that cover:

- All CLI entry points (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`,
  `yainit`, `yascheduler`)
- `class Yascheduler` public methods (submit, get, list — sync and async)
- AiiDA plugin scheduler entry point

### 7.4 Multi-Use-Case Tests

Allocate → Consume → Deallocate as a full lifecycle test:

- Real DB (testcontainers)
- Faked SSH (`FakeMachineGateway` that simulates a job completing)
- Faked cloud (`FakeCloudProvisioner`)
- Verifies task transitions through TO_DO → RUNNING → DONE and node
  deallocation.

---

## 8. Open Questions

| Topic                      | Status                                      |
| -------------------------- | ------------------------------------------- |
| AiiDA plugin evolution     | Keep importing `Yascheduler` facade for now |
| Monitoring/metrics         | Not addressed; domain events enable it      |
| Connection pool            | Deferred to phase 5.5 (optional)            |
| Config attrs → dataclasses | Deferred to phase 5.6 (optional)            |
