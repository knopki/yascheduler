## 1. Implementation

- [ ] 1.1 Create `adapters/persistence/pool.py` with `PgPool` class
- [ ] 1.2 Implement `__init__` — create N connections, populate asyncio.Queue
- [ ] 1.3 Implement `acquire()` and `release()` async methods
- [ ] 1.4 Add `db_pool_size` to `ConfigLocal` (default 1)
- [ ] 1.5 Update `PostgresUnitOfWork` to acquire/release from pool
- [ ] 1.6 Update `di.make_daemon()` and `make_cli_deps()` to create pool
- [ ] 1.7 Add GRACE-lite markup

## 2. Tests

- [ ] 2.1 Unit test: acquire/release cycle returns same connection
- [ ] 2.2 Unit test: pool exhaustion blocks until release
- [ ] 2.3 Unit test: size=1 works identically to old ThreadPoolExecutor
- [ ] 2.4 Integration test: two concurrent UoW instances with pool_size=2

## 3. Verification

- [ ] 3.1 Run `openspec validate --all --json`
- [ ] 3.2 Run full test suite — no regressions
