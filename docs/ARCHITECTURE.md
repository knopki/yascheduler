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

yascheduler is a single Python package (`yascheduler/`) with no formal
layering. The daemon orchestrator (`scheduler.py`, ~800 LOC) is the hub —
it depends on almost every other module and contains business logic,
infrastructure calls, webhook dispatch, and lifecycle management in one
class.

```txt
┌────────────────────────────────────────────────────────────────┐
│                        scheduler.py                            │
│  (allocator, consumer, deallocator, webhooks, stats, …)        │
└───┬───────┬──────────┬───────────┬──────────┬─────────────────┘
    │       │          │           │          │
    ▼       ▼          ▼           ▼          ▼
   db    clouds    remote_mach   config     queue
 (pg8000) (az/hetzner/ (SSH/SFTP) (INI/attrs) (UniqueQueue)
           upcloud)
```

### 1.2 Key Components

| Component         | Responsibility                                          |
| ----------------- | ------------------------------------------------------- |
| `scheduler.py`    | God object: all producer-consumer loops, task lifecycle |
| `db.py`           | PostgreSQL via pg8000 in ThreadPoolExecutor             |
| `clouds/`         | Multi-cloud VM provisioning (Azure, Hetzner, UpCloud)   |
| `remote_machine/` | SSH connection, platform detection, command execution   |
| `config/`         | Config tree parsed from INI (uses attrs)                |
| `utils.py`        | CLI entry points (6 commands), ~540 LOC                 |
| `client.py`       | Public Python API (`class Yascheduler`)                 |
| `aiida_plugin.py` | AiiDA scheduler integration                             |

### 1.3 Pain Points

- **No domain layer** — business rules mixed with DB queries and SSH calls.
- **`scheduler.py` is 806 lines** — violates single responsibility.
- **Unclear error handling** — mix of `RuntimeError("string")`, `assert`,
  status-code strings in DB, and generic `except Exception: log`.
- **`attrs` in domain/config** — domain objects depend on a third-party
  library; config uses attrs but will be migrated last (low priority).
- **`pg8000` in ThreadPoolExecutor(max_workers=1)** — serializes all DB access.
- **Webhook logic scattered across 5 call sites** with inconsistent ordering
  relative to `commit()`.
- **No explicit ports/contracts** — modules import concrete implementations
  directly.
- **`client.py` imports `scheduler.py`** — submitting a task instantiates the
  entire daemon dependency graph just to insert a DB row.
- **`utils.py` CLI commands mix** argparse, DB, SSH, and cloud-init in one file.
- **`TaskModel.metadata` is a god-dict** — 8+ keys with different semantics
  (`engine`, `remote_folder`, `local_folder`, `webhook_url`, base64 file
  contents, `error`) with no contract.

---

## 2. Target Architecture

### 2.1 Hexagonal + DDD (Architecture Patterns with Python)

Dependencies point inward. The domain knows nothing about infrastructure.

