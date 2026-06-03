## 1. Schema Applier Module

- [x] 1.1 Create `yascheduler/adapters/persistence/postgres_schema.py` with GRACE-lite MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY
- [x] 1.2 Implement `apply_schema(config: ConfigDb) -> None` — sync function, pg8000 native connection, BEGIN/COMMIT/ROLLACK, uses `load_query("schema")`
- [x] 1.3 Add DatabaseError handling — print "Database already initialized!" on "already exists" then re-raise
- [x] 1.4 Ensure connection is closed in `finally` block on both success and failure paths

## 2. CLI Init Refactor

- [x] 2.1 Rewrite `_init_db()` in `yascheduler/adapters/cli/init.py` to call `apply_schema(config.db)` — synchronous, no DB import
- [x] 2.2 Remove `@to_sync` decorator and `async` from `init()` — make it a plain sync function
- [x] 2.3 Remove unused imports (`to_sync`, `DB`, `pg8000.ProgrammingError`, `Path` for schema) from init.py
- [x] 2.4 Update MODULE_CONTRACT and MODULE_MAP in init.py to reflect sync nature and new dependency

## 3. Test Fixture Unification

- [x] 3.1 Rewrite `_init_schema` in `tests/integration/conftest.py` — plain sync fixture calling `apply_schema(_db_config)`, remove Path/DB.run/migrate
- [x] 3.2 Rewrite `_init_schema` in `tests/e2e/conftest.py` — plain sync fixture calling `apply_schema(_db_config)`, remove Path/DB.run/migrate

## 4. Integration Test

- [x] 4.1 Create `tests/integration/test_postgres_schema.py` with GRACE-lite markup
- [x] 4.2 Test: `apply_schema()` succeeds against empty testcontainers PostgreSQL — tables exist afterward
- [x] 4.3 Test: `apply_schema()` raises `DatabaseError` when tables already exist and prints "Database already initialized!"

## 5. Verification

- [x] 5.1 Run `python3 scripts/grace_check.py` — new files pass
- [x] 5.2 Run `openspec validate --all --json` — all specs valid
- [x] 5.3 Run `uv run -m unit` — unit tests pass
- [x] 5.4 Run `uv run -m integration` — integration tests pass (requires Docker)
- [x] 5.5 Run `uv run ruff check .` and `uv run ruff format --check .` — no lint errors