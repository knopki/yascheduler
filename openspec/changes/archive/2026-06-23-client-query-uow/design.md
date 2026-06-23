## Context

`yascheduler/db.py` (~540 LOC) is a legacy attrs-based wrapper around `pg8000`
that the codebase has been progressively retiring in favor of the
Unit-of-Work pattern (`PostgresUnitOfWork` +
`PostgresTaskRepository` / `PostgresNodeRepository`). Every daemon and CLI
code path already routes through UoW; the sole remaining production caller of
`DB.create` is `Yascheduler.queue_get_tasks_async` at `client.py:149`. The
`Yascheduler` facade is the public Python/CLI client consumed by the AiiDA
plugin, the `examples/` scripts, and external downstream users (see
`openspec/specs/package-facades/spec.md`). Its public surface — constructor,
method signatures, and the return dict shape of the query methods — is a
frozen contract.

Two structural facts drive the design:

1. The query methods are read-only and return a *projection* (a flat dict),
   not a domain aggregate. The projection shape (`{task_id, label, ip,
   status, metadata, cloud}`, produced today by `attrs.asdict(TaskModel)`)
   is part of the public contract.
2. The query methods currently have **zero** test coverage. Any migration
   must therefore be preceded by characterization tests that pin current
   observable behavior, so the swap can be proven behavior-preserving.

Constraints inherited from the frozen `proposal.md`:
zero-arg `Yascheduler()` stays valid; query method signatures unchanged;
6-key dict shape preserved; `status` returns the enum member; `cloud` stays
`None`. Scope is `client.py` only; test-fixture migration and submit-path
seam conversion are explicitly out of scope.

## Goals / Non-Goals

**Goals:**
- Remove the last production caller of `yascheduler/db.py` by routing the
  facade's query methods through a UoW-backed use case.
- Preserve the public dict shape exactly (six keys, enum-preserve `status`,
  `cloud: None`).
- Introduce a stable test seam so characterization tests survive the
  implementation swap unchanged.
- Land characterization unit tests (via the seam) and a testcontainers
  integration test (implementation-agnostic golden master) for the query
  path.
- Document three behavior deltas honestly: automigrate removal,
  connection-leak fix, and the pre-existing cross-cutting backoff gap.

**Non-Goals:**
- Migrate test fixtures (`fake_db.py`, `models.py`) or the 10 test files
  still importing from `yascheduler.db`. Deferred to a follow-up proposal.
- Convert the submit path to the same `deps_factory` seam. The submit path
  stays on its existing module-patch test pattern; symmetry is desirable but
  out of scope here.
- Add `backoff` retry to `PostgresUnitOfWork` or the repositories. The
  absence is a pre-existing cross-cutting limitation tracked via a FIXME;
  a dedicated proposal should address it for all UoW paths together.
- Remove `yascheduler/db.py`. After this change it becomes test-only; full
  removal waits for the test-fixture migration.
- Remove the vestigial `CLIDeps.query` method. It gains a FIXME for a later
  cleanup sweep.

## Decisions

### D1. New `query_tasks` use case in `application/`, not a `CLIDeps` extension

**Choice.** Create `yascheduler/application/query_tasks.py` exposing
`async def query_tasks(jobs, statuses, uow_factory) -> list[Task]`. The
facade calls it via `deps.uow_factory`.

**Alternatives.**
- *Extend `CLIDeps` with a `query_many` method (no use case).* Rejected:
  asymmetric with `submit_task` / `allocate_task` / `deallocate_nodes`,
  which all live as module-level async functions in `application/`. Putting
  query logic only on `CLIDeps` would split the use-case catalog.
- *Reuse the existing `CLIDeps.query`.* Rejected: it returns a single `Task`
  by id, typed loosely as `object | None`. It does not handle status
  filters, and has zero production callers. Touching it would conflate
  cleanup with the migration.

**Why a use case.** The use case owns one coherent responsibility —
"translate a (jobs XOR statuses) read request into a list of `Task`
aggregates within a single UoW." That is exactly the granularity of the
sibling use cases. The facade stays thin: construct deps, call use case,
project to dict.

**Signature (locked at proposal level, repeated here for design clarity):**
```
query_tasks(
    jobs: Sequence[int] | None,
    statuses: Sequence[TaskStatus] | None,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> list[Task]
```
Control flow:
1. If both `jobs` and `statuses` are provided → raise `ValueError` (mirrors
   the facade's existing mutual-exclusivity check, today at
   `client.py:143-144`).
