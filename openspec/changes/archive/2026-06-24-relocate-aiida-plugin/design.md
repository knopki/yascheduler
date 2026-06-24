## Context

`yascheduler` has a hexagonal / clean-architecture layout enforced by
`import-linter` via a `layers` contract in `pyproject.toml`. The current
contract is five layers:

```
yascheduler.entrypoints → yascheduler.infra → yascheduler.application → yascheduler.domain → yascheduler.shared
```

`add-entrypoints-layer` (archived 2026-06-24) introduced the `entrypoints`
layer and moved `client.py` into it as the first resident. It explicitly
deferred `aiida_plugin.py`, `di.py`, `daemon_*.py`, and `infra/cli/` to
follow-up changes. The `package-facades` spec still carries the forward
reference for `aiida_plugin.py`: "Scheduled for migration into
`yascheduler.entrypoints` in a follow-up change; remains at the package root
in the interim." This change fulfills that deferred commitment for
`aiida_plugin.py` only; `di.py`, `daemon_*.py`, and `infra/cli/` remain
deferred.

`make_aiida()` in `di.py` is a `NotImplementedError` stub introduced in
anticipation of wiring the AiiDA plugin through DI. The plugin never wired
through (it talks to yascheduler over SSH transport, not via the composition
root), and there is no plan to do so. The stub is dead code.

`ARCHITECTURE.md` has drifted across several past changes: the §1 diagram
still shows `client.py` at the package root as "Public API — Yascheduler
facade" (it is a compat shim; the real implementation lives in
`entrypoints/client.py`); the diagram's "ENTRY POINTS & LEGACY WRAPPERS" box
predates the `entrypoints` layer; §2 table and §2.9 still claim the AiiDA
plugin "uses `Yascheduler` client" (factually wrong — the plugin uses SSH
transport, verified zero yascheduler imports); §4 tree shows no
`entrypoints/` or `shared/` subtrees; §6.2 plans a `make_aiida()` future that
is being deleted; §6.3 is resolved-but-still-listed; §7 Open Questions is
stale / cancelled.

Constraints:
- Public interface stability (AGENTS.md): `from yascheduler import
  Yascheduler`, `from yascheduler.client import Yascheduler` (shim), and the
  AiiDA scheduler entrypoint (by *name*, not module path) must remain
  resolvable.
- `import-linter` layers contract: `yascheduler.entrypoints` is already layer
  1; the plugin imports only `aiida.*` + stdlib, so it is trivially
  R3-compliant in its new home — no contract change.
- GRACE-lite: knowledge graph and module contracts updated in the same
  change.
- No new dependencies. Python `>=3.9`.
- `CHANGELOG.md` is commitizen-managed (`update_changelog_on_bump`) — not
  touched.

## Goals / Non-Goals

**Goals:**
- Relocate `yascheduler/aiida_plugin.py` →
  `yascheduler/entrypoints/aiida_plugin.py` (flat file, no subpackage, no
  compat shim).
- Rewrite `[project.entry-points."aiida.schedulers"]` in `pyproject.toml`
  to the new object path; the entry-point *name* `yascheduler` is unchanged.
- Delete `make_aiida()` from `di.py` (function + contract block + MODULE_MAP
  + SCOPE/PURPOSE "AiiDA" mention + CHANGE_SUMMARY) and the matching
  `TestMakeAiida` from `tests/unit/test_di.py`.
- Update `entrypoints/__init__.py` comment + CHANGE_SUMMARY to reflect the
  second resident; do NOT re-export `YaScheduler` from the facade (lazy
  publication).
- Update `docs/knowledge-graph.xml`: `M-AIIDA <path>`; `M-DI` drops
  `<fn-make_aiida>` annotation and the "AiiDA" token in its `<purpose>`.
