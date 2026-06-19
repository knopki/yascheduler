# Explore Brief: clean-architecture-imports

Working checklist for proposal/design/specs/tasks. Not a freezable artifact.

## Rejected alternatives (with reasons)

| Alternative                                              | Why rejected                                            |
| -------------------------------------------------------- | ------------------------------------------------------- |
| Public surface = "everything without `_`" (Variant A)     | `__init__.py` becomes a grab-bag (see `adapters/ssh/platform/__init__.py` 180 lines). Loses encapsulation. |
| Custom import-linter contract for R2 facade enforcement    | Linter's main job = layer direction. Custom contract is overkill for now. |
| `forbidden` contract with hardcoded module list (Дорога A) | Brittle — every new submodule needs a new line; easy to forget. |
| Move SSH exceptions into `domain/exceptions` directly (Variant a) | SSH-specific name in domain = semantic smell.         |
| **Make SSH exception tuples inherit from `RetryableOperationError` (Variant b)** | **Impossible.** `SFTPRetryExc`/`SSHRetryExc`/`AllSSHRetryExc` are tuples of third-party classes (asyncssh + stdlib). Cannot re-parent stdlib/asyncssh classes. Real usage is `backoff.on_exception(..., SFTPRetryExc)` which takes a tuple of types. |
| `abc.register` virtual subclassing (Variant D)            | Works but is magical — readers don't see why `except RetryableOperationError` catches asyncssh exceptions; static type checkers don't see the relationship. |
| `ignore_imports` exception in layers contract (Variant E) | Accepts the R3 violation as a documented wart. Defeats the purpose of this change. |
| Move all retry into gateway, drop application backoff (Variant F) | Cleanest architecturally but changes retry semantics (two-layer → one-layer). Out of scope for this change. |
| `import-linter >= 2.6`                                    | Requires Python 3.10+. Project pins `>=3.9`.           |
| Bump Python to 3.10+ in this change                       | Out of scope; separate decision.                       |
| Touch `db.py`                                              | Legacy, scheduled for deletion.                        |

## Final approach — full dimensions

### The three rules

| ID | Rule                                                       | Enforcement                |
| -- | ---------------------------------------------------------- | -------------------------- |
| R1 | Within-package imports use relative syntax (`from .foo`)    | Convention + spec          |
| R2 | Cross-package imports go through target's `__init__.py`     | Convention + spec          |
| R3 | Layer direction: adapters → application → domain (innermost) | HARD via import-linter     |

### Layer set (high → low)

1. `yascheduler.adapters` — highest
2. `yascheduler.application`
3. `yascheduler.domain` — lowest, depends on nothing in the project

### Outside layer set (NOT constrained by R3)

| Path                       | Reason                                              |
| -------------------------- | --------------------------------------------------- |
| `yascheduler.config`       | Shared infrastructure, imported by all layers       |
| `yascheduler.data`         | Shared infrastructure                                |
| `yascheduler.scheduler`    | Composition root                                     |
| `yascheduler.di`           | Composition root                                     |
| `yascheduler.client`       | Composition root, public entry point                |
| `yascheduler.db`           | Legacy, scheduled for deletion — DO NOT TOUCH       |
| `yascheduler.compat`       | Internal utility, not public                        |
| `yascheduler.aiida_plugin` | Separate stable entry point                         |

All composition root / top-level modules remain subject to **R2** (use facades).

### Public surface (Variant B: lazy, deliberate)

