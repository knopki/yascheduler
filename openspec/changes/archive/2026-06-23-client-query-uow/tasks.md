## 1. New `query_tasks` use case

- [x] 1.1 Create `yascheduler/application/query_tasks.py` with the `query_tasks(jobs, statuses, uow_factory)` async function per `use-cases` spec: opens one UoW, dispatches `list_by_status(set(statuses))` for non-empty statuses or `list_by_jobs(list(jobs))` for non-empty jobs, raises `ValueError` if both supplied, returns `[]` if neither, never calls `uow.commit`. Imports only from `yascheduler.domain` and `yascheduler.application.uow` (no `yascheduler.adapters` at runtime). Include the GRACE-lite `MODULE_CONTRACT`, `MODULE_MAP`, and `CHANGE_SUMMARY` headers on the new file (otherwise `grace_check.py` in 7.2 will fail).
- [x] 1.2 Re-export `query_tasks` from `yascheduler/application/__init__.py` (matches the lazy-facade publication pattern used for `submit_task`).
- [x] 1.3 Verify with a focused unit test (`tests/unit/test_query_tasks.py` or extend an existing application-layer test) that the 5 QueryTasks scenarios from the `use-cases` delta hold against a `FakeUnitOfWork` + `FakeTaskRepository`.

## 2. Constructor seam on `Yascheduler`

- [x] 2.1 Add the keyword-only `deps_factory: Optional[Callable[[Config], CLIDeps]] = None` parameter to `Yascheduler.__init__`. Store as `self._deps_factory = deps_factory or make_cli_deps`. Import `make_cli_deps` and `CLIDeps` from `.di` at module level (replacing the lazy local import inside `queue_submit_task_async` is NOT required — leave submit path untouched).
- [x] 2.2 Confirm `Yascheduler()` zero-arg, `Yascheduler(config_path)`, and `Yascheduler(config_path, logger)` callsites all still construct successfully; a positional third argument (e.g., `Yascheduler(config_path, logger, factory)`) raises `TypeError` because `deps_factory` is keyword-only.

## 3. Characterization baseline (γ) — write against current code, verify pass

- [x] 3.1 Create `tests/integration/test_client_query_integration.py`. Provide a testcontainers-Postgres fixture (or reuse the existing `db` fixture pattern from `tests/integration/conftest.py`) that yields a `Config` whose `.db` points at the live container. Submit a real task via `Yascheduler(config).queue_submit_task(...)`, then assert:
  - `Yascheduler(config).queue_get_tasks(jobs=[task_id])` returns a list containing one Mapping with exactly the six keys `{task_id, label, ip, status, metadata, cloud}`;
  - `Yascheduler(config).queue_get_tasks(status=[0])` returns a list containing that same task with the same six-key shape;
  - `Yascheduler(config).queue_get_task(task_id)` returns a single Mapping (not a list) with the six-key shape; `Yascheduler(config).queue_get_task(<unknown_id>)` returns `None`.
  Assert `status` via `int(result["status"])` / `==` / `.name` — NEVER `isinstance(..., yascheduler.db.TaskStatus)`. Do NOT patch `yascheduler.db.DB`, `yascheduler.di.make_cli_deps`, or any internal collaborator.
- [x] 3.2 Run `uv run pytest -m integration tests/integration/test_client_query_integration.py` and confirm it **passes against the current `DB`-backed path** (this is the characterization baseline — the test must be green BEFORE the swap). If it fails, fix the test (not the production code) until green.

## 4. Body swap + α unit tests