```txt
┌──────────────────────────────────────────────────────────────────┐
│                          DOMAIN                                   │
│  model.py        Task, Node, ConnectedMachine, Engine,           │
│                  TaskContext, TaskStatus (frozen dataclasses)     │
│  services.py     SchedulingService, AllocationPolicy              │
│  ports.py        TaskRepository, NodeRepository, MachineGateway, │
│                  CloudProvisioner (Protocols)                     │
│  exceptions.py   DomainError hierarchy                           │
│                  (depends on: stdlib only)                        │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│                       APPLICATION                                │
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
│                        ADAPTERS                                   │
│  persistence/postgres.py      PostgresTaskRepository             │
│  persistence/sql/             query files + schema.sql            │
│  ssh/gateway.py               SSHMachineGateway (phase 4)        │
│  cloud/                       Azure/Hetzner/UpCloud (phase 4)    │
│  cli/commands.py              Thin CLI wrappers (phase 5)        │
│  notifier/webhook.py          aiohttp webhook dispatcher         │
│                  (depends on: domain, application)                │
└──────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│                     COMPOSITION ROOT                              │
│  config.py         INI → dataclass settings (no attrs)           │
│  di.py             Factories: make_cli_deps(), make_daemon(),    │
│                    make_aiida()                                   │
│                  (depends on: everything — wires the graph)       │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 Design Decisions

| Decision                 | Choice                            | Rationale                                       |
| ------------------------ | --------------------------------- | ----------------------------------------------- |
| Domain model library     | stdlib `dataclasses`              | Zero dependencies in domain                     |
| Model library elsewhere  | `attrs` removed everywhere        | Config last (low priority, no functional gain)  |
| Port definitions         | `typing.Protocol`                 | Structural subtyping, no inheritance required   |
| Domain layer concurrency | Synchronous                       | Simpler, testable, no I/O                       |
| Application/adapters     | Async (`async def`)               | Matches existing asyncssh, aiohttp, asyncio     |
| Persistence              | pg8000, raw SQL in `.sql` files   | No ORM overhead, SQL tooling friendly           |
| DI                       | Manual, no container              | Project size doesn't justify framework overhead |
| Unit of Work             | Factory-injected into use case    | Transaction per use case, testable with fakes   |
| Domain Events            | Deferred to phase 3.5             | Requires stable UoW first                       |
| Bounded contexts         | Monolith with internal boundaries | Avoids cross-context boilerplate                |
| Project structure        | Layered (domain/app/adapters)     | "Screaming architecture", clear import rules    |

### 2.3 Import Rules

```txt
domain/       → may NOT import from yascheduler at all (stdlib only)
application/  → may import domain/
adapters/     → may import domain/, application/
di.py         → may import everything (top of dependency graph)
config.py     → may import nothing from yascheduler
```

Enforcement via tooling (e.g., `import-linter` or `layer-lint`) is out of
scope for the architecture migration; add via a separate proposal.

---

## 3. Layer Details

### 3.1 Domain (`yascheduler/domain/`)

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

# ── Value Objects ────────────────────────────────────

@dataclass(frozen=True)
class Engine:
    """Calculation engine: what command, what files, what platforms."""
    name: str
    spawn: str
    input_files: tuple[str, ...]
    output_files: tuple[str, ...]
    platforms: tuple[str, ...]
    check_cmd: str | None = None
    check_pname: str | None = None

    def validate_inputs(self, context: TaskContext) -> None:
        """Raise ValidationError if required input files are missing."""
        for f in self.input_files:
            if f not in context.extra:
                raise MissingInputFileError(self.name, f)

@dataclass(frozen=True)
class TaskContext:
    """
    Typed wrapper for task metadata. Known fields are explicit;
    arbitrary extras preserved in `extra` (backward compatibility).
    """
    engine: str
    remote_folder: str | None = None
    local_folder: str | None = None
    webhook_url: str | None = None
    webhook_custom_params: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

# ── Entities ─────────────────────────────────────────

@dataclass(frozen=True)
class Task:
    """Aggregate root for the task lifecycle."""
    task_id: int
    label: str
    status: TaskStatus
    context: TaskContext
    allocated_ip: str | None = None

    def allocate_to(self, ip: str) -> "Task":
        if self.status != TaskStatus.TO_DO:
            raise TaskAlreadyAllocatedError(self.task_id)
        return replace(self, allocated_ip=ip)

    def mark_running(self) -> "Task":
        if self.status != TaskStatus.TO_DO:
            raise TaskAlreadyAllocatedError(self.task_id)
        return replace(self, status=TaskStatus.RUNNING)

    def complete(self) -> "Task":
        if self.status != TaskStatus.RUNNING:
            raise TaskNotAllocatedError(self.task_id)
        return replace(self, status=TaskStatus.DONE)

    def fail(self, reason: str) -> "Task":
        return replace(
            self,
            status=TaskStatus.DONE,
            context=replace(self.context, error=reason),
        )

@dataclass(frozen=True)
class Node:
    """Persistent node record (DB row)."""
    ip: str
    ncpus: int
    enabled: bool
    cloud: str | None = None
    username: str = "root"
    port: int = 22

@dataclass(frozen=True)
class ConnectedMachine:
    """
    Runtime representation of an SSH-connected machine.

    Backed by a `Node` (persistent) but adds ephemeral state
    (platform, ncpus detected at runtime, busy/free tracking).
    """
    ip: str
    platform: str
    ncpus: int
    state: MachineState
    free_since: float | None = None

    def is_compatible(self, platforms: tuple[str, ...]) -> bool:
        return self.state == MachineState.FREE and self.platform in platforms

    def occupy(self) -> "ConnectedMachine":
        if self.state != MachineState.FREE:
            raise MachineBusyError(self.ip)
        return replace(self, state=MachineState.BUSY)

    def release(self) -> "ConnectedMachine":
        return replace(
            self, state=MachineState.FREE, free_since=time.monotonic()
        )

@dataclass(frozen=True)
class ProcessResult:
    """Result of a command executed on a remote machine."""
    exit_code: int
    stdout: str = ""
    stderr: str = ""
```