2. Open a single UoW via `uow_factory()`.
3. If `statuses` is set → `await uow.tasks.list_by_status(set(statuses))`.
4. elif `jobs` is set → `await uow.tasks.list_by_jobs(list(jobs))`.
5. else → `[]` (no error; preserves today's `client.py:154-155` "empty in,
   empty out").
6. Exit `async with`; the UoW closes the connection via `__aexit__`. The use
   case issues no `commit()` (read-only).

The use case imports only from `yascheduler.domain` and
`yascheduler.application.uow` — no adapter imports — matching the
discipline already enforced for `allocate_task` (see
`openspec/specs/use-cases/spec.md` AllocateTask requirement).

### D2. Constructor seam `deps_factory` on `Yascheduler.__init__`

**Choice.** Add a keyword-only optional
`deps_factory: Optional[Callable[[Config], CLIDeps]] = None` to
`Yascheduler.__init__`. Store as `self._deps_factory`; if `None`, fall back
to `make_cli_deps` lazily at call time. The query method calls
`self._deps_factory(self.config)` to obtain a fresh `CLIDeps` per invocation,
mirroring how `queue_submit_task_async` today does
`deps = make_cli_deps(self.config)` on each call.

**Alternatives.**
- *Module-level patch of `make_cli_deps` (matches the submit path's existing
  test style).* Rejected for the query path specifically: the swap deletes
  the `DB` symbol from `client.py`, so any characterization test that
  patches `yascheduler.client.DB` cannot survive the refactor. Patching
  `make_cli_deps` only works *after* the migration; characterization-first
  requires a seam that exists *before* and survives *through* the swap.
  Constructor injection is that seam.
- *Cache a single `CLIDeps` instance on the facade.* Rejected: each
  `make_cli_deps` call constructs a fresh `MessageBus` captured by the
  `_uow_factory` closure (`di.py:230-233`); caching the `CLIDeps` would
  freeze that bus for the facade's lifetime. Per-call construction matches
  the submit path and avoids hidden state.

**Why kw-only.** Keyword-only with a default keeps `Yascheduler()` and
`Yascheduler(config_path)` positional callsites 100% backward-compatible
(this is the `package-facades` capability's stability guarantee). The seam
is invisible to non-test callers.

**Why not also route submit through it now.** Scope discipline. The submit
path's characterization test (`tests/unit/test_characterization.py`) patches
`yascheduler.di.make_cli_deps`; converting it to the seam is a separate
refactor that would touch `test_characterization.py` and is not required for
the query migration. Noted as follow-up.

### D3. Inline `_task_to_dict` mapping in `client.py`

**Choice.** Add a private module-level helper
`_task_to_dict(t: Task) -> Mapping[str, Any]` in `client.py`. The facade
maps `list[Task] → list[dict]` via `[_task_to_dict(t) for t in tasks]`.

**Mapping (frozen at proposal level):**
```
{
    "task_id":  t.task_id,
    "label":    t.label,
    "ip":       t.allocated_ip or "",
    "status":   t.status,                  # enum member, NOT .value
    "metadata": t.context.to_metadata(),
    "cloud":    None,
}
```

**Alternatives.**
- *Introduce a `TaskView` DTO with `to_dict()`.* Rejected: one more type to
  retire when external callers modernize. The dict shape is itself the
  contract; a DTO adds nothing while alive and is debt when dead.
- *Push the mapping into the use case.* Rejected: the use case returns
  domain `Task`. Mixing projection into the use case would couple it to the
  facade's serialization format and break symmetry with `submit_task`
  (which also returns primitives, not projections).
- *Return `t.status.value` (plain int).* Rejected — see D4.

**Why `"cloud": None` and not omit.** Today `asdict(TaskModel)` yields
exactly six keys because `TaskModel.cloud` defaults to `None`. Omitting the
key would shrink the shape to five and break any consumer doing
`result["cloud"]` or `set(result.keys())`. Verified: the only code path
that ever sets `cloud` is `DB.get_tasks_with_cloud_by_id_status`, which has
zero production callers; the facade only calls `get_tasks_by_status` and
`get_tasks_by_jobs`, both of which route through `_task_to_model` without
passing `cloud`.

### D4. Status field returns the enum member, not `.value`

**Choice.** `_task_to_dict` returns `t.status` (a `domain.TaskStatus`
member), not `t.status.value`.

**Rationale.** Today `asdict(TaskModel)` returns a `db.TaskStatus` member
(`IntEnum`). Returning `domain.TaskStatus.X.value` (a plain `int`) would
change observable type for any consumer that:
- accesses `.name` (`"RUNNING"`) — would raise `AttributeError` on `int`;
- checks identity rather than equality;
- JSON-serializes — both serialize to the int value via `json.dumps`, so
  this path is unaffected.

`domain.TaskStatus` and `db.TaskStatus` are separate classes with identical
values (`TO_DO=0, RUNNING=1, DONE=2`). Cross-class `IntEnum.__eq__` compares
via the underlying `int`, so
`domain.TaskStatus.RUNNING == db.TaskStatus.RUNNING == 1` holds. Returning
the `domain.TaskStatus` member preserves `.name` access and matches the
legacy "asdict-returns-enum" behavior with the only difference being the
enum's *class* — which is observationally inert for the comparisons and
serializations the contract relies on.

**Alternative.** *Return `.value` for cleanliness.* Rejected: stricter than
the existing contract and risks the `.name` regression above. Conservative
migration preserves type, not just value.

### D5. Test methodology: γ golden master + α unit verification

**Choice.** Two test files with distinct, complementary roles.

- **γ — Integration golden master**
  (`tests/integration/test_client_query_integration.py`): the strict
  *characterization-first* test. Written and verified against the current
  `DB`-backed path first, it submits a real task via
  `Yascheduler().queue_submit_task(...)` and queries it back via
  `queue_get_tasks(jobs=[id])` and `queue_get_tasks(status=[0])`, asserting
  the six-key dict shape and values against testcontainers Postgres. Zero
  patches. After the swap, the same test is re-run unchanged and must still
  pass — both the legacy `DB` path and the new UoW path hit the same
  Postgres, so the test is implementation-agnostic by construction. This is
  the artifact that proves behavior preservation across the swap.
  **γ's `status` assertion strategy**: assert by `int(value)`,
  `result["status"] == 1`, or `result["status"].name == "RUNNING"` — never
  `isinstance(result["status"], db.TaskStatus)`, which would falsely fail
  post-swap when the class becomes `domain.TaskStatus`.
- **α — Unit verification** (`tests/unit/test_client_query.py`): lands with
  the swap and exercises the post-swap implementation via the `deps_factory`
  seam. Constructs `Yascheduler(..., deps_factory=lambda cfg: fake_deps)`
  with a `FakeCLIDeps` whose `uow_factory()` returns a `FakeUnitOfWork`
  carrying a `FakeTaskRepository`. The seam's role here is *forward-looking
  stability*: future refactors of the query body keep the seam, so these
  unit tests survive them without edit. α cannot characterize pre-swap
  behavior because the dispatch logic only exists after the swap; that role
  belongs to γ.

  α asserts *observable behavior only*:
  - status filter dispatches `list_by_status({statuses})`;
  - jobs filter dispatches `list_by_jobs(list(jobs))`;
  - both supplied raises `ValueError`;
  - neither supplied returns `[]`;
  - returned dicts have exactly the six keys
    `{task_id, label, ip, status, metadata, cloud}`;
  - `status` value equals the `domain.TaskStatus` member (identity, not just
    int equality);
  - `allocated_ip is None` → `ip == ""`;
  - `cloud` is `None`.

**Alternatives.**
- *β — Patch `yascheduler.client.DB` with a `FakeDB`, accept one fixture
  edit at swap time.* Rejected: the edit (changing the patch target from
  `DB` to `make_cli_deps`) is exactly the kind of test-side churn
  characterization tests exist to eliminate, and it makes the "tests prove
  behavior preservation" claim weaker.
- *γ alone.* Kept, but insufficient on its own — unit-level dispatch and
  shape assertions belong next to the code, and integration tests are too
  slow for the unit-test gate.

### D6. Three behavior deltas, framed as improvements

The swap changes three observable side effects of `queue_get_tasks_async`.
All three are welcome; all three are documented in `proposal.md` and here.

1. **No schema migration on query.** Today `DB.create(automigrate=True)`
   runs `ALTER TABLE yascheduler_nodes ADD COLUMN IF NOT EXISTS username
   ...; ADD COLUMN IF NOT EXISTS port ...;` on every query call (a
   surprising and heavy side effect for a read). The UoW path runs no DDL.
   Schema migrations are owned by the daemon start and the dedicated `yainit`
   tooling.
2. **No connection/executor leak.** Today `db = await DB.create(self.config.db)` is
   never followed by `await db.close()` in the query path — every call
   leaks a pg8000 connection *and* the `ThreadPoolExecutor(max_workers=1)`
   that `DB.create` constructs (`db.py:209`). The UoW
   `async with uow_factory() as uow:` closes both the connection
   (`postgres_uow.py:139`) and the executor (`:142`) in `__aexit__`.
3. **No `backoff` on `InterfaceError`.** Today `DB.run` wraps queries in
   `@backoff.on_exception(backoff.fibo, InterfaceError, max_time=60)`
   (`db.py:219`). The UoW and repositories have *zero* backoff anywhere
   (`grep backoff yascheduler/adapters/persistence/` is empty). The swap
   homogenizes the query path with submit/allocate/deallocate, which also
   lack backoff. This is a pre-existing cross-cutting gap, not a regression
   introduced here. A FIXME lands on `postgres_uow.py` to make the gap
   discoverable; a follow-up proposal should add retry to the UoW/repo
   layer for *all* paths rather than re-introducing it for query only.

### D7. Two FIXMEs

- `yascheduler/di.py` on `CLIDeps.query`: vestigial — zero production
  callers (only `tests/unit/test_di.py:139`). Marked for a cleanup sweep;
  removing it is out of scope here (would touch `test_di.py`).
- `yascheduler/adapters/persistence/postgres_uow.py`: no
  `backoff.on_exception` on `InterfaceError`. See D6.3 above.

## Risks / Trade-offs

- **[Backoff gap surfaces for query callers]** → Mitigated by FIXME +
  follow-up proposal. If transient `InterfaceError`s become visible in
  production query traffic before the follow-up lands, operators can
  wrap the facade call in retry at the caller layer; the gap is no worse
  than for the existing submit/allocate/deallocate paths.
- **[External consumer relies on `cloud` being absent rather than None]**
  → Unlikely (the key is present today with value `None`); the design
  preserves presence, so this risk is null in practice. Flagged here for
  auditability.
- **[External consumer relies on `status` being a `db.TaskStatus` rather
  than `domain.TaskStatus` instance]** → Cross-class `IntEnum.__eq__` holds;
  `.name` and `.value` match; JSON serialization matches. Only an
  `isinstance(result["status"], db.TaskStatus)` check would break, which is
  undocumented and implausible. Acceptable.
- **[Test seam `deps_factory` becomes a public footgun]** → Mitigated by
  keyword-only placement, underscore-prefixed convention via
  `self._deps_factory`, and no appearance in non-test code paths.
- **[Asymmetry: submit path does not use the seam]** → Acknowledged in D2.
  Not a defect; incremental migration is preferable to a coupled mega-PR.

## Migration Plan

Single-PR change, ordered for strict characterization-first discipline: the
golden master (γ) must pass against the *current* `DB`-backed path before
the swap, then pass unchanged against the new UoW path after.

1. Add `application/query_tasks.py` use case + export in
   `application/__init__.py`. No callers yet.
2. Add `deps_factory` kw-only arg to `Yascheduler.__init__`. Default lazy
   `make_cli_deps`. Query method still uses `DB.create` — seam is inert.
3. Add `tests/integration/test_client_query_integration.py` (γ). Verify it
   **passes** against the current `DB`-backed path. This is the
   characterization baseline.
4. Swap `queue_get_tasks_async` body to use `self._deps_factory(self.config)`
   + `query_tasks` + `_task_to_dict`. Drop `from .db import DB, TaskStatus`;
   import `TaskStatus` from `yascheduler.domain`. Re-source class constants.
   Land `tests/unit/test_client_query.py` (α) in the same commit — the tests
   are written against the post-swap shape and verified here. Re-run γ; it
   must pass unchanged. (Alternative: land α tests earlier via a temporary
   `deps_factory`-routed path that still calls `DB.create` underneath;
   rejected as needless indirection.)
5. Add the two FIXMEs (`di.py`, `postgres_uow.py`).
6. Update `docs/ARCHITECTURE.md` §2.9 (drop stale
   "Consumed by CloudProvisionerImpl" claim) and §6.4 (mark resolved).
7. Update `docs/knowledge-graph.xml`: add `M-APPLICATION-QUERY-TASKS`, two
   CrossLinks, revised `M-CLIENT` annotations, trim `M-DB` annotations.

**Bisectability.** Each step is a valid intermediate state. Step 2 leaves
the seam inert (no behavior change). Step 3 adds a passing test against
existing behavior. Step 4 is the actual swap, covered by both the new α
tests and the pre-existing γ test. Steps 5–7 are documentation/FIXME
cleanups.

**Rollback.** Revert the PR. The public surface is unchanged, so no
downstream coordination is needed. The `deps_factory` kwarg may remain
harmlessly if a rollback misses it (it is optional and defaults to current
behavior).

**No schema migration, no data migration, no config change.** Pure code
swap on a read path.

## Open Questions

None. All decisions were locked during the explore phase (see
`explore-brief.md`) and re-affirmed by the proposal freeze. The two FIXMEs
encode the only known follow-ups (vestigial `CLIDeps.query` cleanup;
cross-cutting backoff gap) and are explicitly out of scope for this change.
