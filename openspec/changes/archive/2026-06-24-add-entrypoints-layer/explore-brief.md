# Explore Brief — add-entrypoints-layer

## Goal

Introduce a new outermost hexagonal layer `yascheduler.entrypoints` (presentation / driving
adapters + composition root) and move the library client `yascheduler/client.py` into it.
Keep `di.py`, `aiida_plugin.py`, `daemon_*.py`, `infra/cli/` in place for follow-up changes.

## Rejected alternatives

- **Move `client.py` into `infra/api/`** — rejected: `infra/` is the driven-adapters layer
  (persistence, ssh, cloud, notifier); `client` is a *driving* adapter that calls use cases.
  Wrong ring.
- **Migrate all driving adapters + di in one change** — rejected: too large for a single
  proposal; `client.py` only now, rest in follow-ups.
- **Add `config` as a layer in the `layers` contract** — rejected: `config` stays an
  outside-layer-set peer utility; the existing `forbidden` contract `shared → config` is
  kept to prevent the import cycle (`config → shared` already exists).
- **Binding `from .entrypoints import client` in `__init__.py` only (no shim file)** —
  rejected experimentally: this creates an attribute `yascheduler.client` but does NOT
  register module `yascheduler.client` in `sys.modules`, so `from yascheduler.client
  import Yascheduler` raises `ModuleNotFoundError`. External downstream consumers using
  the deep path would break.
- **No compat shim, edit all call sites** — rejected: breaks the documented deep import
  path `from yascheduler.client import Yascheduler` for external consumers.

## Final approach

```
yascheduler/
  __init__.py              # from .entrypoints import Yascheduler
  client.py                # COMPAT SHIM: re-export Yascheduler from entrypoints.client
  entrypoints/             # NEW layer
    __init__.py            # facade: from .client import Yascheduler
    client.py              # real implementation (moved from yascheduler/client.py)
  aiida_plugin.py          # stays (interim)
  daemon_systemd.py        # stays (interim)
  daemon_sysv.py           # stays (interim)
  di.py                    # stays (interim)
  infra/  application/  config/  domain/  shared/   # unchanged
```

### Layer mapping (final)

```
entrypoints  →  infra  →  application  →  domain  →  shared
     (NEW)        (driven adapters)   (use cases)    (kernel)
```

`config` remains outside-layer-set (exempt); `forbidden: shared → config` retained.

### Cross-module data flow (unchanged by move)

- `yascheduler/__init__.py` → `yascheduler.entrypoints.__init__` → `yascheduler.entrypoints.client`
- `yascheduler.entrypoints.client.Yascheduler.__init__` → `Config.from_config_parser` (config layer),
  `make_cli_deps` (di, exempt), `to_sync` / `CONFIG_FILE` (shared)
- `yascheduler.entrypoints.client.Yascheduler.queue_submit_task_async` → `CLIDeps.submit`
  (di seam) → `submit_task` use case (application)
- `yascheduler.entrypoints.client.Yascheduler.queue_get_tasks_async` → `query_tasks` use
  case (application) → `AbstractUnitOfWork` (application port)
- Compat shim `yascheduler/client.py` → `yascheduler.entrypoints.client.Yascheduler`
  (single re-export, `__all__ = ["Yascheduler"]`)

### Import-form compatibility matrix (verified empirically, Python 3.13)

| Form                                                   | After change | Mechanism                          |
| ------------------------------------------------------ | ------------ | --------------------------------- |
| `from yascheduler import Yascheduler`                    | ✅ works    | `__init__.py` re-export           |
| `from yascheduler.client import Yascheduler`             | ✅ works    | shim file (real module in sys.modules) |
| `yascheduler.client.X` (attr)                            | ✅ works    | shim module attribute             |
| `import yascheduler.client`                              | ✅ works    | shim module                      |
| `patch("yascheduler.client.Config.from_config_parser")`  | ❌ breaks   | `Config` not re-exported by shim; tests patched onto the real module `yascheduler.entrypoints.client.Config` |

Test call sites that patch `yascheduler.client.Config…` (3 files) migrate to
`yascheduler.entrypoints.client.Config…`.

## Open questions (closed during explore)

- Q: Is `entrypoints` a good name given setuptools `[project.scripts]` overload?
  A: Yes — fixed in proposal prose: "`entrypoints/` = presentation layer (driving adapters
  + composition root); unrelated to setuptools `[project.scripts]`, which point into layers."
- Q: Full shim vs. no shim? A: Full shim (5c) — only form that preserves
  `from yascheduler.client import Yascheduler` for external consumers.
- Q: GRACE-lite contract on the shim? A: Yes, full normal `MODULE_CONTRACT` (no template
  shortcuts); PURPOSE states implementation lives in `entrypoints/client.py`.
- Q: R2 facade enforcement for tests? A: Not enforced; tests import any way they like.

## Knowledge-graph changes

- Rename `M-CLIENT` → `M-ENTRYPOINTS-CLIENT`; update `<path>` to
  `yascheduler/entrypoints/client.py`.
- Introduce `M-ENTRYPOINTS` layer-facade node (TYPE=ENTRY_POINT) for
  `yascheduler/entrypoints/__init__.py`, mirroring `M-ADAPTERS` / `M-APPLICATION`.
- Update `M-MAIN.depends`/`LINKS` to reference `M-ENTRYPOINTS-CLIENT` (via
  `M-ENTRYPOINTS` facade) instead of `M-CLIENT`.
- Remove the spurious `M-AIIDA.LINKS` reference to `M-CLIENT` (the plugin does not import the client; the link was always wrong); set `LINKS: none` in `aiida_plugin.py`.
- Add a node for the compat shim `yascheduler/client.py` (e.g. `M-CLIENT-SHIM`,
  TYPE=UTILITY, PURPOSE=compat re-export) or document it under `M-MAIN`.

## Spec scope

Full rewrite of affected requirements in `openspec/specs/package-facades/spec.md`:
- Layer direction (R3) — add `entrypoints` on top
- Outside-layer-set exemptions — reclassify `yascheduler.client` as compat shim (not
  composition root); drop stale `yascheduler.db` / `yascheduler.compat` /
  `yascheduler.variables` mentions
- Layers contract configuration — new `layers = [...]` with 5 entries
- Public API stability — decouple from file path; key on `from yascheduler import
  Yascheduler`
- `forbidden: shared → config` contract retained unchanged