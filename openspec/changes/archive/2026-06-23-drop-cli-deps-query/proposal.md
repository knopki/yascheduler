## Why

`CLIDeps.query` in `yascheduler/di.py` is dead weight: it has zero production
callers (the client query path goes through the `query_tasks` use case via
`uow_factory`, not through this method). Its only caller is
`tests/unit/test_di.py::test_query_uses_uow_factory`. The previous change
`2026-06-23-client-query-uow` deliberately deferred this cleanup and encoded it
as a known follow-up (see its `design.md` "Open follow-ups" section and
`review-log.md` finding at lines 41-42). This proposal executes that deferred
sweep so the DI surface matches actual usage and the specs stop requiring an
attribute that nothing in production exercises.

## What Changes

- **REMOVE** the `CLIDeps.query` method from `yascheduler/di.py`, along with
  its `START_CONTRACT: CLIDeps.query` / `END_CONTRACT` block and the `# FIXME`
  comment above it.
- **REMOVE** `tests/unit/test_di.py::TestCLIDeps::test_query_uses_uow_factory`
  (the sole caller) and update the `TestCLIDeps` class docstring + the file's
  `SCOPE` line to drop the `query` mention.
- **UPDATE** docstring/`MODULE_MAP` references in `yascheduler/di.py` from
  "submit and query" to "submit".
- **UPDATE** `docs/knowledge-graph.xml` `class-CLIDeps` PURPOSE from
  "submit and query" to "submit".
- No behavioral change to any production code path. `CLIDeps.submit`,
  `make_cli_deps`, `make_daemon`, and the `query_tasks` use case are
  untouched.

This is **not** a breaking change to the project's public interface (per
`AGENTS.md`): `CLIDeps` is internal DI plumbing, not in the stability list
(CLI commands, `Yascheduler` public API, INI format, DB schema, AiiDA
entrypoint). It is, however, a spec-level behavior change because the
`dependency-injection` spec currently requires the `query` attribute, so this
proposal updates that requirement in the same change.

## Capabilities

### New Capabilities
<!-- None. This is a removal/cleanup. -->

### Modified Capabilities
- `dependency-injection`: Drop the requirement that `CLIDeps` exposes a `query`
  attribute. Rewrite the "CLI deps include submit and query use cases" scenario
  to cover only `submit` (the only path the client uses).
- `testing-unit`: Drop the line asserting `CLIDeps` "delegates `submit`/`query`"
  in the unit-test mapping notes; keep only `submit`.

## Impact

- **Code**: `yascheduler/di.py` (method + contract block + FIXME + MODULE_MAP
  line + class docstring), `tests/unit/test_di.py` (one test method + SCOPE
  line + class docstring).
- **Specs**: `openspec/specs/dependency-injection/spec.md`,
  `openspec/specs/testing-unit/spec.md`.
- **Knowledge graph**: `docs/knowledge-graph.xml` (one PURPOSE attribute).
- **APIs / dependencies**: none. No import removed, no new dependency.
- **Migration**: none. Internal-only surface; no DB, INI, CLI, or AiiDA
  surface affected.
- **Verification**: `uv run pytest -m unit`, `openspec validate --all --json`,
  `python3 scripts/grace_check.py`.
