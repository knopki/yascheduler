# Design — Drop Attrs Dependency (P5)

## Context

P5 is the cleanup tail of the config-layer split (`docs/config-layer-split-plan.md`).
By the time P5 runs, P1–P4 have archived and:

- `yascheduler/config/` is deleted (P4); the last four attrs users
  (`config.py`, `db.py`, `remote.py`, `utils.py`) are gone with it.
- `infra/cloud/` attrs consumers migrated to stdlib dataclasses
  (`migrate-cloud-from-attrs`).
- `infra/ssh/platform/` migrated (`migrate-ssh-platform-from-attrs`).
- `application/queue.py` migrated (`queue-dataclass-migration`).

So P5 has no class to migrate. Its scope is three administrative artifacts:

1. The `attrs>=22.2.0` line in `pyproject.toml`'s `dependencies`.
2. The stale `# FIXME: migrate from attrs to dataclasses` marker in
   `config/config.py` (deleted by P4, but P5 verifies and removes the breadcrumb
   if it survived).
3. `CHANGE_SUMMARY` entries that describe the attrs era as if it were current.

Plus one forward-looking guard: a canary test preventing silent reintroduction.

## Decisions

### D1: AST-based canary, not import-time grep

The canary parses each `.py` file with `ast` and visits `ImportFrom`/`Import`
nodes, rather than running a `grep` over source text. Reasons:

- **Precision**: `grep "from attrs"` would false-positive on `CHANGE_SUMMARY`
  comment lines like `# LAST_CHANGE: v1.1.0 - Migrate CloudConfig from
  attrs.define(frozen=True) to ...`. The AST parse ignores comments entirely.
- **Coverage**: catches `import attrs`, `import attrs as a`, `from attrs
  import x`, `from attr import x` (note the singular `attr` — a typo import
  that existed in `infra/cloud/protocols.py` before migration; the canary
  guards against its return).
- **Position reporting**: the AST node carries `lineno`/`col_offset`, so the
  failure message can point the contributor at the exact file and line.

Rejected alternative: a `pytest` import-time hook that tries to import every
yascheduler module and checks `sys.modules` for `attrs`. Slower, requires a
running event loop for async modules, and does not catch `TYPE_CHECKING`-only
imports (which the AST canary does catch — see D2).

### D2: The canary flags TYPE_CHECKING-guarded attrs imports too

A `TYPE_CHECKING`-guarded `from attrs import ...` is not a runtime import, so
it does not create a runtime dependency. Why flag it?

- `attrs` is a runtime third-party package, not a typing shim. A
  `TYPE_CHECKING`-guarded import signals "I want attrs types in my type
  annotations" — but the project's types are stdlib dataclasses; there is no
  attrs-specific type worth importing.
- A `TYPE_CHECKING` import is one `# type: ignore` removal away from becoming
  a runtime import. The canary prevents the thin end of the wedge.
- Precedent: `infra/cloud/protocols.py` had a `from attr import define` typo
  import (singular `attr`, no `s`) that was a typing-time smell and became a
  real migration bug. The canary catches both `attrs` and `attr`.

Trade-off: a legitimate `TYPE_CHECKING` import of an attrs-defined third-party
type would be flagged. No such legitimate case exists in this codebase after
P1–P4; if one arises, it is a signal to reconsider the dependency, not to
silence the canary.

### D3: Transitive attrs via aiohttp is explicitly allowed

`uv.lock` shows `aiohttp` depends on `attrs`. Removing `attrs` from
`pyproject.toml`'s direct dependencies does NOT remove it from the
environment — `uv lock` keeps it as a transitive. This is expected and
correct:

- yascheduler does not control `aiohttp`'s dependencies.
- The canary guards `yascheduler/`'s own import graph, not the environment.
- `import attrs` in the project environment still succeeds (verified in
  task 7.12), so any debug script or REPL usage is unaffected.

The spec's `transitive attrs via aiohttp is allowed` scenario codifies this so
a future contributor does not file a bug "attrs is still in uv.lock, the P5
spec says it should be gone."

