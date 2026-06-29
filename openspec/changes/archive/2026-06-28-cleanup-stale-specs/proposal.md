## Why

`openspec/specs/` accumulated drift after the `decompose-ssh-gateway` and `session-based-machine-handle` migrations (2026-06-27/28) plus earlier `rename-adapters-to-infra` (2026-06-23) and `consolidate-daemon-entrypoints` (2026-06-25). 43 specs, 8198 lines: ~7 specs describe removed symbols (`SSHMachineGateway`, `MachineGateway` Protocol, `adapters.*`, `RemoteMachineRepository`, `DB`, `utils.py`, `clouds/`, `remote_machine/`), 3 specs document completed migrations as if they were live contracts, and 3 spec groups fragment one subsystem into over-detailed pieces. Specs lie about the code; readers navigate by stale coordinates.

## What Changes

**Remove (descriptions of non-existent code):**
- **BREAKING** Delete `cloud-wrapper` spec — `clouds/` package removed.
- **BREAKING** Delete `remote-machine-wrapper` spec — `remote_machine/` removed; also references dissolved `SSHMachineGateway`.
- **BREAKING** Delete `no-attrs-dependency` spec — `attrs` migration complete; the canary test `tests/unit/test_no_attrs_dependency.py` is the authoritative guard and needs no spec.

**Fix stale references (specs stay, content corrected):**
- Replace `SSHMachineGateway` / `MachineGateway` Protocol references with `SSHMachineRepository` + `SSHMachineOperations` (+ `MachineSession` where per-machine handle is meant) in: `orchestrator`, `use-cases`, `cli-commands`, `cloud-provisioner`, `testing-unit`.
- Replace `adapters.*` layer paths with `infra.*` in: `cloud-providers`, `platform-adapters`, `package-facades`, `domain-exceptions`, `cli-commands`.
- Remove the `utils.py preserves re-exports` requirement from `cli-commands` — `yascheduler/utils.py` no longer exists.
- Fix `@to_sync` → `asyncio.run(_f_async(argv))` wording in `cli-commands` (`submit`, `show_nodes`, `manage_node`, `check_status`); resolve the internal contradiction between the requirement at lines 45-53/91-94 (correct) and the per-command requirements at 109/536/1209/1246 (stale `@to_sync`).
- Drop historical `RemoteMachineRepository` / `DB` class name-drops from `use-cases`, `testing-unit`, `dependency-injection`.

**Merge (consolidate fragmented subsystems):**
- **BREAKING** Merge `ssh-gateway` + `ssh-machine-repository` + `ssh-machine-session` → new `ssh-infrastructure` spec. Drop `ssh-gateway` god-class-dissolution transitional prose (`SHALL NOT provide a single SSHMachineGateway class` is a fact, not a requirement). De-duplicate `download_outputs` / `start_task_on_machine` contracts.
- **BREAKING** Merge `cloud-config-dtos` + `cloud-config-parsers` + `cloud-config-protocol` → new `cloud-config` spec (`cloud-providers` stays separate — it covers provider adapters, not config).
- Merge `uow-not-initialized-error` + `task-row-not-found-error` into `domain-exceptions` as sub-sections (both are `RuntimeError` siblings; one place for the exception hierarchy).

Net: 43 → 34 specs, ~8200 → ~6300 lines (~23% reduction). No code changes — this is a specs-only cleanup. No runtime behavior, CLI, DB schema, or public API impact.

## Capabilities

### New Capabilities
- `ssh-infrastructure`: merged SSH adapter contract — `SSHMachineRepository` (collection lifecycle/queries), `SSHMachineSession` (per-machine handle), `SSHMachineOperations` (operations + collaborators `TaskDeployer`/`OutputDownloader`/`OccupancyChecker`). Replaces the `ssh-gateway`/`ssh-machine-repository`/`ssh-machine-session` trio.
- `cloud-config`: merged cloud config contract — `CloudConfig` Protocol + 4 DTOs + `[engine.*]` parsers. Replaces `cloud-config-dtos`/`cloud-config-parsers`/`cloud-config-protocol`.