Validation in `__post_init__` for simple checks; separate validation functions
for complex rules (e.g., `Engine` input/output file lists vs provided
metadata).

**`ports.py`** — Abstract interfaces as Protocols.

```python
from typing import Protocol

class TaskRepository(Protocol):
    async def get(self, task_id: int) -> Task: ...
    async def save(self, task: Task) -> None: ...  # full row UPDATE — see §4.4
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
Adapting a sync-only transport would be done inside the adapter, transparent
to the domain.

Pure-computation ports (e.g., `AllocationPolicy`) use synchronous signatures.

**`services.py`** — Domain services for cross-entity operations that don't
belong to any single entity. Entity-level logic (status transitions,
validation, compatibility checks) lives on the entities themselves.

```python
def match_task_to_node(
    task: Task,
    engine: Engine,
    free_machines: list[ConnectedMachine],
) -> ConnectedMachine | None:
    """Find the best free machine for a task. Cross-entity: Task +
    ConnectedMachine + Engine. Returns the matched machine or None."""
    candidates = [m for m in free_machines if m.is_compatible(engine.platforms)]
    return candidates[0] if candidates else None
```

**`exceptions.py`** — Domain error hierarchy (see §4.2).

### 3.2 Application (`yascheduler/application/`)

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

        # domain validation (on the entity, not in the use case)
        engine.validate_inputs(task.context)

        free_machines = await machines.list_free(engine.platforms)
        node = match_task_to_node(task, engine, free_machines)
        if node is None:
            raise NoCompatibleNodeError(task_id, engine.platforms)

        # domain operations (encapsulated business rules)
        task = task.allocate_to(node.ip)
        machine = node.occupy()

        await uow.tasks.save(task)
        await uow.commit()
    if notifier:
        await notifier.task_allocated(task)
```

**Daemon orchestrator** — The long-running daemon polls the database,
enqueues tasks, and dispatches to use cases. Producer-consumer loops live
here (or in a dedicated `application/orchestrator.py`), not in the scheduler
adapter. This is the only place that manages `UniqueQueue`, concurrency
limits, cancellation, and the poll-sleep-dispatch cycle. It calls use cases
as plain async functions.

**Unit of Work** (`uow.py`) — Protocol. Implementations in adapters.

```python
class AbstractUnitOfWork(Protocol):
    tasks: TaskRepository
    nodes: NodeRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *args) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

UoW is created by a factory injected into use cases. This allows tests to
substitute `FakeUnitOfWork` with in-memory repositories.

**Domain Events** (phase 3.5) — Use cases record events on aggregates.
After `uow.commit()`, the message bus dispatches them to handlers.

```txt
TaskCreated → [webhook_handler]
TaskAllocated → [webhook_handler, occupancy_handler]
TaskCompleted → [webhook_handler, cleanup_handler]
TaskFailed → [webhook_handler]
```

Events decouple side effects from business logic. Handlers are testable
independently.

### 3.3 Adapters (`yascheduler/adapters/`)

**`persistence/postgres.py`** — Implements `TaskRepository` and
`NodeRepository` for PostgreSQL via pg8000. SQL queries are loaded from
`.sql` files with lazy caching.

**`persistence/sql/`** — SQL files organized by entity:

```txt
sql/
├── schema.sql               # Current schema DDL
├── task/
│   ├── get_by_id.sql
│   ├── list_by_status.sql
│   ├── insert.sql
│   └── update_status.sql
├── node/
│   ├── get_by_ip.sql
│   ├── list_enabled.sql
│   └── …
└── migrations/               # Schema migrations (future)
    └── …
