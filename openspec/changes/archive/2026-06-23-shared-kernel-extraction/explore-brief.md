# Explore Brief: shared-kernel-extraction

Working checklist for proposal/design/specs/tasks. Not a freezable artifact.

## Rejected alternatives (with reasons)

| Alternative                                                | Why rejected                                                                                              |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Keep `time.py` / `queue.py` / `compat.py` at top-level     | Top-level of `yascheduler/` is the legacy accumulator: `client.py`, `db.py`, `daemon_*.py`, `webhook.py`, `aiida_plugin.py` plus utilities. No discipline. Mixing UTILITY with ENTRY_POINT and CORE_LOGIC. |
| Single `yascheduler/utils.py` file                          | Grab-bag; multiple unrelated utilities (`compat`, `to_sync`, `variables`) in one file. Anti-pattern.       |
| Shared kernel = `yascheduler/_internal/`                    | Leading underscore is a Python convention for private-to-the-package; shared kernel is not private — it's imported by all layers. Misleading name. |
| Put `to_sync` in `adapters/cli/` (move to the consumer)    | `to_sync` is consumed by `client.py` too (entry point), not just `adapters/cli/*`. One consumer-side placement would still leave entry point needing it. Cross-layer utility = shared kernel. |
| Put `to_sync` in `compat.py` (extend, no new module)       | `compat.py` is typing-only today. Mixing typing shims with runtime async-to-sync bridge muddies the module's purpose. Two different responsibilities. |
| Move `variables.py` to `config/` (treat as deployment cfg)| `config/` is parsed INI containers (`Config`, `ConfigDb`, ...). `variables.py` reads env vars for default paths — a different mechanism (env), different lifecycle (process-global constant). Forcing it into `config/` would require a fake "Config" wrapper. Rejected; keep in shared kernel as a runtime-constant module. |
| Move `time.py` and `queue.py` into shared kernel too        | Out of scope for THIS change per user instruction. Each has a single consumer (`application/orchestrator`); they should move INTO `application/` (private), not into shared kernel. Different change (`time-queue-application-move`). |
| Custom `import-linter` contract forbidding top-level imports of `compat`/`variables` | Overkill. The existing `layers` contract + the move itself + a simple rule "shared kernel imports go through `yascheduler.shared` facade (R2)" is enough. No new contract type needed. |
| Hard-enforce R2 on `yascheduler.shared` via `forbidden` contract | The existing `package-facades` spec says R1/R2 are convention + spec, only R3 is hard-enforced. Stays that way. Adding tooling enforcement is a separate decision. |

## Final approach — full dimensions

### Scope

**IN scope (this change):**
- `to_sync` → extract from `yascheduler/client.py` into `yascheduler/shared/async_utils.py`
- `compat.py` → move from `yascheduler/compat.py` to `yascheduler/shared/compat.py`
- `variables.py` → move from `yascheduler/variables.py` to `yascheduler/shared/variables.py`
- Create `yascheduler/shared/__init__.py` as the shared-kernel facade (lazy publication — re-export only what consumers need today)
- Update `pyproject.toml` `[tool.importlinter]`: add `yascheduler.shared` to the `layers` contract as a peer outside the adapter→app→domain chain (or document it as outside-layer-set, same as `config`/`data`/`compat`/`aiida_plugin` today)
- Update `openspec/specs/package-facades/spec.md`:
  - Replace outside-layer-set entries for `yascheduler.compat` with `yascheduler.shared.compat`
  - Add `yascheduler.shared` to the outside-layer-set list (shared infrastructure, imported by any layer)
  - Remove `yascheduler.client`-as-to_sync-source coupling (client no longer exports `to_sync`)
- Update GRACE-lite knowledge graph: remove `M-COMPAT`, `M-VARIABLES`, `fn-to_sync` from `M-CLIENT`; add `M-SHARED` with sub-annotations `fn-to_sync`, `type-Self`, `type-ParamSpec`, `const-CONFIG_FILE`, `const-PID_FILE`, `const-LOG_FILE`
- Update every consumer's import path (mechanical, ~15 files)
- Update tests that import from `yascheduler.compat` / `yascheduler.variables`

