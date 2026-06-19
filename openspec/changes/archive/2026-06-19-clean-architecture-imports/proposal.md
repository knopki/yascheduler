## Why

Cross-layer imports in `yascheduler/` mostly bypass package `__init__.py`
files: `from yascheduler.domain.model import Task` is the dominant pattern
today, not `from yascheduler.domain import Task`. This makes each layer's
public surface implicit, hides the dependency direction, and lets violations
slip in. The OpenSpec specs already encode a layered architecture
(`domain-ports`, `domain-services`, `use-cases`), but nothing enforces it.
This change adds the import hygiene that makes the existing layered
architecture enforceable instead of convention-only, and establishes package
`__init__.py` files as the deliberate public surface of each subpackage.

## What Changes

- Formalize three import rules for the `yascheduler` package:
  - **R1** — within a package, imports use relative syntax (`from .foo import Bar`).
  - **R2** — across packages, imports go through the target package's `__init__.py` facade. Applies to composition-root modules (`scheduler.py`, `di.py`, `client.py`) and shared infrastructure (`config/`, `data/`) too, even though they are exempt from R3.
  - **R3** — layer direction is `adapters → application → domain` (domain depends on nothing in the project). Enforced hard via `import-linter`.

- Establish **package facades** as the only public surface of each subpackage. Public symbols are added to `__init__.py` lazily — only when an external consumer actually needs them. Four currently-empty facades are acknowledged as the official surface and may stay empty until a symbol needs publishing:
  - `yascheduler/application/__init__.py`
  - `yascheduler/adapters/__init__.py`
  - `yascheduler/adapters/notifier/__init__.py`
  - `yascheduler/adapters/ssh/__init__.py`

- Extend `yascheduler/domain/__init__.py` to expose model, exceptions (the existing `DomainError` tree — no new symbols), and ports (today only events are re-exported).

- Normalize `yascheduler/adapters/cli/__init__.py` to use relative imports per R1 (currently uses absolute self-references like `from yascheduler.adapters.cli.check_status import check_status`).

- Add `import-linter >=2.5,<2.6` as a dev dependency (pinned for Python `>=3.9`; versions `>=2.6` require Python 3.10+).

- Configure a single `layers` contract in `pyproject.toml` `[tool.importlinter]` enforcing R3, with:
  - `root_package = "yascheduler"`
  - `exclude_type_checking_imports = true` (so existing `TYPE_CHECKING`-guarded imports in `application/` are not flagged)
  - `ignore_imports` listing two existing R3 violations as **documented residual** (see "Out of scope" below):
    - `"yascheduler.application.consume_task -> yascheduler.adapters.ssh.exceptions"` *(superseded post-migration: path is now `… -> yascheduler.adapters` — the layer facade; see spec § Documented residual edges)*
    - `"yascheduler.application.orchestrator -> yascheduler.adapters.ssh.exceptions"` *(superseded post-migration: path is now `… -> yascheduler.adapters` — the layer facade)*

- Document the rules in a new spec capability and add a brief TRIGGER pointer in `AGENTS.md` referring to that spec.

## Capabilities

### New Capabilities

- `package-facades` (chosen over `layered-imports` / `import-boundaries` because the facade is the central concept that ties R1+R2+R3 together — not just layering): Formal rules for import direction (R1 relative within package, R2 through target `__init__.py` facade, R3 layer direction `adapters → application → domain`), the lazy public-surface policy for `yascheduler` subpackages, the outside-layer-set exemptions (`config/`, `data/`, composition root, `db.py` legacy, `compat.py` internal, `aiida_plugin.py` stable entry point), the `import-linter` configuration that hard-enforces R3, and the two `ignore_imports` residual edges.

## Impact

- **Dependencies**: new dev dependency `import-linter >=2.5,<2.6`.
- **Code**:
  - `pyproject.toml` — `[tool.importlinter]` section (`root_package`, `exclude_type_checking_imports`, single `layers` contract with two `ignore_imports` entries) and dev dependency.
  - `yascheduler/domain/__init__.py` — extended facade (model, exceptions, ports).
  - `yascheduler/adapters/cli/__init__.py` — switch to relative imports.
  - `yascheduler/application/__init__.py`, `yascheduler/adapters/__init__.py`, `yascheduler/adapters/notifier/__init__.py`, `yascheduler/adapters/ssh/__init__.py` — confirmed as official facades (no content change required unless a symbol needs publishing; this is a scope/documentation act).
  - `AGENTS.md` — brief TRIGGER pointer to the new spec.
  - `openspec/specs/package-facades/spec.md` — new capability spec formalizing R1/R2/R3, public-surface policy, outside-layer-set exemptions, and the `ignore_imports` residual edges.
- **Public API**: no breaking changes. `yascheduler/__init__.py`, `aiida_plugin.py`, `client.py` remain unchanged. `compat.py` remains internal (not public surface).
- **CI**: new `lint-imports` check in the static-checks workflow.
- **Out of scope**:
  - `yascheduler/db.py` (legacy, scheduled for deletion — explicitly not touched).
  - Trimming `yascheduler/adapters/ssh/platform/__init__.py` (180-line over-export; separate change).
  - Python version bump (separate decision).
  - Enforcement of R1 and R2 beyond documentation (linter's only hard job is R3).
  - **Properly fixing the two R3 residual edges** (`consume_task → adapters.ssh.exceptions`, `orchestrator → adapters.ssh.exceptions`). These require gateway SFTP refactor (the gateway's `get_sftp()` leaks a raw asyncssh `SFTPClient`, so gateway-side exception translation cannot reach SFTP call sites). Deferred to follow-up change `gateway-sftp-wrapping` (already scaffolded at `openspec/changes/gateway-sftp-wrapping/` with explore-brief capturing the design). Until then, the two edges are suppressed in the `layers` contract via `ignore_imports` as documented residual.
