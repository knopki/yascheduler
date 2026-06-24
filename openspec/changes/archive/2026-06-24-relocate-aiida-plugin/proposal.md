## Why

`yascheduler/aiida_plugin.py` is a driving adapter that lives at the package
root, outside the `import-linter` layers contract — the same structural debt
that `add-entrypoints-layer` (archived 2026-06-24) set out to retire. That
change moved only `client.py` into `yascheduler.entrypoints/` and explicitly
deferred the plugin to a follow-up; the `package-facades` spec still carries
the forward reference "Scheduled for migration into `yascheduler.entrypoints`
in a follow-up change; remains at the package root in the interim." This
change fulfills that deferred commitment.

In the same move, `make_aiida()` in `di.py` is deleted: it has been a
`NotImplementedError` stub since introduction, the plugin never wired through
DI, and there is no future plan to do so. It is dead code.

`ARCHITECTURE.md` has drifted across several past changes (the entrypoints
layer, the shared kernel, the legacy-db removal); this change brings it
current rather than applying point edits.

## What Changes

- Move `yascheduler/aiida_plugin.py` → `yascheduler/entrypoints/aiida_plugin.py`
  (update `# FILE:` header path, bump `VERSION`, add `START_CHANGE_SUMMARY`
  entry). The plugin imports only `aiida.*` and stdlib — zero yascheduler
  imports — so no internal imports change. **No compat shim** at the old path:
  the old module path ceases to exist.
- Update `pyproject.toml` `[project.entry-points."aiida.schedulers"]`:
  `yascheduler = "yascheduler.aiida_plugin:YaScheduler"` →
  `yascheduler = "yascheduler.entrypoints.aiida_plugin:YaScheduler"`. The
  entry-point *name* (`yascheduler`) is unchanged — AiiDA discovers plugins by
  name via `importlib.metadata.entry_points`, so `verdi` / `reentry scan`
  users see no behavioral change. **BREAKING** only for downstream code that
  pinned `from yascheduler.aiida_plugin import …` (no such caller is known).
- Update `yascheduler/entrypoints/__init__.py` comment + `START_CHANGE_SUMMARY`
  to reflect `aiida_plugin.py` as a second resident. The facade does NOT
  re-export `YaScheduler` (lazy-public policy; discovery is via the
  entry-point registry, not the package facade).
- Delete `make_aiida()` from `yascheduler/di.py` (function + its
  `START_CONTRACT`/`END_CONTRACT` block, which is the only place `M-AIIDA`
  appears in the file — the top-level `MODULE_CONTRACT LINKS` field does NOT
  list `M-AIIDA` and needs no separate edit) + `MODULE_MAP` line + `SCOPE`
  reference + new `START_CHANGE_SUMMARY` entry). The `MODULE_CONTRACT PURPOSE`
  (L4) drops the "AiiDA" mention ("factories per entry point (daemon, CLI,
  AiiDA)" → "factories per entry point (daemon, CLI)") to stay consistent with
  the trimmed `SCOPE`. **BREAKING** for code that imported `make_aiida` from
  `yascheduler.di` (only the unit test did).
- Delete `class TestMakeAiida` and the `make_aiida` import from
  `tests/unit/test_di.py`; update its `MODULE_CONTRACT SCOPE` and `MODULE_MAP`.
- Update `docs/knowledge-graph.xml`: `M-AIIDA <path>` →
  `yascheduler/entrypoints/aiida_plugin.py` (depends stays `none`);
  `M-DI` drops the `<fn-make_aiida>` annotation; the `M-DI` `<purpose>` drops
  the "AiiDA" mention ("factories per entry point: daemon, CLI, AiiDA" →
  "factories per entry point: daemon, CLI") to stay consistent with the
  trimmed `<annotations>`. `M-AIIDA` is NOT in `M-DI`'s `<depends>` today, so
  no depends edit is needed.
- Rewrite affected requirements in `openspec/specs/package-facades/spec.md`:
  the outside-layer-set exemption list drops `yascheduler.aiida_plugin` (now in
  the entrypoints layer, no shim) and the stale `yascheduler.db` (module
  removed in `remove-legacy-db`); the lazy-public policy prose drops the
  `aiida_plugin.py` follow-up sentence; the "AiiDA plugin entrypoint SHALL
  remain loadable" requirement is regrounded on the new path
  `yascheduler.entrypoints.aiida_plugin:YaScheduler`; the "AiiDA plugin still
  loads" scenario is kept and regrounded.
