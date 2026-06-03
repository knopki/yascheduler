## 1. Migration Files

- [ ] 1.1 Create `adapters/persistence/sql/migrations/` directory
- [ ] 1.2 Create `001_add_username_port.sql` with current ALTER TABLE statements from db.migrate()
- [ ] 1.3 Add GRACE-lite MODULE_CONTRACT comment to migrations directory README or __init__.py

## 2. Migration Runner

- [ ] 2.1 Create `adapters/persistence/migrations.py` (or add to `__init__.py`)
- [ ] 2.2 Implement `run_migrations(conn: Connection) -> None` async function
- [ ] 2.3 Implement `_ensure_tracking_table(conn)` — CREATE TABLE IF NOT EXISTS
- [ ] 2.4 Implement `_get_applied_version(conn) -> int` — SELECT MAX(version)
- [ ] 2.5 Implement `_list_migration_files() -> list[tuple[int, str, str]]` — scan directory, sort
- [ ] 2.6 Implement per-migration execution: read file, execute SQL, INSERT tracking row
- [ ] 2.7 Wrap each migration in a transaction

## 3. DB Integration

- [ ] 3.1 Replace `db.migrate()` body with call to `run_migrations(self.conn)`
- [ ] 3.2 Preserve `migrate()` method signature and async behavior
- [ ] 3.3 Remove hardcoded ALTER TABLE from db.py

## 4. Tests

- [ ] 4.1 Write unit test: `run_migrations` creates tracking table on first call
- [ ] 4.2 Write unit test: already-applied migrations are skipped
- [ ] 4.3 Write unit test: new migration file is applied when version > applied
- [ ] 4.4 Write integration test: full migration against testcontainers PostgreSQL
- [ ] 4.5 Write integration test: idempotency — double-run produces no errors
- [ ] 4.6 Write unit test: `db.migrate()` delegates to runner

## 5. Verification

- [ ] 5.1 Run `grace_check.py` — new files pass
- [ ] 5.2 Run `openspec validate --all --json`
- [ ] 5.3 Run `uv run pytest -k "migration"` — tests pass
- [ ] 5.4 Run `uv run ruff check` — no lint errors
- [ ] 5.5 Run full existing test suite — no regressions