### Modified Capabilities
- `orchestrator`: replace `gateway: MachineGateway` with `repository: MachineRepository` + `operations: MachineOperations` in the `Orchestrator.__init__` requirement and scenarios.
- `use-cases`: replace `gateway: MachineGateway` params in `allocate_task`/`consume_task` with `repository`/`operations`; drop `RemoteMachineRepository` historical reference.
- `cli-commands`: fix `SSHMachineGateway`→`SSHMachineRepository`/`SSHMachineOperations`/`MachineSession` in `yasetnode`/`yastatus -v`; fix `@to_sync`→`asyncio.run`; remove `utils.py preserves re-exports` requirement; fix `adapters.cli.commands`→`entrypoints.cli`.
- `cloud-provisioner`: replace `SSHMachineGateway.disconnect_all` with `SSHMachineRepository.disconnect_all`.
- `testing-unit`: replace `SSHMachineGateway` and `RemoteMachineRepository.filter` references with current symbols.
- `package-facades`: replace `adapters.*` internal references with `infra.*`; update `adapters.cli.init`/`adapters.persistence.postgres_uow`/`adapters.notifier`/`adapters.cloud.adapters` to `entrypoints.cli.init`/`infra.persistence.postgres_uow`/`infra.notifier`/`infra.cloud.adapters`; fix the `yascheduler/di.py: from .adapters.cloud.adapters import _resolve_adapter` example to `infra`.
- `domain-exceptions`: absorb `uow-not-initialized-error` and `task-row-not-found-error` content as sub-requirements; fix `adapters.cloud`→`infra.cloud` re-export scenarios.
- `cloud-providers`: fix `adapters.cloud.providers.*`→`infra.cloud.providers.*` import scenarios.
- `platform-adapters`: fix `adapters.ssh.platform.*`→`infra.ssh.platform.*` import scenarios.
- `dependency-injection`: drop `DB`/`RemoteMachineRepository` name-drops from the `make_daemon` scenario prose.
- `config-parser-assembly`: repoint the `cloud-config-dtos` capability reference at line 59 to `cloud-config` (the merged capability name).
- `domain-ports`: repoint the `ssh-machine-repository` and `ssh-machine-session` capability references at lines 81/83 to `ssh-infrastructure` (the merged capability name).

### Removed Capabilities
- `cloud-wrapper`: deleted — `clouds/` package removed; no live contract.
- `remote-machine-wrapper`: deleted — `remote_machine/` removed; no live contract.
- `no-attrs-dependency`: deleted — migration complete; canary test is the guard.
- `ssh-gateway`: merged into `ssh-infrastructure`.
- `ssh-machine-repository`: merged into `ssh-infrastructure`.
- `ssh-machine-session`: merged into `ssh-infrastructure`.
- `cloud-config-dtos`: merged into `cloud-config`.
- `cloud-config-parsers`: merged into `cloud-config`.
- `cloud-config-protocol`: merged into `cloud-config`.
- `uow-not-initialized-error`: merged into `domain-exceptions`.
- `task-row-not-found-error`: merged into `domain-exceptions`.

## Impact

- **Code:** None. Specs-only change. No `yascheduler/` files touched.
- **Tests:** None. The `test_no_attrs_dependency.py` canary stays as the guard (its rationale previously lived in the deleted spec).
- **Docs/knowledge graph:** `docs/knowledge-graph.xml` M-SSH / M-CLOUDCONFIG module records updated to reflect the merged spec names (per GRACE-lite rule 3: graph stays current with structure). No M-IDs removed — only spec file references.
- **OpenSpec validation:** `openspec validate --all --json` must pass after the merge. Cross-references to deleted/merged spec names must be repointed: `domain-ports` lines 81/83 reference `ssh-machine-repository`/`ssh-machine-session` → `ssh-infrastructure`; `config-parser-assembly` line 59 references `cloud-config-dtos` → `cloud-config`.
- **Risk:** Low. Spec consumers are humans + the OpenSpec validator. Stale references are already misleading; this change reduces drift. The merge is reversible (git history preserves the originals).