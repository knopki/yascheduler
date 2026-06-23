## MODIFIED Requirements

### Requirement: Persistence adapter with mocked pg8000

Tests SHALL verify `PostgresTaskRepository`, `PostgresNodeRepository`, and
`PostgresUnitOfWork` from `yascheduler.infra.persistence` using mocked
pg8000 connections:
- `load_query` reads file on first call, returns cache on subsequent calls
- UoW: enter creates repos, commit calls `conn.run("COMMIT")`, exception
  triggers rollback, normal exit closes connection, commit after exit raises
  `UnitOfWorkNotInitializedError`
- Task repo: `get`, `insert` (returns generated ID), `save` (upsert),
  `list_by_status`, `list_by_jobs`, `count_by_status`, `update_status`
- Node repo: `get`, `list_enabled` (filters invalid IPs), `list_disabled`,
  `add`, `enable`, `disable`, `remove`, `get_by_ips`

#### Scenario: PostgresUnitOfWork commit calls COMMIT
- **WHEN** `uow.commit()` is called with a mocked connection
- **THEN** `conn.run("COMMIT")` is executed

#### Scenario: PostgresUnitOfWork commit after exit raises UnitOfWorkNotInitializedError
- **WHEN** `uow.commit()` is called after the `async with` block has exited
- **THEN** `UnitOfWorkNotInitializedError` is raised and `isinstance(exc, RuntimeError)` is `True`
