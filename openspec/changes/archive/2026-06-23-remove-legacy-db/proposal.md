## Why

`yascheduler/db.py` is a legacy facade (`DB`, `TaskModel`, `NodeModel`,
`TaskStatus`) that now only mirrors the canonical domain model
(`yascheduler.domain.model`) and delegates to
`PostgresTaskRepository`/`PostgresNodeRepository`. Production code has already
been fully migrated away (0 importers in `yascheduler/`), and the file carries
a `# FIXME: remove this module` marker. Its only remaining consumers are test
files; keeping it blocks spec cleanup, leaves a duplicate `TaskStatus` enum,
and obscures the real persistence contract (`PostgresUnitOfWork` + repos).

## What Changes

- **BREAKING (internal)**: Delete `yascheduler/db.py` and its public symbols
  (`DB`, `TaskModel`, `NodeModel`, `TaskStatus`). No production code imports
  them; the public CLI/client/INI/DB-schema surfaces are unaffected.
- **Delete dead/legacy test modules** that exist only to test the facade:
  - `tests/fixtures/models.py` (`make_task`/`make_node` — zero importers),
  - `tests/fixtures/fake_db.py` (`FakeDB` — only used by `test_fake_db.py`),
  - `tests/unit/test_fake_db.py`,
  - `tests/unit/test_models.py` (legacy `TaskModel`/`NodeModel`; domain
    equivalents covered by `test_domain_model.py`),
  - `tests/unit/test_db.py` (DB facade with mocked pg8000; repository behavior
    covered by `test_persistence_adapter.py`).
- **Migrate the 5 test files that still rely on the `DB` connection helper**:
  - `tests/integration/conftest.py`, `tests/integration/test_db_integration.py`,
    `tests/integration/test_persistence_adapter.py`,
    `tests/e2e/conftest.py`, `tests/e2e/test_full_cycle.py`.
  - Replace the `db` fixture (`DB.create` + `db.run("TRUNCATE ...")`) with a
    `PostgresUnitOfWork`-based fixture (for test logic) plus a raw pg8000
    connection helper (for `TRUNCATE` teardown). Re-express `db.add_task` /
    `db.get_task` / `db.set_task_running` / `db.set_task_done` / etc. as
    `async with uow_factory() as uow:` repo calls; re-source `TaskStatus`
    from `yascheduler.domain`.
  - `PostgresUnitOfWork.__init__` requires a `bus: MessageBus`; the conftest
    constructs a bare `MessageBus()` (no handlers, no-op dispatch).
  - Note: not all DB methods map mechanically to repo calls. `test_persistence_adapter.py`
    builds repos directly via `PostgresTaskRepository(db.conn, db.executor)`, so
    the new fixture must also expose a raw `(connection, executor)` pair. And
    `db.add_node(ip_addr=..., port=...)` becomes
    `uow.nodes.add(Node(ip=..., port=...))` (domain entity, renamed args).
- **Retire the `db-wrapper` spec** (its sole subject, the `DB` class, is gone).
- **Update OpenSpec specs** that reference `yascheduler.db`:
  `package-facades`, `test-db-integration`, `dependency-injection`,
  `testing-unit`, `e2e-testing`.
- **Update `docs/knowledge-graph.xml`**: remove `<M-DB>`, its `CrossLink`, the
  `M-DB` hop in `<DF-PERSISTENCE>`, and any `M-DB` in `<depends>`.
- **Update `docs/ARCHITECTURE.md`**: remove the `db.py` references.

## Capabilities

### New Capabilities
<!-- None — this is a pure removal/migration. -->
_(none)_

### Modified Capabilities
- `db-wrapper`: **removed entirely** — the `DB` class, `TaskModel`,
  `NodeModel`, and all associated requirements/scenarios are deleted; this spec
  is dropped from `openspec/specs/`.
- `package-facades`: drop the `yascheduler.db` "legacy, scheduled for deletion"
  carve-out; the package facade list no longer mentions it.
- `test-db-integration`: re-require integration tests to use
  `PostgresUnitOfWork` + repositories and `domain.TaskStatus` instead of
  `yascheduler.db.DB` / `yascheduler.db.TaskStatus`; keep the non-patching
  black-box discipline.
- `dependency-injection`: replace the "does NOT import `DB` from
  `yascheduler.db`" requirement with a forward-looking guard forbidding
  re-introduction of a DB facade in the composition root.
- `testing-unit`: remove the three legacy-only requirements ("Legacy DB models
  (TaskModel, NodeModel, TaskStatus)", "DB facade with mocked connection",
  "FakeDB test double"); update "Shared test fixtures" to drop
  `make_task`/`make_node` (module deleted).
- `e2e-testing`: generalize the "Poll `db.get_task(task_id)`" step to poll task
  status via the new UoW-backed fixture (the `db.get_task` method no longer
  exists); behavior (poll until `DONE`) is unchanged.

## Impact

- **Code**: `yascheduler/db.py` removed (~540 LOC); 5 test files migrated,
  5 test modules/files deleted. No production module changes (already clean).
  The deleted module's absence is enforced by existing tooling (ruff/zuban/
  import-linter fail on any `import yascheduler.db` since the target no longer
  exists), so no bespoke grep guard is needed.
- **Public API / compatibility**: no change to CLI, `class Yascheduler`, INI
  format, DB schema, or AiiDA entrypoint. The removed symbols were never part
  of the documented public client surface (production importers = 0).
- **Dependencies**: none added or removed.
- **Tests**: net reduction (5 deletions, 5 migrations); unit suite loses legacy
  model/facade tests but domain + persistence-adapter coverage is retained.
- **Docs/graph**: `ARCHITECTURE.md` and `knowledge-graph.xml` updated; GRACE-lite
  `M-DB` retired.
- **Follow-ups (out of scope)**: extracting shared domain-shaped fakes
  (`FakeTaskRepository`/`FakeNodeRepository`/`FakeUnitOfWork`) from the two
  inline copies in `test_query_tasks.py` / `test_client_query.py` is a separate
  refactor.
