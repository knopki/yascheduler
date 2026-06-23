# explore-brief: remove-legacy-db

## Goal
Delete `yascheduler/db.py` (legacy `DB`/`TaskModel`/`NodeModel`/`TaskStatus`
facade). The file is already marked `# FIXME: remove this module` and has
**zero production importers**; all remaining consumers are under `tests/`.

## Current state (verified by grep)
- Production (`yascheduler/`): **0** imports of `yascheduler.db` (migrated in
  prior changes: `client-query-uow`, `cloud-provisioner-pure`,
  `usecase-uow-migration`).
- `tests/` importers of `yascheduler.db`: 10 files.

## Consumer classification → action

| File | Imports | Real consumers? | Action |
|------|---------|-----------------|--------|
| `tests/fixtures/models.py` | `NodeModel,TaskModel,TaskStatus` | **none** (grep `from tests.fixtures.models import` = 0) | **delete** (dead) |
| `tests/fixtures/fake_db.py` | `NodeModel,TaskModel,TaskStatus` | only `test_fake_db.py` | **delete** |
| `tests/unit/test_fake_db.py` | `NodeModel,TaskStatus` + `FakeDB` | tests only `FakeDB` | **delete** |
| `tests/unit/test_models.py` | `NodeModel,TaskModel,TaskStatus` | tests legacy models only | **delete** (domain `Task`/`Node`/`TaskStatus` already covered by `test_domain_model.py`) |
| `tests/unit/test_db.py` | `DB,NodeModel,TaskModel,TaskStatus` | tests deleted `DB` facade w/ mocked pg8000 | **delete** (repos covered by `test_persistence_adapter.py`) |
| `tests/integration/conftest.py` | `DB` | `db` fixture via `DB.create` + `run("TRUNCATE")` | **migrate** fixture |
| `tests/integration/test_db_integration.py` | `DB,TaskStatus` | uses `db` fixture | **migrate** |
| `tests/integration/test_persistence_adapter.py` | `DB` | uses `db` fixture | **migrate** |
| `tests/e2e/conftest.py` | `DB` | `db` fixture via `DB.create` + `run("TRUNCATE")` | **migrate** fixture |
| `tests/e2e/test_full_cycle.py` | `DB,TaskStatus` | uses `db` fixture | **migrate** |

## Rejected alternatives
1. **Keep `db.py` as a thin re-export shim** (`TaskStatus = domain.TaskStatus`).
   Rejected: still imports the module, defeats deletion; specs/knowledge-graph
   stay ambiguous. No external API consumer needs it (production already gone).
2. **Migrate `FakeDB` → domain-shaped `FakeTaskRepository`+`FakeNodeRepository`+`FakeUnitOfWork` shared fixtures.** Rejected for *this* change: `FakeDB` has no
   real consumer (only its own test). Domain-shaped fakes already exist inline
   in `test_query_tasks.py`/`test_client_query.py`. Extracting shared domain
   fakes is a separate refactor; here we just delete dead legacy doubles.
3. **Rewrite integration/e2e tests around raw repos.** Kept as the chosen path
   but scoped: introduce a minimal `uow_factory` (+ raw connection for
   TRUNCATE) in conftest; rewrite the few DB-method calls in the 3 consumer
   tests to `async with uow_factory() as uow:`.

## Chosen approach (the migration contract)
**Integration/e2e `db` fixture replacement.** Replace `DB.create`-based
fixture with:
- A session/function-scoped raw `pg8000.Connection`-based helper OR
  `PostgresUnitOfWork` factory for test assertions.
- `TRUNCATE` teardown: via a raw connection helper (UoW has no `run`).

Concretely, conftest provides:
- `uow_factory` (callable → `PostgresUnitOfWork`) for test logic
  (`uow.tasks.insert/get/save`, `uow.nodes.add/...`, `uow.commit()`).
- A raw connection fixture (or reuse `_db_config` + a `pg8000.native.Connection`)
  for `TRUNCATE ... CASCADE` teardown.

**Cross-module data flows (after change):**
- Unit tests → `yascheduler.domain.model` (`Task`, `Node`, `TaskStatus`).
- Integration tests → `PostgresUnitOfWork` + `PostgresTaskRepository` /
  `PostgresNodeRepository` (adapters.persistence.postgres).
- E2E tests → same UoW + repos; `TRUNCATE` via raw connection.

## OpenSpec spec deltas required
- `db-wrapper` — **obsolete**: remove the spec entirely (its whole purpose is
  the deleted `DB` class).
- `package-facades` — drop the `yascheduler.db` "legacy, scheduled for
  deletion" line.
- `test-db-integration` — replace `yascheduler.db.DB`/`yascheduler.db.TaskStatus`
  references with UoW / `domain.TaskStatus`.
- `dependency-injection` — the "does NOT import `DB` from `yascheduler.db`"
  requirement becomes vacuous → reword to forbid re-introduction of a DB
  facade (or drop the scenario).
- `testing-unit` — remove 3 requirements: "Legacy DB models",
  "DB facade with mocked connection", "FakeDB test double"; update
  "Shared test fixtures" to drop `make_task`/`make_node` (deleted).

## Knowledge graph & docs
- `docs/knowledge-graph.xml`: remove `<M-DB>` block (L39-62); remove
  `<CrossLink from="M-DB" ...>` (L926); update
  `<DF-PERSISTENCE>` (L901) to drop `M-DB`; drop `M-DB` from any
  `<depends>` (e.g. M-CLIENT L67 already clean — verify all).
- `docs/ARCHITECTURE.md`: remove/revise db.py references (L85, 119, 173, 261,
  462, 536, 556, 574).

## Open questions
1. **TRUNCATE teardown mechanism** — add a tiny `tests/integration|e2e/db.py`
   helper exposing `truncate(conn)`, or inline raw `Connection` in conftest?
   Lean: inline in conftest (smallest footprint, no new module).
2. **`MessageBus` construction for `PostgresUnitOfWork`** in tests — UoW ctor
   requires `bus: MessageBus`. Need a no-op/null bus in conftest fixture.
3. Confirm `test_db_integration.py`/`test_full_cycle.py` assertions still hold
   when re-expressed via UoW repos (some DB methods like
   `get_tasks_with_cloud_by_id_status` join nodes — may need repo composition).
