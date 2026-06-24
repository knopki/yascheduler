# Explore Brief — relocate-aiida-plugin

## Alternatives considered & rejected

- **Keep `aiida_plugin.py` at package root + update only the entrypoint path.**
  Rejected: the `add-entrypoints-layer` change (archived 2026-06-24) already
  committed in `package-facades` spec to relocate the plugin into
  `yascheduler.entrypoints` in a follow-up; leaving it at root perpetuates the
  structural debt that change set out to retire.
- **Compat shim at `yascheduler/aiida_plugin.py` re-exporting `YaScheduler` /
  `YaschedJobResource`** (mirror the `client.py` shim treatment).
  Rejected by the user: the only consumer is the
  `[project.entry-points."aiida.schedulers"]` registry, which is being
  rewritten to the new path; there is no evidence of external
  `from yascheduler.aiida_plugin import …` callers, and the project does not
  commit to preserving that deep path (unlike `yascheduler.client`).
- **Keep `make_aiida()` stub for "future AiiDA integration".**
  Rejected: the stub has been `NotImplementedError` since introduction, the
  plugin never wired through DI, and the user judges it useless now and in
  the future. Dead code — delete.
- **Add an AiiDA-plugin-load smoke test in this change.**
  Rejected: user does not want scope expansion around testing.
- **Subpackage `entrypoints/aiida/plugin.py`** instead of flat file.
  Rejected: plugin is self-contained (2 classes, 330 lines); flat
  `entrypoints/aiida_plugin.py` matches the `client.py` precedent.
- **Re-export `YaScheduler` from `entrypoints/__init__.py`.**
  Rejected: lazy-public policy. Plugin discovery is via entry-point registry,
  not `from yascheduler.entrypoints import …`. Re-exporting widens public
  surface for no consumer.

## Final approach — labels / mappings / touchpoints

### File move

| From                                | To                                       |
| ----------------------------------- | ---------------------------------------- |
| `yascheduler/aiida_plugin.py`       | `yascheduler/entrypoints/aiida_plugin.py`|

Inside the moved file: update `# FILE:` header path; bump `VERSION`; add
`START_CHANGE_SUMMARY` entry. `MODULE_CONTRACT DEPENDS: none` and
`LINKS: M-AIIDA` unchanged (plugin imports only `aiida.*` + stdlib; verified
zero yascheduler imports).

No shim at the old path. Old path ceases to exist.

### `pyproject.toml`

`[project.entry-points."aiida.schedulers"]`:

```
yascheduler = "yascheduler.aiida_plugin:YaScheduler"
  →
yascheduler = "yascheduler.entrypoints.aiida_plugin:YaScheduler"
```

`[tool.importlinter]` layers contract: **unchanged** (`yascheduler.entrypoints`
already layer 1; plugin imports only external `aiida.*`, trivially R3-compliant).

### `di.py` — delete `make_aiida`

- Delete `def make_aiida(config) -> None` + its `START_CONTRACT` /
  `END_CONTRACT` block.
- `MODULE_CONTRACT SCOPE`: drop `make_aiida` from the list.
- `MODULE_CONTRACT LINKS`: drop `M-AIIDA`.
- `MODULE_MAP`: drop `make_aiida - Stub for future AiiDA integration`.
- Add `START_CHANGE_SUMMARY` entry.

### `tests/unit/test_di.py` — delete `TestMakeAiida`

- Delete `class TestMakeAiida` (2 test methods).
- Drop `make_aiida` from `from yascheduler.di import …`.
- `MODULE_CONTRACT SCOPE`: drop `make_aiida`.
- `MODULE_MAP`: drop `TestMakeAiida` line.

No new tests. Scope explicitly excludes test expansion.

### `entrypoints/__init__.py`

- Update comment: "only `client.py` resident" → "`client.py` and
  `aiida_plugin.py` residents".
- Add `START_CHANGE_SUMMARY` entry.
- **Do NOT** re-export `YaScheduler` from the facade (lazy-public policy).

### Knowledge graph (`docs/knowledge-graph.xml`)

- `M-AIIDA <path>`: `yascheduler/aiida_plugin.py` →
  `yascheduler/entrypoints/aiida_plugin.py`. `<depends>` stays `none`.
- `M-DI`: delete `<fn-make_aiida PURPOSE="Stub for future AiiDA integration" />`
  annotation; drop `M-AIIDA` from `M-DI` `<depends>` if present (verify —
  current `M-DI` depends list does not include `M-AIIDA`, only the LINKS
  field referenced it; LINKS field already updated in
  `add-entrypoints-layer` to drop `M-CLIENT` — needs `M-AIIDA` dropped too).
- No CrossLinks touch aiida (the spurious `M-AIIDA → M-CLIENT` CrossLink and
  `DF-AIIDA-INTEGRATION` were deleted in `add-entrypoints-layer`).
- Outside-set exemption list (`package-facades` spec prose): drop
  `yascheduler.aiida_plugin` (no longer at root, no shim) and the stale
  `yascheduler.db` (module removed in `remove-legacy-db`).

### Specs to modify (delta files under `specs/`)