```

Queries loaded via `load_query("task/get_by_id")` → `@functools.cache` → str.

**`ssh/gateway.py`** (phase 4) — Implements `MachineGateway` using asyncssh.
Replaces the domain/infrastructure mixing currently in `remote_machine/`.

**`cloud/`** (phase 4) — Cloud providers as adapters implementing
`CloudProvisioner`.

**`notifier/webhook.py`** — `aiohttp`-based webhook dispatcher. Handles
retry, rate limiting, and error logging. Becomes a domain-event handler in
phase 3.5.

**`cli/commands.py`** (phase 5) — Thin wrappers calling use cases. Replaces
the current monolithic `utils.py`.

### 3.4 Configuration & DI

**`config.py`** — Reads INI file via `ConfigParser`, returns a plain
dataclass (no attrs). Sections map to nested dataclasses. Currently the
config package uses attrs; migration to dataclasses is deferred to a late
phase (no functional benefit, just consistency).

`Config` holds its own `EngineConfig` dataclass (INI-shaped). `di.py`
converts `EngineConfig` → domain `Engine` during wiring. This keeps the
import rule intact: `config.py` does not import from `domain/`.

**`di.py`** — Composition root. Multiple factory functions, one per
entry point:

```python
def make_cli_deps(config: Config) -> CLIDeps:
    """Lightweight deps for yasubmit, yastatus, yasetnode, yanodes."""
    ...

def make_daemon(config: Config) -> Orchestrator:
    """Full graph for the daemon: SSH pool, cloud manager, all use cases."""
    ...

def make_aiida(config: Config) -> ...:
    """Deps for the AiiDA plugin entry point."""
    ...
```

Each factory creates only the adapters and use cases needed by that entry
point. `yastatus` does not instantiate SSH connections or cloud providers.

---

## 4. Key Design Topics

### 4.1 Sync Domain / Async Adapters

- Domain methods are synchronous — they compute, validate, and return.
- All I/O ports (`TaskRepository`, `MachineGateway`, `CloudProvisioner`) use
  `async def`. This does **not** violate domain purity: the domain only
  _declares_ the contract; it never executes coroutines. The async boundary
  exists in adapters and use cases, not in domain logic.
- Use cases are `async def` — they `await` repository calls, pass results to
  sync domain services, and `await` the result back to storage.
- pg8000 is synchronous; it runs in a `ThreadPoolExecutor` inside the
  persistence adapter.

### 4.2 Exception Hierarchy

```txt
DomainError                      (domain/exceptions.py)
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

ApplicationError                  (yascheduler/exceptions.py)
└── InfrastructureError
    ├── PersistenceError
    ├── MachineCommunicationError
    └── CloudProvisioningError
