## Context

`yascheduler/db.py` is a ~540-LOC facade: `DB` (async wrapper over a pg8000
connection with `run`/`migrate`/`commit`/`close`), plus legacy attrs models
`TaskModel`/`NodeModel`/`TaskStatus` that mirror the canonical
`yascheduler.domain.model` types. It already delegates all persistence to
`PostgresTaskRepository`/`PostgresNodeRepository` and converts between its
legacy models and domain models. Production code no longer imports it
(`grep -rn "from yascheduler.db import" yascheduler/` → 0). The remaining
consumers are 10 test files, and `# FIXME: remove this module` sits at the top.

The canonical persistence contract is `PostgresUnitOfWork`
(`yascheduler/adapters/persistence/postgres_uow.py`) + the repository adapters
(`PostgresTaskRepository`, `PostgresNodeRepository`). `PostgresUnitOfWork.__init__(config, bus)`
requires a `MessageBus` (`yascheduler.application.message_bus.MessageBus`,
zero-arg ctor, `async dispatch(events)`). Schema is applied independently via
the sync `apply_schema(config)` helper (`postgres_schema.py`), already used by
both integration and e2e conftests.

## Goals / Non-Goals

**Goals:**
- Delete `yascheduler/db.py`; rely on existing tooling (ruff/zuban/import-linter)
  to catch any stray `import yascheduler.db` once the module is gone — no bespoke
  grep guard.
- Remove dead legacy test code: `tests/fixtures/models.py`,
  `tests/fixtures/fake_db.py`, `tests/unit/test_fake_db.py`,
  `tests/unit/test_models.py`, `tests/unit/test_db.py`.
- Migrate the 5 real consumers (integration `conftest`/`test_db_integration`/
  `test_persistence_adapter`, e2e `conftest`/`test_full_cycle`) to
  `PostgresUnitOfWork` + repos + `domain.TaskStatus`, with a `TRUNCATE`
  teardown path independent of `DB.run`.
- Retire `db-wrapper` spec; update `package-facades`, `test-db-integration`,
  `dependency-injection`, `testing-unit`, `e2e-testing`.
- Update `docs/knowledge-graph.xml` (remove `M-DB`) and `docs/ARCHITECTURE.md`.

**Non-Goals:**
- Extracting shared `FakeTaskRepository`/`FakeNodeRepository`/`FakeUnitOfWork`
  from the inline copies in `test_query_tasks.py`/`test_client_query.py` —
  separate refactor.
- Changing the production persistence layer, DI graph, CLI, INI, or DB schema.
- Adding new dependencies.

## Decisions

### D1: Conftest fixture shape — replace `db` with layered fixtures
Replace the single `db: DB` fixture with three composable fixtures in both
integration and e2e conftests:
- `pg_conn` (function-scoped): a raw `pg8000.native.Connection` built from
  `_db_config` on a single-worker `ThreadPoolExecutor`. Used for `TRUNCATE`
  teardown and for tests that construct repos directly
  (`test_persistence_adapter.py` does `PostgresTaskRepository(db.conn, db.executor)`).
- `pg_executor` (function-scoped): `ThreadPoolExecutor(max_workers=1)` (pg8000
  is not thread-safe). Shared by `pg_conn`, repo construction, and UoW.
- `uow_factory` (function-scoped): a `Callable[[], PostgresUnitOfWork]` that
  closes over `_db_config` and a session-shared bare `MessageBus()`. Tests do
  `async with uow_factory() as uow: ...`.

Teardown: `pg_conn` runs `TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE`
and closes the connection; shuts down the executor.

**Why layered over one `db`-shaped fixture:** `test_persistence_adapter.py`
needs raw `(conn, executor)` (it instantiates repos directly), while
`test_db_integration.py`/`test_full_cycle.py` want the UoW path. One fixture
can't cleanly serve both without re-exposing `DB`'s shape, which is what we're
removing. Layered fixtures keep each consumer honest about what it uses.

**Alternative considered:** a single `db` fixture returning a small dataclass
with `.conn`, `.executor`, `.uow()`. Rejected — reintroduces a facade-like
object; layered fixtures are simpler and GRACE-annotatable.

### D2: `test_persistence_adapter.py` migration — minimal
It already imports `PostgresTaskRepository`/`PostgresNodeRepository`/
`PostgresUnitOfWork`/`MessageBus`/`ConfigDb` and constructs repos via
`PostgresTaskRepository(db.conn, db.executor)`. Only change: replace the
`db: DB` fixture param with `pg_conn` + `pg_executor`, i.e.
`PostgresTaskRepository(pg_conn, pg_executor)`. Its two UoW tests
(`test_uow_integration`, `test_uow_rollback_integration`) already take
`_db_config` + `_init_schema` and build their own UoW — unchanged except the
`from yascheduler.db import DB` line is removed.

