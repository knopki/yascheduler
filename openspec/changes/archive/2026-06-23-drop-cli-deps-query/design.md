## Context

`CLIDeps` is the lightweight DI container produced by `make_cli_deps` for CLI
and client use. Its declared surface has two methods:

- `submit(...)` — used in production by `Yascheduler.queue_submit_task_async`
  via the `deps_factory` seam.
- `query(task_id)` — declared in `yascheduler/di.py` but with zero production
  callers. `Yascheduler.queue_get_tasks_async` does not use it; instead it
  reaches into `deps.uow_factory` and runs the `query_tasks` use case
  directly (per archived change `2026-06-23-client-query-uow`, design D1/D2).

`query` survived the client-query refactor as a deliberately deferred cleanup,
marked with a `# FIXME: vestigial` comment in `di.py` and explicitly enumerated
in the prior change's "Open follow-ups". The `dependency-injection` spec still
requires the attribute, so the surface and the spec disagree with actual
usage. This change aligns them.

## Goals / Non-Goals

**Goals:**
- Remove `CLIDeps.query` (method, contract block, FIXME).
- Remove the single test that exercises it
  (`test_di.py::TestCLIDeps::test_query_uses_uow_factory`).
- Update docstrings, `MODULE_MAP`, knowledge-graph `class-CLIDeps` PURPOSE, and
  the two spec lines that currently require `query`, so no stale artifact
  mentions a method that no longer exists.

**Non-Goals:**
- Touch `CLIDeps.submit`, `make_cli_deps`, `make_daemon`, or the `query_tasks`
  use case. Their behavior is unchanged.
- Refactor anything else in `di.py`. The cloud-capacity filter hardening and
  active-clouds logic from v5.1.0 stay exactly as they are.
- Add new tests. This is a removal; the remaining `TestCLIDeps` suite
  (constructor, `submit`) still covers the live surface.
- Change any public-stability surface (CLI commands, `Yascheduler` public API,
  INI, DB schema, AiiDA entrypoint). `CLIDeps` is internal DI plumbing.

## Decisions

### D1. Delete `query` outright, not deprecate

**Choice:** Remove the method, contract block, and FIXME in one commit. Also
remove the one test that calls it.

**Alternatives considered:**
- *Deprecate with `warnings.warn(DeprecationWarning)` first, remove later.*
  Rejected: there are no external callers to warn. `CLIDeps` is not in the
  `AGENTS.md` stability list; nothing outside the repo imports it. A
  deprecation cycle would warn nobody and keep the dead code on the books.
- *Keep `query` and add a sibling `query_many`.* Rejected by the prior
  `client-query-uow` change (design D-alt-A): use-case-on-`CLIDeps` splits the
  use-case catalog. The `query_tasks` use case is the canonical path.

**Rationale:** the spec is the only thing that pretends `query` is a live
contract. Removing the spec requirement + the code in the same change is the
honest state.

### D2. Rewrite the `dependency-injection` scenario rather than remove it

**Choice:** In the `make_cli_deps factory` requirement, modify the second
scenario from "CLI deps include submit and query use cases" to "CLI deps
include submit use case" — assert only that `CLIDeps.submit` is present and
usable for task submission. The first scenario ("CLI deps do not create SSH
connections") is untouched.

**Alternatives considered:**
- *Remove the second scenario entirely, leave only the SSH-connections one.*
  Rejected: the scenario encodes the public expectation that the CLI deps
  surface includes the submission entry point. Dropping it would leave the
  requirement with only a negative assertion ("does not create SSH"), which is
  weaker than the current intent.
- *Add a new "Submit only" requirement and `## REMOVED` the old one.*
  Rejected: it's the same requirement, narrowed. `## MODIFIED` with the full
  updated content is the correct delta per the OpenSpec workflow
  ("MODIFIED Requirements ... MUST include full updated content").

### D3. Edit the `testing-unit` bullet list in place via `## MODIFIED`

**Choice:** Modify the "Dependency injection factories" requirement to drop
the `/query` mention in its bullet list (`CLIDeps` stores fields and delegates
`submit`/`query` → `submit`). The other three bullets and the existing
`make_cli_deps returns CLIDeps with PostgresUnitOfWork factory` scenario are
preserved verbatim.

**Rationale:** the bullet list is part of a single requirement block.
Splitting out a new requirement would fragment the DI test mapping notes;
editing in place via `## MODIFIED` keeps the structure stable.

### D4. Graph update is mechanical

One attribute in `docs/knowledge-graph.xml`:
`<class-CLIDeps PURPOSE="Lightweight dependency container for CLI submit and query" />`
→ `... for CLI submit" />`. No M-ID added/removed, no `<depends>` or
`<CrossLink>` change. Touched in the same change per GRACE-lite rule 3 because
the public annotation surface changed; trivial enough to live as a task line,
recorded here for traceability.

## Risks / Trade-offs

- **[A future caller wanted `CLIDeps.query`] → Mitigation:** none needed at
  code level; the canonical path (`query_tasks` use case via `uow_factory`)
  remains available and is what production already uses. If a caller genuinely
  needs single-task lookup, they should reach for `uow_factory` directly, same
  as `Yascheduler.queue_get_tasks_async` does.
- **[A test outside the enumerated set calls `.query()` and silently breaks]**
  → Mitigation: `grep` verification in the tasks confirms
  `tests/unit/test_di.py::test_query_uses_uow_factory` is the only caller. The
  other CLIDeps test (`test_client_query.py`) uses a `FakeCLIDeps` stub that
  does not implement `.query()`.
- **[Spec drift between code and spec re-emerges] → Mitigation:** removing the
  spec requirement in the same change eliminates the current drift; future
  additions to `CLIDeps` surface will go through the same OpenSpec flow.

## Migration Plan

None. Internal-only surface; no DB, INI, CLI, or AiiDA consumer affected. No
release note required beyond the Conventional Commit that lands the change.

## Open Questions

None. The scope is fully determined by the existing FIXME and the prior
change's encoded follow-up.