```

- `DomainError` subclasses carry domain context (task_id, engine name, etc.).
- Use cases catch `ValidationError` → mark task DONE with error in `TaskContext`
  (fatal — invalid input),
  `SchedulingError` → retry later (transient — no node available yet),
  `InfrastructureError` → log and retry.
- Adapters raise `InfrastructureError` subclasses; never raise `DomainError`.
- New exception classes replace old `RuntimeError("string")` and string-based
  status codes as each use case is migrated. No upfront mapping table needed.

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
- Lazy-loaded via `load_query(name)` → `@functools.cache` → plain string.
- Parameter placeholders use pg8000 `:param` style.
- Schema DDL lives in `sql/schema.sql`; migrations in `sql/migrations/`.
- `TaskRepository.save(task)` does a full-row `UPDATE` (all columns) rather
  than partial field updates. This simplifies the port at the cost of always
  writing every column — acceptable given the row width and write frequency.
- Tooling: `sqlfluff` for linting, `psql -f` for manual execution.

### 4.5 `class Yascheduler` (Public API)

- Remains in `client.py` as a **facade**.
- Internally delegates to use cases obtained from `di.make_cli_deps()`.
- Public API (method signatures) is preserved — no breaking change.
- **Phase 3 requirement**: `client.py` must stop importing `scheduler.py` and
  switch to calling `SubmitTask` use case directly. Currently
  `queue_submit_task_async()` does `from .scheduler import Scheduler` and
  calls `Scheduler.create()` — this instantiates the entire daemon graph
  (DB, clouds, SSH) just to insert a task row. The facade will call the
  use case via DI instead.
- AiiDA plugin continues to import `Yascheduler` unchanged.

### 4.6 GRACE-lite

- GRACE-lite markup rules unchanged.
- Before each phase: update contracts in affected files, update knowledge
  graph.
- After implementation: validate with `grace_check.py`.

---

## 5. Project Structure (Target)

```txt
yascheduler/
├── domain/
│   ├── model.py
│   ├── services.py
│   ├── ports.py
│   └── exceptions.py
├── application/
│   ├── submit_task.py
│   ├── allocate_task.py
│   ├── consume_task.py
│   ├── deallocate_nodes.py
│   ├── orchestrator.py       # long-running daemon loops
│   ├── uow.py
│   ├── events.py              # phase 3.5
│   └── message_bus.py         # phase 3.5
├── adapters/
│   ├── persistence/
│   │   ├── postgres.py
│   │   ├── postgres_uow.py
│   │   └── sql/
│   │       ├── schema.sql
│   │       ├── task/
│   │       │   ├── get_by_id.sql
│   │       │   └── ...
│   │       ├── node/
│   │       │   ├── get_by_ip.sql
│   │       │   └── ...
│   │       └── migrations/
│   ├── ssh/                   # phase 4
│   │   ├── gateway.py
│   │   └── platform/
│   ├── cloud/                 # phase 4
│   │   ├── manager.py
│   │   └── providers/
│   ├── cli/                   # phase 5
│   │   └── commands.py
│   └── notifier/
│       └── webhook.py
├── config.py
├── di.py
├── exceptions.py              # ApplicationError hierarchy
├── client.py                  # class Yascheduler (facade)
├── scheduler.py               # thinned: loops + use-case calls
├── aiida_plugin.py            # unchanged
│
├── db.py                      # → wrapper, then removed
├── utils.py                   # → wrapper, then removed
├── clouds/                    # → adapters/cloud/, then removed
├── remote_machine/            # → adapters/ssh/, then removed
├── config/                    # → config.py, then removed
├── queue.py                   # retained (no domain coupling)
├── time.py                    # retained (utility)
├── compat.py                  # retained (compatibility shim)
└── variables.py               # retained (path constants)
```

---

## 6. Migration Plan

### Phase 1 — Domain Model & Ports

**Goal**: Define domain entities and port interfaces. No behavior change.

- Create `domain/model.py` — `Task`, `Node`, `ConnectedMachine`, `Engine`,
  `TaskContext`, `TaskStatus`, `MachineState`.
- Create `domain/ports.py` — `TaskRepository`, `NodeRepository`,
  `MachineGateway`, `CloudProvisioner` as Protocols.
- Create `domain/exceptions.py` — `DomainError` hierarchy (base classes:
  `ValidationError`, `TaskError`, `SchedulingError`).
- Create `domain/services.py` — `match_task_to_node()` (extracted from
  `allocate_task`).
- Existing code unchanged. Domain code is not yet wired in.

### Phase 2 — Persistence Adapter

**Goal**: New DB layer behind the domain ports. Old `db.py` becomes a wrapper.

- Create `adapters/persistence/sql/` with query files extracted from `db.py`.
- Create `adapters/persistence/postgres.py` implementing `TaskRepository` and
  `NodeRepository`.
- Create `adapters/persistence/postgres_uow.py` implementing
  `AbstractUnitOfWork`.
- Modify `db.py` to delegate to `PostgresTaskRepository` / `NodeRepository`
  internally. External API of `db.py` unchanged.
- **Important**: `db.py` remains the **sole** persistence path for cloud
  modules (`CloudAPIManager`, `CloudAPI`) until phase 4. The cloud modules
  currently call `DB` methods directly — they continue to do so through the
  wrapper. The new `PostgresTaskRepository` serves the scheduler and CLI use
  cases; cloud modules are migrated in phase 4.
- Add unit tests for repositories with `FakeDB`-style in-memory doubles.

### Phase 2.5 — Schema Migrations

**Goal**: Managed schema evolution before the long architecture migration
completes.

- Add migration framework (or simple versioned SQL files).
- Allow schema changes to support new features without waiting for phase 5.

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

### 7.1 Characterization Tests (per phase)

Before refactoring any module, add characterization tests that capture
current behavior — especially error paths, edge cases, and implicit contracts
(e.g., webhook ordering relative to `commit()`). These tests run against
the _old_ code and validate that the _new_ code preserves behavior.

### 7.2 Fake Adapters (unit tests)

For every port in `domain/ports.py`, provide an in-memory fake:

| Port               | Fake                                                       |
| ------------------ | ---------------------------------------------------------- |
| `TaskRepository`   | `FakeTaskRepository` (dict-backed, like current `FakeDB`)  |
| `NodeRepository`   | `FakeNodeRepository` (dict-backed)                         |
| `MachineGateway`   | `FakeMachineGateway` (stubbed SSH, returns canned results) |
| `CloudProvisioner` | `FakeCloudProvisioner` (stubbed cloud, returns canned IPs) |

Use cases are tested with fakes: no real DB, no real SSH, no real cloud.

Fakes are verified against their Protocols with a conformance test (e.g.,
`isinstance(fake, TaskRepository)` with `@runtime_checkable` decorators)
to catch drift between port definition and fake implementation.

### 7.3 Integration Tests

| Layer              | Tool                            | When    |
| ------------------ | ------------------------------- | ------- |
| Persistence        | `testcontainers[postgres]`      | Phase 2 |
| Use case + real DB | testcontainers + fake SSH/cloud | Phase 3 |
| SSH adapter        | Docker SSH server               | Phase 4 |
| Cloud adapter      | Staged (manual) or mock HTTP    | Phase 4 |

UoW commit/rollback semantics are verified in persistence integration tests.

### 7.4 Smoke Tests (Public API)

Before and after each phase, run smoke tests that cover:

- All CLI entry points (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`,
  `yainit`, `yascheduler`)
- `class Yascheduler` public methods (submit, get, list — sync and async)
- AiiDA plugin scheduler entry point

Smoke tests use fakes or a light testcontainers setup. Goal: catch
regressions in the public API contract.

### 7.5 Multi-Use-Case Tests

Allocate → Consume → Deallocate as a full lifecycle test:

- Real DB (testcontainers)
- Faked SSH (`FakeMachineGateway` that simulates a job completing)
- Faked cloud (`FakeCloudProvisioner`)
- Verifies task transitions through TO_DO → RUNNING → DONE and node
  deallocation.

---

## 8. Open Questions

| Topic                       | Status                                      |
| --------------------------- | ------------------------------------------- |
| `Engine` as value object    | Accepted; added to domain model (§3.1)      |
| `TaskContext` value object  | Accepted; added to domain model (§3.1)      |
| `Node` / `ConnectedMachine` | Accepted; separated in domain model (§3.1)  |
| AiiDA plugin evolution      | Keep importing `Yascheduler` facade for now |
| Migration framework         | Design in phase 2.5                         |
| Monitoring/metrics          | Not addressed; domain events enable it      |
| Connection pool             | Deferred to phase 5.5 (optional)            |
| Config attrs → dataclasses  | Deferred to phase 5.6 (optional)            |