- Rewrite affected requirements in `openspec/specs/package-facades/spec.md`
  (outside-set list drops `yascheduler.aiida_plugin` + stale `yascheduler.db`;
  lazy-public prose drops the `aiida_plugin.py` follow-up sentence; "SHALL
  remain loadable" requirement + scenario reground on the new path) and
  `openspec/specs/testing-unit/spec.md` (drop `make_aiida` bullet).
- Refresh `docs/ARCHITECTURE.md` to current reality (full refresh, not point
  edits): §1 diagram gains PRESENTATION (`entrypoints`) + `shared` blocks and
  drops the stale "ENTRY POINTS & LEGACY WRAPPERS" box; §2 table fixes
  `client.py` (shim) and `aiida_plugin.py` (entrypoints, SSH transport)
  rows; §2.8 drops `make_aiida`; §2.9, §3.7, §3.8 reground on
  `entrypoints/client.py`; §4 tree shows `entrypoints/` + `shared/` subtrees,
  keeps `client.py` at root as shim, drops `aiida_plugin.py` from root,
  expands `infra/` one nested level without files; §6.2 and §6.3 deleted;
  §7 deleted.

**Non-Goals:**
- Migrate `di.py`, `daemon_systemd.py`, `daemon_sysv.py`, or `infra/cli/`
  into `entrypoints/`. Remain at the package root, tracked separately.
- Wire the AiiDA plugin through DI (no `make_aiida` replacement).
- Add any test for the AiiDA plugin entry-point load (no test expansion).
- Touch `CHANGELOG.md`.
- Promote `YaScheduler` to the `entrypoints` facade (lazy publication: the
  plugin is discovered via the entry-point registry, not via
  `from yascheduler.entrypoints import …`).
- Add a compat shim at `yascheduler/aiida_plugin.py` (the only consumer is
  the entry-point registry, which is being rewritten; no known external
  deep-path importer).

## Decisions

### D1. Target path: flat `entrypoints/aiida_plugin.py`

**Choice:** `yascheduler/entrypoints/aiida_plugin.py` (flat file).

**Rationale:** Matches the `client.py` precedent in `entrypoints/`. The
plugin is self-contained (2 classes, 330 lines, zero yascheduler imports);
a subpackage would add a directory for no structural benefit.

**Alternatives considered:**
- `entrypoints/aiida/plugin.py` (subpackage) — rejected: over-structure for a
  self-contained file; no sibling modules anticipated.

### D2. No compat shim at the old path

**Choice:** `yascheduler/aiida_plugin.py` ceases to exist; no shim.

**Rationale:** The only consumer is
`[project.entry-points."aiida.schedulers"]`, which is being rewritten to the
new path. AiiDA discovers plugins by entry-point *name* via
`importlib.metadata.entry_points`, not by module path, so `verdi` /
`reentry scan` users see no change. No known external caller uses
`from yascheduler.aiida_plugin import …`, and the project does not commit to
preserving that deep path (unlike `yascheduler.client`, which has an explicit
shim requirement in `package-facades`).

**Alternatives considered:**
- Mirror the `client.py` shim treatment — rejected by the user: "не нужен
  шим, нужно entry-point поменять и всё будет ок."

### D3. Facade does NOT re-export `YaScheduler`

**Choice:** `entrypoints/__init__.py` keeps re-exporting only `Yascheduler`
(from `.client`); `YaScheduler` is NOT added.

**Rationale:** Lazy-publication policy (`package-facades` spec). Plugin
discovery is via the entry-point registry, not via
`from yascheduler.entrypoints import YaScheduler`. Re-exporting would widen
the public surface for no consumer.

### D4. `make_aiida()` deleted, not stubbed

**Choice:** Delete the function, its contract block, the MODULE_MAP line,
the SCOPE/PURPOSE "AiiDA" mention, the `<fn-make_aiida>` graph annotation,
and the "AiiDA" token in `M-DI`'s `<purpose>`. No replacement.

**Rationale:** The stub has been `NotImplementedError` since introduction; the
plugin never wired through DI (it uses SSH transport); the user judges it
"useless code now and in the future." Dead code — delete. The
`testing-unit` spec bullet "`make_aiida` raises `NotImplementedError`" is
removed in the same change. The `dependency-injection` spec has no
`make_aiida` requirement (verified), so no delta there.

### D5. ARCHITECTURE.md full refresh

**Choice:** Rewrite the stale sections to current reality rather than apply
point edits.

**Rationale:** The file has drifted across `add-entrypoints-layer`,
`shared-kernel-extraction`, `remove-legacy-db`, and now this change. Point
edits would leave the §1 diagram still showing a "LEGACY WRAPPERS" box and
`client.py` at root as facade. The user explicitly asked to "обновить
нормально, а не только про aiida_plugin.py."

**Specific edits:**
- §1 diagram: add PRESENTATION (`yascheduler.entrypoints`) block listing
  `client.py` and `aiida_plugin.py` as residents; add `shared/` block;
  Composition Root / outside-layer-set block holds `di.py`, `config/`,
  `daemon_*.py`, `client.py` (shim); drop `make_aiida()` line; drop the
  "ENTRY POINTS & LEGACY WRAPPERS" box (contents redistributed).
- §2 table: `client.py` → shim (not facade); `aiida_plugin.py` →
  `entrypoints/aiida_plugin.py`, SSH transport (NOT "uses Yascheduler
  client"); `di.py` row drops `make_aiida`.
- §2.8: drop `make_aiida(config)` bullet.
- §2.9: rewrite — public API in `entrypoints/client.py`; `client.py` is
  shim; `aiida_plugin.py` in `entrypoints/`; drop the false "uses Yascheduler
  client" claim.
- §3.7: reground AiiDA line to the new entry-point path; fix "class
  Yascheduler in `client.py`" → facade in `entrypoints/client.py`.
- §3.8: reground to `entrypoints/client.py` as the real home; `client.py` is
  the shim.
- §4 tree: show `entrypoints/` subtree (`__init__.py`, `client.py`,
  `aiida_plugin.py`); `client.py` remains at root as shim; show `shared/`
  subtree; expand `infra/` one nested level (`persistence/`, `ssh/`,
  `cloud/`, `cli/`, `notifier/`) without files; drop `aiida_plugin.py` from
  root.
- §6.2 (`make_aiida()` implementation): DELETE.
- §6.3 (`client.py` query methods): DELETE (resolved).
- §7 Open Questions: DELETE (stale / cancelled per user).

### D6. `yascheduler.db` cleaned from outside-set lists

**Choice:** While editing the `package-facades` outside-set enumeration
(L75-80 prose, L253 scenario) to drop `yascheduler.aiida_plugin`, also drop
the stale `yascheduler.db` (module removed in `remove-legacy-db`).

**Rationale:** We are already editing these lines; the `yascheduler.db`
reference is factually wrong (the module does not exist). Leaving it would
keep the spec internally inconsistent. L253 does NOT list `yascheduler.db`,
so only `aiida_plugin` is removed there. L78 prose ("the legacy DB layer, or
the AiiDA plugin is negligible") also goes stale and is rewritten.

## Risks / Trade-offs

- **Risk:** Downstream code pins `from yascheduler.aiida_plugin import …`.
  → **Mitigation:** The entry-point *name* `yascheduler` is unchanged, so
  AiiDA discovery is unaffected. No such external caller is known. The
  project does not commit to preserving that deep path. Accepted as
  **BREAKING** for the (unknown, likely empty) set of deep-path importers.
- **Risk:** Downstream code imports `make_aiida` from `yascheduler.di`.
  → **Mitigation:** Only `tests/unit/test_di.py` did, and it is being
  updated in this change. Accepted as **BREAKING** for the (empty) set of
  external callers.
- **Risk:** ARCHITECTURE.md full refresh introduces new inaccuracies.
  → **Mitigation:** The refresh is grounded in the verified current state of
  the codebase (entrypoints layer exists, shared layer exists, aiida_plugin
  imports zero yascheduler modules, make_aiida is a stub). The knowledge
  graph is the canonical source; ARCHITECTURE.md defers to it per its own
  header note.
- **Risk:** `entrypoints/__init__.py` comment grows stale as more residents
  arrive.
  → **Mitigation:** The comment is updated in this change to name
  `client.py` and `aiida_plugin.py` as current residents; future follow-ups
  update it. Low risk — cosmetic.

## Migration Plan

This is a source-level relocation; no runtime migration is needed.

1. Apply the file move, `pyproject.toml` entry-point swap, `di.py` deletion,
   `test_di.py` cleanup, `entrypoints/__init__.py` comment update, knowledge
   graph update, spec rewrites, and ARCHITECTURE.md refresh in one change.
2. Reinstall the package (`uv pip install -e .` or `uv sync`) so the new
   entry-point path is registered in the installed metadata.
3. Verify AiiDA discovery: `python -c "import importlib.metadata as m;
   eps=m.entry_points(); print([e for e in eps.select(group='aiida.schedulers')
   if e.name=='yascheduler'])"` shows the new object path
   `yascheduler.entrypoints.aiida_plugin:YaScheduler`.
4. Run `uv run pytest -m unit`, `uv run lint-imports`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run zuban check`,
   `python3 scripts/grace_check.py`, `openspec validate --all --json`.

**Rollback:** Revert the change commit. The entry-point registry returns to
the old path on reinstall. No data migration, no schema change.

## Open Questions

None remaining. All resolved during exploration:

- Shim or no shim → no shim.
- Test coverage gap → out of scope.
- ARCHITECTURE.md framing → full refresh.
- Stale `yascheduler.db` in outside-set lists → clean up in this change.
- `make_aiida` → delete.
- §6.2 / §6.3 / §7 → delete all three.
- §4 tree depth → directories only (no files) below top level; `infra/` one
  nested level; `client.py` remains at root as shim.
- CHANGELOG → not touched.
- Change name → `relocate-aiida-plugin`, with `make_aiida` deletion in scope.