| Module                              | Public exports                                                                       |
| ----------------------------------- | ------------------------------------------------------------------------------------ |
| `yascheduler/__init__.py`           | `Yascheduler`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`, `__version__` (current — keep stable) |
| `yascheduler/aiida_plugin.py`       | AiiDA scheduler entrypoint (separate, stable)                                        |
| `yascheduler/client.py`             | Public client (stable)                                                               |
| `yascheduler/compat.py`             | Internal — NOT public                                                                |

Each subpackage `__init__.py` exposes only what external consumers actually need. Adding to public surface is a deliberate act, not automatic.

### Exception routing (Variant C) — DEFERRED to follow-up change

Variant C (gateway wraps operations and re-raises as `RetryableOperationError`) is the right design, but Round 2 review exposed that `gateway.get_sftp()` yields a **raw asyncssh `SFTPClient`** (`gateway.py:321-326`). Application code calls `sftp.get` / `sftp.makedirs` / `_write_remote_file(sftp, …)` directly on this raw client, and those raise asyncssh-specific exceptions that gateway-side translation cannot reach.

Properly implementing Variant C therefore requires also:
- Removing `get_sftp()` from the gateway's public surface.
- Adding higher-level wrapped SFTP methods (`download_files`, `upload_files`, `make_remote_dir`, …) with internal retry and reraise-as-`RetryableOperationError`.
- Updating 4+ call sites in `consume_task._sftp_download_job`, `orchestrator._upload_task_data`, `adapters/cli/check_status.py`, `orchestrator.py:282`.

That is a **gateway refactor**, not an **import hygiene** change. Scope creep. Decision: **defer to a separate follow-up change `gateway-sftp-wrapping`** (already scaffolded with explore-brief at `openspec/changes/gateway-sftp-wrapping/explore-brief.md`).

This change (`clean-architecture-imports`) ships the import-linter contract with the two known violations suppressed via `ignore_imports`. The follow-up change removes those entries.

### import-linter configuration

- Dependency: `import-linter >=2.5,<2.6` (Python 3.9 compatible).
- Location: `pyproject.toml` `[tool.importlinter]`.
- `root_package = "yascheduler"`.
- `exclude_type_checking_imports = true` (so existing TYPE_CHECKING imports in application are not flagged as R3 violations).
- Single `layers` contract:
  - `layers = ["yascheduler.adapters", "yascheduler.application", "yascheduler.domain"]`
  - `ignore_imports` (documented residual, removed by follow-up `gateway-sftp-wrapping`):
    - `"yascheduler.application.consume_task -> yascheduler.adapters.ssh.exceptions"`
    - `"yascheduler.application.orchestrator -> yascheduler.adapters.ssh.exceptions"`
- CI: `lint-imports` command, exit 0/1.

### `__init__.py` files to bring to standard

Currently empty (need deliberate facades):
- `yascheduler/application/__init__.py`
- `yascheduler/adapters/__init__.py`
- `yascheduler/adapters/notifier/__init__.py`
- `yascheduler/adapters/ssh/__init__.py`

Currently partial (extend):
- `yascheduler/domain/__init__.py` — currently only events; expose model + exceptions + ports.

Already non-empty and reasonable (audit only, no mandatory change):
- `yascheduler/config/__init__.py`
- `yascheduler/adapters/persistence/__init__.py`
- `yascheduler/adapters/cli/__init__.py` (note: uses absolute self-import — should switch to relative per R1)
- `yascheduler/adapters/cloud/__init__.py`
- `yascheduler/adapters/cloud/providers/__init__.py`

Out of scope (smell, but separate change):
- `yascheduler/adapters/ssh/platform/__init__.py` (180 lines, over-exported) — trim later.

### Existing R3 violations — DOCUMENTED RESIDUAL (deferred to gateway-sftp-wrapping)

Two existing edges violate R3 and are suppressed in the `layers` contract via `ignore_imports`:

- `yascheduler.application.consume_task ──→ yascheduler.adapters.ssh.exceptions` (`SFTPRetryExc`, used at `consume_task.py:35,105,151`).
- `yascheduler.application.orchestrator ──→ yascheduler.adapters.ssh.exceptions` (`AllSSHRetryExc`, used at `orchestrator.py:37,411`).

Proper fix requires gateway SFTP refactor — see `openspec/changes/gateway-sftp-wrapping/explore-brief.md`. Follow-up change will remove the `ignore_imports` entries.

## Key cross-module data flows (post-change)

```
   composition root (scheduler.py, di.py, client.py)
        │  uses facades only (R2)
        ▼
   ╔════════════════════════════════════╗
   ║   adapters/__init__.py             ║
   ║      │                             ║
   ║      ▼ uses facade                 ║
   ║   application/__init__.py          ║
   ║      │                             ║
   ║      ▼ uses facade                 ║
   ║   domain/__init__.py               ║
   ║   (Task, TaskCreated,              ║
   ║    DomainError tree,               ║
   ║    TaskRepository, NodeRepository, ║
   ║    MachineGateway, ...)            ║
   ╚════════════════════════════════════╝

   shared: config/, data/  ← imported by anyone, not in layer set
```

Two documented residual edges (post-change), suppressed via `ignore_imports` until follow-up `gateway-sftp-wrapping` lands:

```
   application/consume_task ──→ adapters.ssh.exceptions (SFTPRetryExc)
   application/orchestrator ──→ adapters.ssh.exceptions (AllSSHRetryExc)
```

Application still names the SSH tuple classes at these two sites; gateway SFTP refactor in the follow-up change will route them through a domain-level abstraction (`RetryableOperationError`) instead.

## Known open questions

1. **New capability name** — proposal will suggest `package-facades` (covers R1+R2+R3 holistically). Alternatives: `layered-imports`, `import-boundaries`. Decide in proposal.
2. **R1 enforcement** — convention only, or also via ruff `TID251` banned-api for specific patterns? Default: convention only.
3. **`adapters/cli/__init__.py` absolute self-import** — fix as part of this change (R1) or defer? Default: fix, it's trivial.
4. **`adapters/ssh/platform/__init__.py` 180-line over-export** — explicitly out of scope (smell, but pre-existing, separate change).
