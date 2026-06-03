## MODIFIED Requirements

### Requirement: PostgreSQL testcontainer fixture

The project SHALL provide a session-scoped pytest fixture that starts a PostgreSQL
container via testcontainers, applies the schema using `apply_schema()` from
`adapters/persistence/postgres_schema.py`, and yields a live `DB` instance.

#### Scenario: Fixture provides working DB
- **WHEN** an integration test uses the `db` fixture
- **THEN** a `DB` instance is available with schema applied via `apply_schema()` and `db.get_all_nodes()` returns an empty list
