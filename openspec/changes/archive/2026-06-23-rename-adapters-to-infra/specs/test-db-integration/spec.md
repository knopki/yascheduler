## MODIFIED Requirements

### Requirement: PostgreSQL testcontainer fixture
The project SHALL provide a session-scoped pytest fixture that starts a
PostgreSQL container via testcontainers and applies the schema using
`apply_schema()` from `infra/persistence/postgres_schema.py` once per
session. The project SHALL provide function-scoped fixtures that yield the
persistence primitives tests need: a raw `pg8000.native.Connection`
(`pg_conn`), a single-worker `ThreadPoolExecutor` (`pg_executor`), and a
`uow_factory` callable returning a `PostgresUnitOfWork` constructed with
`_db_config` and a bare `MessageBus()`. Tests SHALL NOT receive a `DB`
instance (the class is removed).

#### Scenario: Fixture provides working persistence primitives
- **WHEN** an integration test uses the `uow_factory` fixture inside `async with uow_factory() as uow:`
- **THEN** a `PostgresUnitOfWork` is available with schema applied via `apply_schema()` and `await uow.nodes.list_all()` returns an empty list