**`package-facades`** (8 aiida references, lines 76, 78, 182, 246, 253, 467,
491, 492; plus stale `yascheduler.db` references at 76, 253):

- Outside-set prose (L75-80): drop `yascheduler.aiida_plugin` and the stale
  `yascheduler.db` from the enumerated list; keep `yascheduler.data`,
  `yascheduler.di`, `yascheduler.client`, `yascheduler.daemon_systemd`,
  `yascheduler.daemon_sysv`.
- Outside-set scenario (L253): same removals from the enumerated scenario
  list.
- L182 (lazy-public policy): drop `aiida_plugin.py` from the "migrate in
  follow-up" sentence (it is migrating in THIS change).
- L246 bullet: rewrite — `yascheduler.aiida_plugin` no longer exists at root;
  the plugin lives at `yascheduler.entrypoints.aiida_plugin` and is discovered
  via the entry-point registry.
- L467-469: rewrite the "SHALL remain loadable" requirement to key on the new
  path `yascheduler.entrypoints.aiida_plugin:YaScheduler`.
- L491-493 scenario "AiiDA plugin still loads": keep, reground to the new
  entry-point path.

**`testing-unit`** (1 reference, L141):

- L135-141 "Dependency injection factories" requirement: drop the bullet
  `make_aiida raises NotImplementedError`. Keep the other 3 bullets
  (`CLIDeps`, `make_cli_deps`, `make_daemon`).

**`dependency-injection`**: no `make_aiida` requirement exists (verified).
No delta.

### `ARCHITECTURE.md` — full refresh (not just aiida)

The file has drifted across several past changes; this change brings it
current. Per user instruction: "обновить нормально", not point edits.

- **§1 diagram**: redraw the top stack to show the PRESENTATION layer
  (`yascheduler.entrypoints`) with `client.py` and `aiida_plugin.py` as
  residents; show `shared/` as the bottom layer; Composition Root /
  outside-layer-set block holds `di.py`, `config/`, `daemon_*.py`, and the
  `client.py` shim. Drop the `make_aiida()` line from the Composition Root
  block. Drop the stale "ENTRY POINTS & LEGACY WRAPPERS" box (its contents
  are redistributed: real residents → entrypoints; shim → outside-set;
  daemon launchers → outside-set, deferred).
- **§2 Component Reference table**: fix `client.py` row (shim, not facade);
  fix `aiida_plugin.py` row (now `entrypoints/aiida_plugin.py`; uses SSH
  transport, does NOT use the `Yascheduler` client — the "uses Yascheduler
  client" claim was always factually wrong); `di.py` row drops `make_aiida`.
- **§2.8 Composition Root**: drop `make_aiida(config)` bullet.
- **§2.9 Public API & Legacy Wrappers**: rewrite — "Public API" lives in
  `entrypoints/client.py`; `client.py` at root is an explicit compat shim;
  `aiida_plugin.py` lives in `entrypoints/`. Drop the "uses Yascheduler
  client" claim.
- **§3.7 Public API Stability**: reground the AiiDA line to the new
  entry-point path; fix "class Yascheduler in `client.py` remains the public
  Python facade" → facade is `entrypoints/client.py`, shim re-exports.
- **§3.8 `class Yascheduler` (Public API)**: reground to
  `entrypoints/client.py` as the real home; `client.py` is the shim.
- **§4 Project Structure tree**: redraw — show `entrypoints/` subtree
  (containing `__init__.py`, `client.py`, `aiida_plugin.py`); `client.py` at
  root remains as shim; show `shared/` subtree; expand `infra/` one level
  (`persistence/`, `ssh/`, `cloud/`, `cli/`, `notifier/`) without files; drop
  `aiida_plugin.py` from root.
- **§6.2 `make_aiida()` implementation**: DELETE the whole subsection.
- **§6.3 `client.py` query methods via use cases**: DELETE (resolved).
- **§7 Open Questions table**: DELETE entirely (stale / cancelled per user).

### CHANGELOG.md

**Not touched.** Commitizen owns it via `update_changelog_on_bump`.

## Cross-module data flows

No new flows. `M-AIIDA` has `<depends>none</depends>` — it imports only
`aiida.*` and stdlib; it does NOT import the `Yascheduler` client (verified
via grep: zero `from yascheduler` / `import yascheduler` in the plugin). It
talks to yascheduler over SSH transport by shelling out to
`yasubmit` / `yastatus`. So the relocation is a pure file move + entrypoint
path swap with zero dependency-wiring consequences.

The deletion of `make_aiida` removes the only `M-DI → M-AIIDA` reference
(in the `LINKS` field and the `<fn-make_aiida>` annotation).

## Open questions

None remaining. All resolved during exploration:

- Shim or no shim → no shim.
- Test coverage gap → out of scope (no test expansion).
- ARCHITECTURE.md framing → full refresh.
- Stale `yascheduler.db` in outside-set lists → clean up in this change
  (we already edit those lines for aiida).
- `make_aiida` → delete.
- §6.2 / §6.3 / §7 → delete all three.
- §4 tree depth → directories only (no files) below top level; `infra/`
  one nested level.
- CHANGELOG → not touched.
- Change name → `relocate-aiida-plugin`, with `make_aiida` deletion in scope.