### D4: No delta to existing capability specs

P5 does not modify `cloud-config-dtos`, `domain-engine-types`,
`domain-entities`, or any other spec that mentions "stdlib dataclass, no
attrs". Those specs already codify the *form* of the types (frozen stdlib
dataclass). P5 codifies the *dependency policy* (no direct attrs in
`pyproject.toml` + canary guard). These are orthogonal concerns:

- `cloud-config-dtos` says "ConfigCloudAzure is a frozen stdlib dataclass with
  no attrs dependency" — that is a statement about the class form, scoped to
  one module.
- `no-attrs-dependency` says "yascheduler as a whole has no direct attrs
  dependency and a canary guards reintroduction" — that is a statement about
  the project's dependency policy, scoped to the whole package.

A delta to `cloud-config-dtos` adding "and the canary guards it" would be
redundant: the canary is project-wide, not cloud-specific. A delta to
`domain-entities` would be similarly redundant. The new capability stands
alone.

### D5: No knowledge-graph change

`docs/knowledge-graph.xml` tracks in-repo modules and their call edges.
`attrs` is a third-party package, not an in-repo module; it has no `M-*` node.
Removing the `pyproject.toml` line does not add, remove, or repoint any `M-*`
node, `DF-*` data flow, or `CrossLink`. The graph is untouched.

The only graph-adjacent artifact is the `CHANGE_SUMMARY` refreshes in
`infra/cloud/cloud_config.py` and `infra/cloud/adapters.py` — but those are
file-local metadata, not graph nodes. The graph itself does not record
dependency declarations.

### D6: Canary test location and marker

The canary lives in `tests/unit/test_no_attrs_dependency.py` (singular file,
singular test). It is a unit test — it does not require DB, SSH, or
testcontainers; it parses source files with stdlib `ast`. The `unit` marker
applies by directory convention (`tests/unit/`); no explicit `@pytest.mark`
decorator is needed unless the project's `conftest.py` requires one. Task 4.4
verifies the convention.

Rejected alternative: a `tests/` top-level canary. The `unit/` directory is
the right home because the canary is fast, hermetic, and does not need
integration infrastructure.

## Risks

- **Canary brittleness**: the AST walk targets `ImportFrom`/`Import` nodes by
  module name prefix (`attrs`, `attr`). A future third-party package named
  `attrs-something` would be flagged. Mitigation: the prefix match is on the
  exact module names `attrs` and `attr` (the two real packages), not on a
  substring; `from attrs_foo import x` does not match. The test's CONTRACT
  documents the exact prefix rule.
- **Stale `CHANGE_SUMMARY` wording**: the canary does not flag comment lines,
  so a `CHANGE_SUMMARY` saying "uses attrs" would not be caught. Mitigation:
  task 3.1 and 3.2 manually verify the `MODULE_MAP`/`MODULE_CONTRACT` wording
  in the two files most likely to drift; the grep in task 7.11 catches
  `FIXME.*attrs` markers (the most common stale wording form).
- **`uv.lock` churn**: regenerating the lockfile may pull in version bumps for
  unrelated packages. Mitigation: task 1.2 verifies the `attrs` lines
  specifically; any unrelated churn is reviewed in the PR diff before merge.
  If `uv lock` produces unacceptable churn, `uv lock --upgrade-package attrs`
  is a narrower alternative (but `attrs` is being removed, not upgraded — the
  full `uv lock` is the correct regeneration).
- **P4 not archived when P5 starts**: P5 assumes `yascheduler/config/` is
  deleted. If P4 is still in flight, task 2.1 falls back to "remove the FIXME
  marker from the still-existing file" and task 1.1 still removes the
  `pyproject.toml` line. The canary (task 4.1) would then flag the four config
  files as attrs importers and fail. Mitigation: the proposal's `Why` section
  states the P4-predecessor assumption explicitly; if P5 is attempted before
  P4 archives, the canary will fail loudly, which is the correct signal.