**OUT of scope (follow-up changes):**
- Moving `time.py` / `queue.py` into `application/` (different rationale: single consumer, should be private to the consumer layer, not shared kernel)
- Moving `webhook.py` (it's a domain value object, needs a separate analysis — possibly into `domain/`)
- Deleting `db.py` (legacy, already scheduled separately)
- Trimming `adapters/ssh/platform/__init__.py` (already a separate acknowledged smell)
- Backward-compat shims at old paths (`yascheduler/compat.py` re-exporting from new location) — explicit decision: NO compat shims, the modules are internal per existing `package-facades` spec ("`yascheduler.compat` SHALL remain internal (not public surface)")

### Shared kernel structure

```
yascheduler/shared/
  __init__.py        # facade — re-exports: Self, ParamSpec, to_sync, CONFIG_FILE, LOG_FILE, PID_FILE
  compat.py          # Self, ParamSpec — version-dependent typing imports
  async_utils.py     # to_sync — async-to-sync runtime bridge
  variables.py       # CONFIG_FILE, LOG_FILE, PID_FILE — env-derived path constants
```

Each file keeps its existing GRACE-lite MODULE_CONTRACT; only `path` and `LINKS` change.

### Facade contents (lazy publication)

`yascheduler/shared/__init__.py` re-exports exactly what consumers need today:

| Symbol        | Source                | Consumers (current importers)                                                                 |
| ------------- | --------------------- | --------------------------------------------------------------------------------------------- |
| `Self`        | `.compat`             | `config/{cloud,engine_repository,remote}`, `db`, `tests/unit/test_message_bus`                |
| `ParamSpec`   | `.compat`             | `client`                                                                                       |
| `to_sync`     | `.async_utils`        | `client`, `adapters/cli/{submit,daemonize,show_nodes,check_status,manage_node}`, tests        |
| `CONFIG_FILE` | `.variables`          | `__init__`, `client`, `adapters/cli/{submit,daemonize,show_nodes,init,check_status,manage_node}` |
| `PID_FILE`    | `.variables`          | `__init__`, `daemon_sysv`                                                                     |
| `LOG_FILE`    | `.variables`          | `__init__`, `daemon_systemd`, `daemon_sysv`                                                   |

### Import rule changes

- `yascheduler.shared` becomes a **new outside-layer-set module** (shared infrastructure like `config`, `data`).
- Any layer may import from `yascheduler.shared` (R3-exempt).
- R2 applies: cross-package imports go through `yascheduler.shared` facade (e.g., `from yascheduler.shared import Self, to_sync, CONFIG_FILE`), not through deep submodule paths (`from yascheduler.shared.compat import Self`).
- The existing `package-facades` spec lists `yascheduler.compat` as outside-layer-set; this change moves it to `yascheduler.shared.compat` and adds `yascheduler.shared` as the outside-layer-set umbrella.

### `import-linter` configuration change

Current `layers` contract:
```toml
layers = [
  "yascheduler.adapters",
  "yascheduler.application",
  "yascheduler.domain",
]
```

No change to the layer chain itself. `yascheduler.shared` is outside-layer-set (not in `layers` list) — same treatment as `yascheduler.config`, `yascheduler.data`, `yascheduler.di`, `yascheduler.client`, `yascheduler.compat`, `yascheduler.aiida_plugin` today.

The only `pyproject.toml` change: none to the `layers` contract itself (it stays the same). The outside-layer-set exemption lives in the `package-facades` spec prose, not in `import-linter` config (matches the existing convention).

### Public API stability

Per `package-facades` spec Requirement "Public API stability":
- `yascheduler/__init__.py` exports (`Yascheduler`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`, `__version__`) remain resolvable. `CONFIG_FILE`/`LOG_FILE`/`PID_FILE` will be re-exported via `yascheduler.shared.variables` (still re-exported from top-level `__init__.py` — no downstream-visible change).
- `yascheduler.compat` — explicitly internal per spec ("SHALL remain internal (not public surface)"). Path change is NOT a public API break.
- `yascheduler.client.to_sync` — currently not in any documented public API. `package-facades` spec lists `to_sync` as a private internal helper consumed by CLI adapters. No downstream consumer should be importing `to_sync` from `yascheduler.client`. The change is internal.

Decision: **No backward-compat shims.** Old paths (`yascheduler/compat.py`, `yascheduler/variables.py`) cease to exist. The `client.py` `to_sync` definition is removed. All consumers update in the same change. This matches the existing spec's stance that these are internal modules.

### Knowledge graph changes

Remove:
- `<M-COMPAT>` module entry (replaced by `M-SHARED-COMPAT` sub-annotation)
- `<M-VARIABLES>` module entry (replaced by `M-SHARED-VARIABLES` sub-annotation)
- `fn-to_sync` from `<M-CLIENT>` annotations
- `<CrossLink>` entries referencing `M-COMPAT` or `M-VARIABLES` if any

Add:
- `<M-SHARED>` module entry, `TYPE="UTILITY"`, `STATUS="implemented"`, `depends=none`, with sub-annotations:
  - `fn-to_sync` — async-to-sync decorator
  - `type-Self`, `type-ParamSpec` — typing shims
  - `const-CONFIG_FILE`, `const-PID_FILE`, `const-LOG_FILE` — path constants
- Update `M-MAIN` `<depends>`: `M-VARIABLES` → `M-SHARED`
- Update `M-CLIENT` `<depends>`: `M-VARIABLES, M-COMPAT` → `M-SHARED`; remove `fn-to_sync` annotation
- Update `M-DAEMON-SYSTEMD`, `M-DAEMON-SYSV`, `M-CLI-COMMANDS` `<depends>`: `M-VARIABLES` → `M-SHARED`
- Update `<CrossLink from="M-DOMAIN" to="M-DOMAIN-EVENTS" relation="re-exports event types from domain package" />` — no change needed (no reference to compat/variables)

## Key cross-module data flows (post-change)

```
   composition root (scheduler.py, di.py, client.py)
        │  uses facades only (R2)
        ▼
   yascheduler.shared/__init__.py   ← NEW shared kernel
   (Self, ParamSpec, to_sync,
    CONFIG_FILE, LOG_FILE, PID_FILE)
        ▲
        │ imported by any layer (outside-layer-set, R3-exempt)
        │
   ┌────┴─────┬──────────┬─────────────┬──────────┐
   │          │          │             │          │
 adapters   application  domain     config      cli/*

   (adapters → application → domain still enforced by R3 layers contract;
    yascheduler.shared sits alongside yascheduler.config as outside-layer-set)
```

## Known open questions

1. **Should `to_sync` go into `compat.py` or its own `async_utils.py`?** Default: own file. `compat.py` is typing-only; mixing with runtime code muddies the contract. Confirm in design.
2. **Should the shared kernel facade enforce a "no business logic" rule in spec?** Yes — mirror the `package-facades` spec's "Outside-layer-set exemptions" requirement, add a clause that `yascheduler.shared` SHALL NOT contain business logic, domain types, or I/O. Decision-level content for the delta spec.
3. **Should `yascheduler.shared` be added to the `layers` contract as a 4th outermost layer or stay outside the layer set entirely?** Default: outside the layer set (peer to `config`/`data`). Adding it as a layer would mean `adapters → application → domain → shared` which is wrong — shared is imported by `config`, which is itself outside-layer-set. Keep it outside. Confirm in design.
4. **`time.py` and `queue.py` follow-up** — out of scope here, but the design should note they are NOT moving into shared (single consumer → move into `application/` instead). Document as future work.