- Modify `openspec/specs/testing-unit/spec.md`: the "Dependency injection
  factories" requirement drops the `make_aiida raises NotImplementedError`
  bullet (the other 3 bullets stay).
- Rewrite `docs/ARCHITECTURE.md` to reflect current reality — not point edits:
  the §1 diagram gains a PRESENTATION (`yascheduler.entrypoints`) block and a
  `shared/` block; the stale "ENTRY POINTS & LEGACY WRAPPERS" box is
  redistributed (real residents → entrypoints; shim → outside-set; daemon
  launchers → outside-set, deferred); §2 table fixes the `client.py` (shim)
  and `aiida_plugin.py` (entrypoints, SSH transport — does NOT use the
  `Yascheduler` client) rows; §2.8 drops `make_aiida`; §2.9, §3.7, §3.8 are
  regrounded on `entrypoints/client.py` as the real facade; §4 tree shows the
  `entrypoints/` and `shared/` subtrees and drops `aiida_plugin.py` from root;
  §6.2 (`make_aiida()` implementation) is deleted; §6.3 (`client.py` query
  methods) is deleted (resolved); §7 Open Questions is deleted (stale /
  cancelled).

### Out of scope

- Migrating `di.py`, `daemon_systemd.py`, `daemon_sysv.py`, or `infra/cli/`
  into `entrypoints/` — remain at the package root, tracked separately.
- Wiring the AiiDA plugin through DI (no `make_aiida` replacement).
- Adding any test for the AiiDA plugin entry-point load (no test expansion).
- Touching `CHANGELOG.md` (commitizen owns it via `update_changelog_on_bump`).

## Capabilities

### New Capabilities

_None._ The relocation is a structural concern whose requirements (layer
membership, entry-point path, outside-set composition) are expressed as
modifications to existing capabilities.

### Modified Capabilities

- `package-facades`: Outside-layer-set exemption list drops
  `yascheduler.aiida_plugin` (relocated into the `entrypoints` layer, no shim)
  and the stale `yascheduler.db` (module removed); the lazy-public policy
  prose drops the `aiida_plugin.py` follow-up sentence; the "AiiDA plugin
  entrypoint SHALL remain loadable" requirement and its "AiiDA plugin still
  loads" scenario are reground on the new entry-point path
  `yascheduler.entrypoints.aiida_plugin:YaScheduler`.
- `testing-unit`: The "Dependency injection factories" requirement drops the
  `make_aiida raises NotImplementedError` bullet (function deleted).

## Impact

- **Code**: `yascheduler/aiida_plugin.py` moves to
  `yascheduler/entrypoints/aiida_plugin.py` (no shim); `yascheduler/di.py`
  loses `make_aiida`; `yascheduler/entrypoints/__init__.py` comment + change
  summary updated; `tests/unit/test_di.py` loses `TestMakeAiida` and the
  `make_aiida` import.
- **Config**: `pyproject.toml` `[project.entry-points."aiida.schedulers"]`
  object path rewritten; `[tool.importlinter]` layers contract unchanged
  (entrypoints is already layer 1; plugin imports only external `aiida.*`).
- **External API**: `from yascheduler import Yascheduler` unchanged. The AiiDA
  entry-point *name* (`yascheduler`) is unchanged — AiiDA's plugin discovery
  is by name, not module path, so `verdi` / `reentry scan` users see no change.
  **BREAKING** for downstream code that pinned
  `from yascheduler.aiida_plugin import …` (no such caller is known) or
  `from yascheduler.di import make_aiida` (only the unit test did).
- **Specs**: `openspec/specs/package-facades/spec.md` and
  `openspec/specs/testing-unit/spec.md` rewritten in the affected
  requirements.
- **Knowledge graph**: `docs/knowledge-graph.xml` `M-AIIDA` path update + `M-DI`
  annotation/link cleanup.
- **Docs**: `docs/ARCHITECTURE.md` full refresh (§1 diagram, §2 table, §2.8,
  §2.9, §3.7, §3.8, §4 tree, §6.2/§6.3 deletions, §7 deletion).
- **Dependencies**: none added or removed.