### D3: `test_db_integration.py` migration — rewrite to UoW + repos
The file tests the deleted facade, but exercises real PostgreSQL behavior
through it. Rewrite each test against `uow_factory` + repos:
- `db.add_node("ip","user",port=,ncpus=,cloud=,enabled=)` →
  `await uow.nodes.add(Node(ip=..., username=..., port=..., ncpus=..., cloud=..., enabled=...))`.
- `db.add_task(label=, ip_addr=, status=, metadata=)` → construct a domain
  `Task(task_id=0, label=, context=TaskContext.from_metadata(metadata), status=DomainTaskStatus(...))`,
  `await uow.tasks.insert(task)`, then `uow.commit()`.
- `db.set_task_running(id, ip)` → `get` → `task.allocate_to(ip).mark_running()` →
  `uow.tasks.save(...)`.
- `db.set_task_done`/`set_task_error` → `get` → rebuild `Task` with new
  context/status → `save`.
- `db.get_tasks_by_status([s])` → `uow.tasks.list_by_status({DomainTaskStatus(s.value)})`.
- `db.get_tasks_by_jobs([ids])` → `uow.tasks.list_by_jobs([ids])`.
- `db.get_task_ids_by_ip_and_status(ip, s)` → `uow.tasks.list_ids_by_ip_and_status(ip, DomainTaskStatus(...))`.
- `db.get_tasks_with_cloud_by_id_status(ids, s)` — **not a repo method**. The
  facade composed it from `_task_repo.list_by_jobs` + `_node_repo.get_by_ips`.
  Rewrite the test to compose the same way in-test:
  `tasks = await uow.tasks.list_by_jobs(ids); matching=[t for t in tasks if t.status==s];
  ips=[t.allocated_ip for t in matching if t.allocated_ip];
  nodes = await uow.nodes.get_by_ips(ips); assert cloud per ip`.
- `db.add_tmp_node("az","root")` → `uow.nodes.add_tmp("az", "root")`.
- `db.count_nodes_clouds()` → `uow.nodes.count_by_cloud()`;
  `db.count_nodes_by_status()` → `uow.nodes.count_by_status()`.
- **Delete `test_migrate_idempotency`**: `DB.migrate` is removed; schema is
  applied once per session by `apply_schema()`. The "call migrate twice"
  concern disappears with the legacy migration path; `apply_schema` itself is
  covered by `test_postgres_schema.py`.
- Re-source `TaskStatus` from `yascheduler.domain.model`.

**Alternative considered:** delete `test_db_integration.py` entirely and port
only unique scenarios into `test_persistence_adapter.py`. Rejected: keeping a
UoW-level integration suite (exercises the public UoW + repo composition, not
raw repos) provides orthogonal coverage to the repo-level suite.

### D4: `test_full_cycle.py` (e2e) migration
Same mapping as D3 for the `db.add_node`/`db.get_task`/`db.set_task_done`
calls. The "poll `db.get_task` until DONE" loop becomes
`async with uow_factory() as uow: t = await uow.tasks.get(id)`. Re-source
`TaskStatus` from `yascheduler.domain`. The e2e `db` fixture becomes the same
layered `pg_conn`/`pg_executor`/`uow_factory` set (D1).

Non-obvious renames specific to this file (domain `Task` vs legacy `TaskModel`):
- `task.ip` → `task.allocated_ip` (lines 98, 112).
- `task.metadata.get("local_folder")` → `task.context.local_folder` (line 116).
- `db.remove_node(ssh_container["host"])` → `uow.nodes.remove(ssh_container["host"])` (line 138).

### D5: `FakeDB` / `make_task`/`make_node` — delete, do not migrate
- `tests/fixtures/models.py`: **zero importers** (`grep "from tests.fixtures.models import"` = 0). Delete.
- `tests/fixtures/fake_db.py` + `tests/unit/test_fake_db.py`: `FakeDB` has no
  consumer other than its own test. Both are legacy-DB-shaped. Delete together.
- `tests/unit/test_models.py`: tests deleted `TaskModel`/`NodeModel`/`TaskStatus`;
  domain `Task`/`Node`/`TaskStatus` are covered by `test_domain_model.py`. Delete.
- `tests/unit/test_db.py`: tests deleted `DB` facade with a mocked pg8000;
  `PostgresTaskRepository`/`PostgresNodeRepository`/`PostgresUnitOfWork` behavior
  is covered by `test_persistence_adapter.py` (integration) and existing unit
  tests. Delete.

