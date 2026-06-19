## 1. Dependencies & import-linter configuration

- [x] 1.1 Add `import-linter >=2.5,<2.6` to `[dependency-groups]` `dev` in `pyproject.toml` (PEP 735 — this project's existing convention, see `pyproject.toml:68`).
- [x] 1.2 Run `uv sync --all-extras --dev` to confirm the new dependency resolves at the pinned version.
- [x] 1.3 Add `[tool.importlinter]` section to `pyproject.toml`:
  - `root_package = "yascheduler"`
  - `exclude_type_checking_imports = true`
  - One `[[tool.importlinter.contracts]]` entry with:
    - `name = "Clean architecture layers"`
    - `type = "layers"`
    - `layers = ["yascheduler.adapters", "yascheduler.application", "yascheduler.domain"]`
    - `ignore_imports = ["yascheduler.application.consume_task -> yascheduler.adapters", "yascheduler.application.orchestrator -> yascheduler.adapters"]` *(path updated by task 8.7.4 from `… -> yascheduler.adapters.ssh` to `… -> yascheduler.adapters` layer facade; originally `… -> yascheduler.adapters.ssh.exceptions` pre-migration)*

## 2. Code changes — facades and __init__.py

- [x] 2.1 Extend `yascheduler/domain/__init__.py` to re-export:
  - Events (preserve existing re-exports — no regression).
  - Model: `Task` and related entities from `.model`.
  - Exceptions: the existing `DomainError` tree from `.exceptions` (no new symbols).
  - Ports: `TaskRepository`, `NodeRepository`, `MachineGateway`, `CloudProvisioner` from `.ports`.
- [x] 2.2 Update the file-local GRACE-lite metadata at the top of `yascheduler/domain/__init__.py`:
  - `START_MODULE_CONTRACT` PURPOSE and SCOPE: broaden to cover the expanded surface (events + model + exceptions + ports, not just events).
  - `START_MODULE_CONTRACT` DEPENDS: from `M-DOMAIN-EVENTS` to `M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-PORTS`.
  - `START_MODULE_MAP`: add entries for the newly re-exported symbols.
  - `START_CHANGE_SUMMARY`: add `LAST_CHANGE` entry referencing this change (`clean-architecture-imports`) and a one-line description of the extended facade.
- [x] 2.3 Normalize `yascheduler/adapters/cli/__init__.py` to use relative imports: replace `from yascheduler.adapters.cli.check_status import check_status` (and equivalent for `daemonize`, `init`, `manage_node`, `show_nodes`, `submit`) with `from .check_status import check_status`, etc.
- [x] 2.4 Update the file-local GRACE-lite metadata at the top of `yascheduler/adapters/cli/__init__.py`: broaden `START_MODULE_CONTRACT` PURPOSE/SCOPE if needed (likely no change — same symbols, just import style), and add `START_CHANGE_SUMMARY` `LAST_CHANGE` entry referencing this change and the relative-import normalization.
- [x] 2.5 Verify the four currently-empty facades need no code change:
  - `yascheduler/application/__init__.py`
  - `yascheduler/adapters/__init__.py`
  - `yascheduler/adapters/notifier/__init__.py`
  - `yascheduler/adapters/ssh/__init__.py`
  Confirm each remains a valid empty facade. No content change required.

## 3. GRACE-lite knowledge graph

- [x] 3.1 Update `docs/knowledge-graph.xml`: extend `<M-DOMAIN>` `<depends>` from `M-DOMAIN-EVENTS` to `M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-PORTS`. (These M-* entries already exist in the graph — only the `<depends>` list on M-DOMAIN changes.)
- [x] 3.2 Update the existing `<CrossLink from="M-DOMAIN" to="M-DOMAIN-EVENTS" relation="re-exports event types from domain package" />` (currently at `knowledge-graph.xml:783`): either broaden the `relation` text (e.g., "re-exports events, model, exceptions, ports from domain package") OR add three new CrossLinks `M-DOMAIN → M-DOMAIN-{MODEL,EXCEPTIONS,PORTS}` with appropriate relation prose.
- [x] 3.3 Run `python3 scripts/grace_check.py` — must exit 0. If it fails, fix XML or annotation issues before continuing.

## 4. Documentation

- [x] 4.1 Confirm `openspec/changes/clean-architecture-imports/specs/package-facades/spec.md` exists with the formal R1/R2/R3 rules, facade policy, layer contract configuration, residual-edge documentation, and outside-layer-set enumeration. (Created in Batch 3 — verification only.)
- [x] 4.2 Add a brief TRIGGER pointer to `AGENTS.md` near the existing rules section (around the "OpenSpec Rule" block at lines 36-55, alongside the existing four spec pointers). Suggested wording: "Import structure changes (new modules in `domain/`, `application/`, `adapters/`; new cross-package imports; new public symbols): consult `openspec/specs/package-facades` before editing." Keep it to one or two lines. Use the existing path style (no `/spec.md` suffix).
- [x] 4.3 Optional: add `# noqa` or comment near the two `ignore_imports` entries in `pyproject.toml` referencing the follow-up change `gateway-sftp-wrapping`, so future readers understand why the carve-outs exist.

## 5. CI integration

- [x] 5.1 Add a new step to `.github/workflows/lint.yml` after the existing step named `type check` (`uv run zuban check`), which is the last step today:
  ```yaml
  - name: import-linter
    run: uv run lint-imports
  ```

## 6. Verification (run all before opening PR)

- [x] 6.1 `uv run pytest -m unit` — unit tests pass (no behavior change expected; this is a regression guard).
- [x] 6.2 `uv run zuban check` — type checks pass.
- [x] 6.3 `uv run ruff check .` — lint clean.
- [x] 6.4 `uv run ruff format --check .` — format clean.
- [x] 6.5 `uv run lint-imports` — exit 0 (the layers contract is satisfied given the two documented `ignore_imports` entries).
- [x] 6.6 `openspec validate --all --json` — `clean-architecture-imports` reports `valid: true` with no issues.
- [x] 6.7 Smoke test: in a Python REPL or test, confirm `from yascheduler.domain import Task, TaskCreated, DomainError, TaskRepository, NodeRepository, MachineGateway, CloudProvisioner` resolves without `ImportError`.
- [x] 6.8 Confirm `from yascheduler import Yascheduler, CONFIG_FILE, LOG_FILE, PID_FILE, __version__` still resolves (public API unchanged).
- [x] 6.9 Confirm `yascheduler/db.py` was not modified (`git diff $(git merge-base HEAD main) -- yascheduler/db.py` returns nothing; adjust base ref if your branch model differs).

## 7. Out of scope (explicitly NOT done in this change)

- [x] 7.1 NOT touching `yascheduler/db.py` (legacy, scheduled for deletion).
- [x] 7.2 NOT trimming `yascheduler/adapters/ssh/platform/__init__.py` (180-line over-export; separate concern).
- [x] 7.3 NOT modifying `yascheduler/__init__.py`, `yascheduler/aiida_plugin.py`, `yascheduler/client.py`, `yascheduler/compat.py` (public API stable, internal utility).
- [x] 7.4 NOT fixing the two documented residual R3/R2 edges in `consume_task.py` and `orchestrator.py` (deferred to follow-up change `gateway-sftp-wrapping`).
- [x] 7.5 NOT bumping Python version above 3.9.
- [x] 7.6 NOT enforcing R1 or R2 with tooling (lint-imports enforces R3 only; R1/R2 are convention + spec).

## 8. Retroactive R1/R2 enforcement migration

Scope correction: the original task 7.6 ("R1/R2 NOT tooling-enforced") and the now-removed spec escape clause ("pre-existing R2 violations not retroactively required to be fixed") undermined the spec. This section reverses that — R1/R2 SHALL hold across the codebase, enforced by a new AST checker script. Discovered during post-implementation review.

### 8.1 Facade extensions (symbols currently consumed cross-package but not in target facade)

- [x] 8.1.1 `yascheduler/adapters/ssh/__init__.py`: re-export `SSHMachineGateway` (from `.gateway`), `AllSSHRetryExc` and `SFTPRetryExc` (from `.exceptions`). Add GRACE-lite MODULE_MAP entries + CHANGE_SUMMARY bump.
- [x] 8.1.2 `yascheduler/adapters/cloud/__init__.py`: re-export `CloudProvisionerImpl` (from `.manager`). GRACE-lite metadata update.
- [x] 8.1.3 `yascheduler/application/__init__.py`: re-export `AbstractUnitOfWork` (from `.uow`), `Orchestrator` (from `.orchestrator`), `MessageBus` (from `.message_bus`). GRACE-lite metadata update.
- [x] 8.1.4 `yascheduler/adapters/persistence/__init__.py`: re-export `apply_schema` (from `.postgres_schema`). GRACE-lite metadata update.

### 8.2 R1 conversions (absolute same-package imports → relative)

- [x] 8.2.1 `yascheduler/application/` (5 files: orchestrator, consume_task, deallocate_nodes, submit_task, allocate_task): `from yascheduler.application.uow import AbstractUnitOfWork` → `from .uow import AbstractUnitOfWork`.
- [x] 8.2.2 `yascheduler/adapters/cloud/manager.py`: `from yascheduler.adapters.cloud.adapters import CloudAdapter` → `from .adapters import CloudAdapter`; same for `.protocols`.
- [x] 8.2.3 `yascheduler/adapters/ssh/` (exceptions, helpers, gateway): convert absolute self-references inside the `ssh` package tree to relative (including subpackage references like `.platform.protocol`, `.platform.adapters`, `.platform.exceptions`).
- [x] 8.2.4 `yascheduler/daemon_sysv.py` and `yascheduler/daemon_systemd.py`: `from yascheduler import LOG_FILE, PID_FILE` → `from . import LOG_FILE, PID_FILE`; `from yascheduler.adapters.cli.daemonize import daemonize` → `from .adapters.cli import daemonize` (R2 via facade).

### 8.3 R2 conversions (cross-package deep-path → facade)

- [x] 8.3.1 `yascheduler/application/` (orchestrator, consume_task, allocate_task, deallocate_nodes, submit_task, uow, message_bus): convert all `from yascheduler.domain.{events,model,exceptions,ports} import X` → `from yascheduler.domain import X`. Convert `from yascheduler.adapters.cloud.manager import CloudProvisionerImpl` → `from yascheduler.adapters.cloud import CloudProvisionerImpl`. Convert `from yascheduler.adapters.ssh.gateway import SSHMachineGateway` (under TYPE_CHECKING) → `from yascheduler.adapters.ssh import SSHMachineGateway`. Update the 2 R3-residual edges from `… -> yascheduler.adapters.ssh.exceptions` → `… -> yascheduler.adapters.ssh` (now via facade).
- [x] 8.3.2 `yascheduler/adapters/cli/` (check_status, daemonize, init, manage_node, show_nodes, submit): convert all `from yascheduler.domain.model/exceptions/ports import X` → `from yascheduler.domain import X`; `from yascheduler.config import X` already facade-compliant (verify); `from yascheduler.adapters.ssh.gateway import SSHMachineGateway` → `from yascheduler.adapters.ssh import SSHMachineGateway`; `from yascheduler.adapters.persistence.postgres_schema import apply_schema` → `from yascheduler.adapters.persistence import apply_schema`; `from yascheduler.application.{uow,orchestrator} import X` → `from yascheduler.application import X`.
- [x] 8.3.3 `yascheduler/adapters/cloud/{manager,adapters}.py`: convert domain deep paths to facade; convert `from yascheduler.adapters.ssh.gateway import SSHMachineGateway` → `from yascheduler.adapters.ssh import SSHMachineGateway`.
- [x] 8.3.4 `yascheduler/adapters/persistence/{postgres_uow,postgres_schema}.py`: convert `from yascheduler.config.db import ConfigDb` → `from yascheduler.config import ConfigDb`; convert `from yascheduler.application.message_bus import MessageBus` → `from yascheduler.application import MessageBus`; convert domain deep paths to facade.
- [x] 8.3.5 `yascheduler/adapters/notifier/webhook.py`: convert domain deep paths to facade.
- [x] 8.3.6 `yascheduler/adapters/ssh/{gateway,platform/protocol,platform/windows,platform/linux}.py`: convert `from yascheduler.domain.model import X` → `from yascheduler.domain import X`; convert `from yascheduler.config.engine import X` → `from yascheduler.config import X`.

### 8.4 Enforcement approach — corrected

- [x] 8.4.1 ~~Write `scripts/check_imports.py` AST checker~~ **CANCELLED**: post-review feedback rejected the custom-tooling approach (script missed real issues: parent-traversal relative imports, cross-subpackage facade leaks). Enforcement is via R3 `import-linter` contract + code review + the spec's explicit R1/R2 rules. The script was deleted.
- [x] 8.4.2 ~~Add CI step for check_imports~~ **CANCELLED**: CI step removed when the script was deleted. The existing `import-linter` step (R3) remains.

### 8.5 Knowledge graph + spec reconciliation

- [x] 8.5.1 Update `docs/knowledge-graph.xml`: added new `<M-ADAPTERS>` layer-facade entry (aggregating ssh/cloud/persistence/notifier public surface); updated `<M-NOTIFIER>` with `export-webhook_handler`; added `export-get_rnd_name` to `<M-CLOUD>`; added `export-AzureImageReference` to `<M-CONFIG-HUB>`. Earlier-created `<M-APPLICATION>`, `<M-SSH>`, `<M-CLOUD>`, `<M-PERSISTENCE>` entries preserved.
- [x] 8.5.2 Update `pyproject.toml` `[tool.importlinter].contracts.layers.ignore_imports`: paths now point at `… -> yascheduler.adapters` (the layer facade), since the residual edges now resolve through the layer facade.

### 8.6 Correction — layer facade as the sole public surface (post-review feedback)

The original 8.1–8.3 work used subpackage facades (`yascheduler.adapters.ssh`, `yascheduler.adapters.cloud`, etc.) as the migration target. Reviewer correctly pointed out this still leaks internal structure across layers: cross-layer consumers must go through the LAYER facade (`yascheduler.adapters`), not subpackage facades. This section corrects that.

- [x] 8.6.1 Extend `yascheduler/adapters/__init__.py` as the adapters LAYER facade re-exporting `SSHMachineGateway`, `AllSSHRetryExc`, `SFTPRetryExc`, `CloudProvisionerImpl`, `apply_schema`, `webhook_handler` from `.ssh`/`.cloud`/`.persistence`/`.notifier`.
- [x] 8.6.2 Extend `yascheduler/adapters/notifier/__init__.py` to re-export `webhook_handler` (was empty).
- [x] 8.6.3 Extend `yascheduler/adapters/cloud/__init__.py` to add `get_rnd_name` (consumed by `providers/*`).
- [x] 8.6.4 Extend `yascheduler/config/__init__.py` to add `AzureImageReference` (consumed by `adapters.cloud.providers.az` under `TYPE_CHECKING`).
- [x] 8.6.5 Re-migrate all `application/*` consumers: `from yascheduler.adapters.{ssh,cloud} import X` → `from yascheduler.adapters import X`.
- [x] 8.6.6 Re-migrate all `adapters/cli/*` consumers: `from yascheduler.adapters.{ssh,persistence} import X` → `from yascheduler.adapters import X`.
- [x] 8.6.7 Re-migrate `adapters/cloud/manager.py`: `from yascheduler.adapters.ssh import SSHMachineGateway` → `from yascheduler.adapters import SSHMachineGateway`.
- [x] 8.6.8 Re-migrate `di.py`: `from .adapters.notifier.webhook import webhook_handler` → `from .adapters import webhook_handler`.
- [x] 8.6.9 Convert ALL parent-traversal relative imports (`from ..`, `from ...`, `from ....`) to absolute facade imports across the codebase:
  - `adapters/cloud/protocols.py`: `from ...config import ConfigCloud` → `from yascheduler.config import ConfigCloud`
  - `adapters/cloud/providers/{az,hetzner,upcloud,vastai}.py`: `from ..utils import get_rnd_name`, `from ..ssh_keys import get_key_name`, `from ..protocols import PCloudConfig`, `from ....config[.cloud] import X` → absolute facade (`from yascheduler.adapters.cloud import …`, `from yascheduler.config import …`)
  - `adapters/persistence/postgres.py`: `from ...domain.model import X` → `from yascheduler.domain import X`
  - `config/{cloud,engine_repository,remote}.py`: `from ..compat import Self` → `from yascheduler.compat import Self`
- [x] 8.6.10 Delete `scripts/check_imports.py` (unrequested tooling; reviewer flagged it as not catching real issues).
- [x] 8.6.11 Remove the `import-structure (R1/R2)` CI step from `.github/workflows/lint.yml`.

### 8.7 Spec reconciliation with corrected architecture

- [x] 8.7.1 R1 requirement: rewritten to forbid parent-traversal relative imports (`from ..`, `from ...`, `from ....`) anywhere in the `yascheduler` tree; only `from .` (single-level sibling) relative imports permitted.
- [x] 8.7.2 R2 requirement: rewritten to name the three LAYER facades (`yascheduler.adapters`, `yascheduler.application`, `yascheduler.domain`) as the sole public surface for cross-layer consumers; subpackage facades are internal organization, not cross-layer entry points.
- [x] 8.7.3 "Extended facade contents" requirement: rewritten to describe the layer facade contents (adapters exposes 6 symbols; application exposes 3; notifier/cloud/persistence/config extended).
- [x] 8.7.4 "Documented residual edges" path updated from `… -> yascheduler.adapters.ssh` to `… -> yascheduler.adapters` (layer facade).
- [x] 8.7.5 "Empty facade is valid" scenario generalized (no longer enumerates specific files).
- [x] 8.7.6 Removed the "R1 and R2 tooling enforcement" requirement (script deleted).

### 8.8 Final verification

- [x] 8.8.1 `uv run pytest -m unit` — 348 passed.
- [x] 8.8.2 `uv run ruff check .` / `ruff format --check .` — clean.
- [x] 8.8.3 `uv run zuban check` — clean (125 source files).
- [x] 8.8.4 `uv run lint-imports` — Clean architecture layers KEPT (R3 satisfied with updated `ignore_imports` paths pointing at layer facade).
- [x] 8.8.5 `python3 scripts/grace_check.py` — 0 errors (17 pre-existing warnings).
- [x] 8.8.6 `openspec validate --all --json` — 32/32 valid.
- [x] 8.8.7 Smoke: `from yascheduler.adapters import SSHMachineGateway, AllSSHRetryExc, SFTPRetryExc, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork` ; `from yascheduler.application import AbstractUnitOfWork, Orchestrator, MessageBus, submit_task` ; `from yascheduler.adapters.notifier import webhook_handler` ; `from yascheduler.adapters.cloud import get_rnd_name` ; `from yascheduler.config import AzureImageReference` — all resolve.
- [x] 8.8.8 No parent-traversal relative imports remain anywhere under `yascheduler/` (verified via grep).
- [x] 8.8.9 No cross-layer imports via subpackage facades remain (verified via grep; only deliberate `_resolve_adapter` private carve-out remains).
- [x] 8.8.10 Out-of-scope files untouched: `db.py`, `aiida_plugin.py`, `client.py`, `compat.py`, top `__init__.py`, `ssh/platform/{__init__,windows,linux}.py`.

### 8.9 Cycle-3 corrective work (from GRACE + code review)

- [x] 8.9.1 Add GRACE-lite metadata update to `yascheduler/config/__init__.py` (VERSION 1.7.0→1.8.0, SCOPE/MODULE_MAP/CHANGE_SUMMARY) for the `AzureImageReference` re-export added in 8.6.4.
- [x] 8.9.2 Fully migrate `yascheduler/di.py` to layer facades: `CloudProvisionerImpl`, `SSHMachineGateway`, `MessageBus`, `Orchestrator`, `submit_task`, all domain events now via `.adapters`/`.application`/`.domain`; only `_resolve_adapter` (private) remains on deep path.
- [x] 8.9.3 Fully migrate `yascheduler/scheduler.py` to layer facades: `CloudAdapter`, `CloudProvisionerImpl`, `Orchestrator`, `submit_task`, `SSHMachineGateway` now via `.adapters`/`.application`; only `_resolve_adapter` (private) remains on deep path.
- [x] 8.9.4 Extend `yascheduler/adapters/persistence/__init__.py` to re-export `PostgresUnitOfWork` (needed by composition root di.py via the adapters layer facade).
- [x] 8.9.5 Extend `yascheduler/application/__init__.py` to re-export `submit_task` (needed by composition root di.py/scheduler.py).
- [x] 8.9.6 Extend `yascheduler/adapters/__init__.py` layer facade to also re-export `CloudAdapter` and `PostgresUnitOfWork` (composition root consumers).
- [x] 8.9.7 Fix circular import in `yascheduler/adapters/persistence/postgres.py:29`: `from . import load_query` → `from .sql_loader import load_query` (the persistence facade re-exporting PostgresUnitOfWork made the package-init import cycle).
- [x] 8.9.8 Knowledge graph: reword M-SSH/M-CLOUD/M-PERSISTENCE purposes to clarify they are internal subpackage facades re-exported by M-ADAPTERS; change M-NOTIFIER TYPE=INTEGRATION → ENTRY_POINT; add CrossLinks M-ADAPTERS → M-SSH/M-CLOUD/M-PERSISTENCE/M-NOTIFIER; update M-APPLICATION purpose + add `export-submit_task`; add `export-PostgresUnitOfWork` to M-PERSISTENCE.
- [x] 8.9.9 Spec reconciliation: extend "Extended facade contents" enumeration to include `CloudAdapter`, `PostgresUnitOfWork`, `submit_task`; update smoke scenarios to "eight symbols"/"four symbols"; replace "No additional symbols are added" closing claim (now false) with accurate text.
- [x] 8.9.10 Add spec requirement "Documented private-symbol carve-outs" covering `_resolve_adapter` deep-path R2 carve-out.
- [x] 8.9.11 Add spec requirement "Broad ignore_imports tradeoff" documenting that `… -> yascheduler.adapters` is broader than the original deep path and reviewers must scrutinize new adapter imports in the two residual files.
- [x] 8.9.12 Add "superseded" notes to stale `ignore_imports` paths in `proposal.md` and `design.md` (frozen artifacts — declarative annotations only).