- [x] 4.1 Rewrite `Yascheduler.queue_get_tasks_async` body: call `deps = self._deps_factory(self.config)`, `tasks = await query_tasks(jobs, statuses, deps.uow_factory)`, and `return [_task_to_dict(t) for t in tasks]`. Add the private `_task_to_dict(t: Task) -> Mapping[str, Any]` helper returning `{task_id, label, ip=(allocated_ip or ""), status=t.status, metadata=t.context.to_metadata(), cloud=None}`.
- [x] 4.2 Drop `from .db import DB, TaskStatus` in `client.py`; import `TaskStatus` and `Task` from `yascheduler.domain` and `query_tasks` from `yascheduler.application`. Re-source the three class constants `STATUS_TO_DO / RUNNING / DONE` from `domain.TaskStatus` (values unchanged: 0/1/2).
- [x] 4.3 Create `tests/unit/test_client_query.py` constructing `Yascheduler(..., deps_factory=lambda cfg: FakeCLIDeps(...))` with `FakeUnitOfWork` + `FakeTaskRepository`. Cover the five `testing-unit` scenarios: status filter dispatches `list_by_status({domain.TaskStatus.TO_DO})`; jobs filter dispatches `list_by_jobs([7])`; both supplied raises `ValueError`; neither returns `[]`; returned dict has exactly six keys, `status` is `isinstance(domain.TaskStatus)`, `allocated_ip=None → ip==""`, `cloud is None`. Also cover the `dependency-injection` "Factory is invoked once per query call" scenario: configure `deps_factory` as a counting spy and assert two `queue_get_tasks_async` calls invoke the factory exactly twice (no caching). Fakes may live in `tests/unit/test_client_query.py` or `tests/fixtures/`.
- [x] 4.4 Re-run γ: `uv run pytest -m integration tests/integration/test_client_query_integration.py` — must pass **unchanged** against the swapped implementation (proof of behavior preservation). If it fails, the swap introduced a regression — fix before proceeding.
- [x] 4.5 Run the full unit + integration gates: `uv run pytest -m unit` and `uv run pytest -m integration`. All green.

## 5. FIXMEs

- [x] 5.1 Add a `# FIXME: vestigial — zero production callers (only tests/unit/test_di.py). Remove in a cleanup sweep.` comment above `CLIDeps.query` in `yascheduler/di.py`. No behavior change.
- [x] 5.2 Add a `# FIXME: no backoff.on_exception on InterfaceError — pre-existing cross-cutting gap with the retired DB.run retry behavior. Track in a follow-up proposal covering all UoW paths.` comment near the top of `PostgresUnitOfWork` (or its `__init__`) in `yascheduler/adapters/persistence/postgres_uow.py`. No behavior change.

## 6. Documentation

- [x] 6.1 Update `docs/ARCHITECTURE.md` §2.9: drop the stale claim that `db.py` is "Consumed by `client.py` and `CloudProvisionerImpl`"; state that `client.py` no longer constructs `DB` and `db.py` is test-only pending a separate removal proposal.
- [x] 6.2 Update `docs/ARCHITECTURE.md` §6.4: mark the `client.py` query-methods-via-use-case migration as **resolved** by this change (cross-reference `openspec/changes/client-query-uow/`).
- [x] 6.3 Update `docs/knowledge-graph.xml`: add a new `M-APPLICATION-QUERY-TASKS` module element (`TYPE="CORE_LOGIC"`, `STATUS="implemented"`, depends on `M-DOMAIN-PORTS, M-PERSISTENCE-UOW`, with `<fn-query_tasks PURPOSE="...">` annotation). Add two `CrossLink`s: `M-CLIENT → M-APPLICATION-QUERY-TASKS` (relation: "delegates task queries"); `M-APPLICATION-QUERY-TASKS → M-PERSISTENCE-UOW` (relation: "reads via UoW"). Update `M-CLIENT` annotations to add `fn-_task_to_dict` and `param-deps_factory`. Trim `M-DB` annotations by removing any that reference production callers (after 7.5 confirms zero remain, only test-consumer references are valid).

## 7. Final verification

- [x] 7.1 `openspec validate "client-query-uow" --json` — valid, 0 issues.
- [x] 7.2 `python3 scripts/grace_check.py` — exit 0 (XML + source checks pass after knowledge-graph and contract updates).
- [x] 7.3 Static checks: `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` — all clean.
- [x] 7.4 Full test gates: `uv run pytest -m unit`, `uv run pytest -m integration` — green. (`uv run pytest -m e2e` is optional unless CI requires it; the change is read-path-only on the facade and no SSH/cloud code is touched.)
- [x] 7.5 Confirm `grep -rn "from yascheduler.db import" yascheduler/` returns **zero** matches (production modules no longer import legacy `db`; tests still do, which is expected pending the follow-up test-fixture migration).
- [x] 7.6 Update this change's `review-log.md` with the implementation-time entries (any review rounds during apply); mark the change ready for `/opsx-verify`.