### D6: Spec deltas
- `db-wrapper`: **delete** the spec directory from `openspec/specs/`. Its entire
  subject (`DB`, `TaskModel`, `NodeModel`) is gone.
- `package-facades`: remove the `yascheduler.db — legacy, scheduled for deletion`
  line from the facade list.
- `test-db-integration`: replace `yascheduler.db.DB`/`yascheduler.db.TaskStatus`
  references with `PostgresUnitOfWork` + repos + `domain.TaskStatus`; keep the
  black-box "no patching of internal collaborators" discipline; drop the
  `isinstance(result["status"], yascheduler.db.TaskStatus)` scenario (replaced by
  `domain.TaskStatus`).
- `dependency-injection`: reword the "does NOT import `DB` from `yascheduler.db`"
  requirement to a forward guard — "the composition root SHALL NOT introduce a
  DB-facade class; persistence is accessed only via `PostgresUnitOfWork` and
  repository ports".
- `testing-unit`: remove three requirements ("Legacy DB models",
  "DB facade with mocked connection", "FakeDB test double"); in "Shared test
  fixtures" drop the `make_task`/`make_node` clause (module deleted).
- `e2e-testing`: generalize "Poll `db.get_task(task_id)`" to "poll task status
  via the UoW-backed fixture" (behavior unchanged).

### D7: Knowledge graph & docs
- `docs/knowledge-graph.xml`: remove the `<M-DB>` element (L39-62); remove
  `<CrossLink from="M-DB" to="M-PERSISTENCE-POSTGRES" ...>` (L926); update
  `<DF-PERSISTENCE>` (L901) to `M-PERSISTENCE-POSTGRES -> M-PERSISTENCE` (drop the
  `M-DB ->` hop); audit all `<depends>` for `M-DB` and remove — confirmed site:
  `M-CLI-COMMANDS` (L118) lists `M-DB` in its `<depends>`; verify no others
  (`M-CLIENT` L67 is already clean).
- `docs/ARCHITECTURE.md`: remove/revise the `db.py` references (L85, 119, 173,
  261, 462, 536, 556, 574).

## Risks / Trade-offs

- [Loss of facade-level integration coverage] `test_db_integration.py` is
  rewritten to UoW+repos; some assertions weaken (e.g. the JOIN scenario is now
  composed in-test rather than tested as a single facade call).
  → Mitigation: the in-test composition mirrors the facade's exact logic; the
  scenario still asserts real-Postgres JOIN behavior via `get_by_ips`.
- [`TRUNCATE` via raw connection] The new `pg_conn` fixture holds a separate
  connection from the UoW; pg8000 autocommit semantics must allow `TRUNCATE`
  outside a transaction.
  → Mitigation: open `pg_conn` outside any `BEGIN` (pg8000 native defaults to
  autocommit per statement); `TRUNCATE ... CASCADE` is run directly. Verified
  that the old `db.run("TRUNCATE ...")` worked the same way.
- [e2e `MessageBus` no-op] `PostgresUnitOfWork.commit()` dispatches events via
  `bus.dispatch`. A bare `MessageBus()` swallows events (no handlers).
  → Mitigation: e2e/integration tests assert DB state, not event dispatch; the
  existing `test_uow_integration` already uses a bare `MessageBus()`.
- [Spec `db-wrapper` deletion] Removing a spec directory is a structural
  change; `openspec validate --all --json` must still pass.
  → Mitigation: validate after the delta; the spec has no dependents (no other
  spec `depends` on `db-wrapper`).
- [Re-introduction of a `yascheduler.db` import] New code could re-add an
  import of the deleted module.
  → Mitigation: none bespoke needed. Once `yascheduler/db.py` is deleted, any
  `import yascheduler.db` is a broken import caught by ruff, zuban, mypy, and
  import-linter; the existing CI lint workflow already fails on such errors.

## Migration Plan

This is a single-PR internal change; no runtime migration, no DB schema change.
Order (each step gated by tests/static checks):
1. Add layered fixtures to integration + e2e conftests; migrate
   `test_persistence_adapter.py` to `pg_conn`/`pg_executor`.
2. Rewrite `test_db_integration.py` and `test_full_cycle.py` to UoW + repos.
3. Delete the 5 dead/legacy test modules + `yascheduler/db.py`.
4. Apply spec deltas (delete `db-wrapper`; edit the other 5 specs).
5. Update `knowledge-graph.xml` + `ARCHITECTURE.md`.
6. Run `uv run pytest -m unit`, `-m integration`, `-m e2e`; `openspec validate
   --all --json`; `python3 scripts/grace_check.py`.

Rollback: revert the PR; `yascheduler/db.py` and deleted tests return. No data
or runtime migration to undo.