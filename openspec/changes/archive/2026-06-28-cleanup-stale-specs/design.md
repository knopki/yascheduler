## Context

`openspec/specs/` drifted from the codebase through four recent migrations whose spec updates were incomplete:

1. `rename-adapters-to-infra` (2026-06-23) — renamed the `yascheduler.adapters` package to `yascheduler.infra`. The R3 layer-direction contract in `package-facades` was updated, but internal prose in several specs kept `adapters.cli.init`, `adapters.ssh.platform.*`, `adapters.cloud.providers.*`, `adapters.persistence.postgres_uow`, `adapters.notifier`.
2. `consolidate-daemon-entrypoints` (2026-06-25) — replaced `@to_sync`-decorated async CLI entry points with `def f(argv): asyncio.run(_f_async(argv))`. The `cli-commands` spec got a new requirement mandating `asyncio.run` (lines 45-53/91-94) but the per-command requirements (lines 109/536/1209/1246) still say `@to_sync`, creating an internal contradiction.
3. `decompose-ssh-gateway` (2026-06-27) — dissolved the `SSHMachineGateway` god-class into `SSHMachineRepository` + `SSHMachineOperations` (+ collaborators) and removed the `MachineGateway` Protocol from `domain/ports.py`. Six specs still reference `SSHMachineGateway` / `MachineGateway` as live types.
4. `session-based-machine-handle` (2026-06-28) — introduced `SSHMachineSession` and narrowed `MachineRepository`/`MachineOperations` to session-based signatures. Specs describing the old `ConnectedMachine`/`ip`-based signatures are stale.

Separately, three specs describe completed migrations as if they were live contracts (`cloud-wrapper`, `remote-machine-wrapper`, `no-attrs-dependency`), and three spec groups fragment one subsystem into over-detailed pieces (SSH trio, cloud-config trio, exception pair).

Constraints:
- This is a **specs-only change**. No `yascheduler/` code, no `tests/`, no `pyproject.toml`. Touching code would violate the "no proposal, no code edits" rule in the wrong direction — this proposal authorizes spec edits only.
- OpenSpec `validate --all --json` must pass after the change.
- GRACE-lite rule 3: `docs/knowledge-graph.xml` stays current with structure. The merged spec names require M-SSH / M-CLOUDCONFIG module-record updates (spec file references, not M-ID changes).
- Public interface stability (per `AGENTS.md`): the INI config format, DB schema, CLI commands, `class Yascheduler` API, AiiDA entrypoint are all unaffected — those contracts live in other specs and are not touched here.

## Goals / Non-Goals

**Goals:**
- Make `openspec/specs/` describe the code as it actually is today (post-4-migrations).
- Eliminate internal contradictions within specs (the `cli-commands` `@to_sync` vs `asyncio.run` case).
- Consolidate fragmented subsystem specs so one subsystem = one spec.
- Reduce total spec volume ~23% (8198 → ~6300 lines) without losing contract coverage.
- Keep `openspec validate --all --json` green.
- Keep `docs/knowledge-graph.xml` spec-file references current.

**Non-Goals:**
- Changing any `yascheduler/` Python code, tests, or `pyproject.toml`.
- Renaming any M-ID in the knowledge graph (only `<path>` / spec-reference fields change).
- Re-architecting the spec schema or OpenSpec conventions.
- Fixing every stylistic imperfection in every spec — only stale references, contradictions, and the named merges are in scope.
- Touching the four testing specs (`testing-unit`, `test-db-integration`, `e2e-testing`, `testing-infrastructure`) beyond the `SSHMachineGateway`/`RemoteMachineRepository` reference fixes in `testing-unit`. The testing-spec consolidation (suggested lower-priority in the audit) is deferred.
- Merging `cloud-providers` into `cloud-config` — it covers provider adapters (a different concern from config DTOs/parsers/Protocol).

## Decisions

### D1: Delete the 3 migration-completion specs outright

**Decision:** Remove `cloud-wrapper`, `remote-machine-wrapper`, `no-attrs-dependency` entirely.

**Rationale:** Each describes code that no longer exists as if the migration were a forward-looking contract. `cloud-wrapper` is 20 lines saying "use `CloudProvisionerImpl` directly" — the cloud-provisioner spec already says that. `remote-machine-wrapper` references `SSHMachineGateway` which is itself dissolved (double-stale). `no-attrs-dependency` is a regression canary; the test `tests/unit/test_no_attrs_dependency.py` is the authoritative guard and does not need a spec to exist.

**Alternative considered:** Keep `no-attrs-dependency` as a permanent "no attrs" rule. Rejected — the canary test enforces it; a spec restating "don't import attrs" adds no contract that the test doesn't already lock down, and keeping it means the spec must be maintained alongside the test for no behavioral gain.

### D2: Merge the SSH trio into `ssh-infrastructure` (not 3 specs, not 2)

**Decision:** Merge `ssh-gateway` + `ssh-machine-repository` + `ssh-machine-session` into one `ssh-infrastructure` spec with three sub-requirements: Repository, Session, Operations+collaborators.

**Rationale:** The three are one subsystem split across three files for historical reasons (the `decompose-ssh-gateway` change created `ssh-machine-repository` and `ssh-machine-session` as transitional scaffolding). A reader navigating SSH contracts currently bounces between three specs with duplicated `download_outputs` / `start_task_on_machine` text. One spec with clear sub-sections is navigable and de-duplicates the overlapping contracts.

**Alternative considered:** Keep 3 specs but de-duplicate. Rejected — the duplication is structural (operations contracts appear in both `ssh-gateway` and `ssh-machine-repository`); fixing it requires moving content between specs, which is the same effort as merging and leaves 3 thin specs that always travel together.

**Alternative considered:** Merge into 2 (repository+session vs operations). Rejected — session is operated on by operations; splitting them forces a cross-reference for every operations method signature.

**Transitional prose to drop:** `ssh-gateway`'s "The system SHALL NOT provide a single `SSHMachineGateway` class" and "The `MachineGateway` Protocol in `domain/ports.py` SHALL be removed" — these are facts about the completed migration, not forward-looking requirements. The merged spec states the current structure declaratively.

### D3: Merge the cloud-config trio into `cloud-config`

**Decision:** Merge `cloud-config-protocol` + `cloud-config-dtos` + `cloud-config-parsers` into one `cloud-config` spec with sub-requirements: Protocol, DTOs, parsers.

**Rationale:** All three describe one concern — how `[engine.*]` cloud config sections become typed objects. Protocol + 4 DTOs + parsers are <300 lines combined; three spec files for one parse pipeline is over-fragmentation.

**Alternative considered:** Also merge `cloud-providers`. Rejected (Non-Goal) — `cloud-providers` covers `az_create_node`/`hetzner_create_node`/`upcloud_create_node_sync` provider adapters, a different concern from config parsing.

### D4: Absorb the 2 persistence-exception specs into `domain-exceptions`

**Decision:** Move `uow-not-initialized-error` and `task-row-not-found-error` content into `domain-exceptions` as sub-requirements.

**Rationale:** Both are `RuntimeError` siblings in `yascheduler.infra.persistence.exceptions`. They are not domain exceptions (the `task-row-not-found-error` spec explicitly says so), but they belong with the exception hierarchy spec rather than standing alone as 34- and 38-line files. `domain-exceptions` is the natural home for "all exceptions the project defines."

**Alternative considered:** Merge into `postgres-uow` / `postgres-repositories` instead (where the exceptions are raised). Rejected — splitting the exception hierarchy across two persistence specs makes it harder to see the full `RuntimeError` sibling set; `domain-exceptions` already aggregates exceptions from multiple layers and is the established home.

### D5: Fix stale references in-place (no merge) for the 11 modified specs

**Decision:** For `orchestrator`, `use-cases`, `cli-commands`, `cloud-provisioner`, `testing-unit`, `package-facades`, `domain-exceptions`, `cloud-providers`, `platform-adapters`, `dependency-injection`, `config-parser-assembly`, `domain-ports` — apply targeted text substitutions, do not restructure.

**Rationale:** These specs' structure is sound; only specific symbols/paths are stale. A targeted find-and-replace is the minimal change (per `AGENTS.md` "Prefer minimal changes over broad refactors") and preserves the spec logic.

**Substitution table (authoritative — implementer follows this verbatim):**

| Find | Replace | Specs |
| --- | --- | --- |
| `SSHMachineGateway` (class) | `SSHMachineRepository` (collection context) or `SSHMachineOperations` (operations context) or `SSHMachineSession` (per-machine handle context) — disambiguate by reading the surrounding requirement | `orchestrator`, `use-cases`, `cli-commands`, `cloud-provisioner`, `testing-unit` |
| `MachineGateway` (Protocol) | `MachineRepository` + `MachineOperations` (and `MachineSession` where the handle is meant) | `orchestrator`, `use-cases`, `cli-commands` |
| `gateway: MachineGateway` (param) | `repository: MachineRepository, operations: MachineOperations` (split param) | `orchestrator`, `use-cases` |
| `gateway.disconnect_all()` | `repository.disconnect_all()` | `cloud-provisioner` |
| `adapters.cli.init` | `entrypoints.cli.init` | `package-facades` |
| `adapters.cli.manage_node` | `entrypoints.cli.manage_node` | `package-facades` |
| `adapters.cli.daemonize` | `entrypoints.cli.daemonize` | `package-facades` |
| `adapters.persistence.postgres_uow` | `infra.persistence.postgres_uow` | `package-facades` |
| `adapters.notifier` | `infra.notifier` | `package-facades` |
| `adapters.cloud.adapters` | `infra.cloud.adapters` | `package-facades` |
| `adapters.cloud.manager` | `infra.cloud.manager` | `cloud-wrapper` (deleted with spec), `cloud-provisioner` |
| `adapters.ssh.gateway` | `infra.ssh` (facade) | `remote-machine-wrapper` (deleted with spec) |
| `adapters.cloud.providers.az` / `.hetzner` / `.upcloud` | `infra.cloud.providers.az` / `.hetzner` / `.upcloud` | `cloud-providers` |
| `adapters.ssh.platform.adapters` / `.checks` / `.linux` | `infra.ssh.platform.adapters` / `.checks` / `.linux` | `platform-adapters` |
| `adapters.cloud does not re-export CloudError` / `adapters.cloud still re-exports` | `infra.cloud does not re-export CloudError` / `infra.cloud still re-exports` | `domain-exceptions` |
| `from .adapters.cloud.adapters import _resolve_adapter` (example) | `from .infra.cloud.adapters import _resolve_adapter` | `package-facades` |
| `async function decorated with @to_sync` (per-command requirements) | `synchronous def that calls asyncio.run(_f_async(argv))` | `cli-commands` lines ~109/536/1209/1246 |
| `RemoteMachineRepository` (historical name-drop) | drop the clause or rephrase to current symbols | `use-cases` line ~133, `testing-unit` line ~282, `dependency-injection` line ~63 |
| `DB` (class name-drop in `make_daemon` scenario) | `the unit-of-work factory` or drop the clause | `dependency-injection` line ~63 |
| `ssh-machine-repository` capability (cross-ref) | `ssh-infrastructure` capability | `domain-ports` lines 81/83 |
| `ssh-machine-session` capability (cross-ref) | `ssh-infrastructure` capability | `domain-ports` line 83 |
| `cloud-config-dtos` capability (cross-ref) | `cloud-config` capability | `config-parser-assembly` line 59 |

### D6: Remove the `utils.py preserves re-exports` requirement from `cli-commands`

**Decision:** Delete the entire requirement block "utils.py preserves re-exports" and its two scenarios from `cli-commands`.

**Rationale:** `yascheduler/utils.py` does not exist. The requirement describes a re-export shim that was removed. Keeping it would leave a spec requirement with no implementation, which is the same defect as the stale-reference specs.

### D7: Update `docs/knowledge-graph.xml` spec-file references only

**Decision:** In `docs/knowledge-graph.xml`, update the `<path>` (or equivalent spec-reference field) for M-SSH and M-CLOUDCONFIG module records to point at the merged spec files. Do NOT rename any M-ID, do NOT change `<depends>`, do NOT add/remove `<CrossLink>` entries.

**Rationale:** GRACE-lite rule 3 requires the graph to stay current with structure. The merge changes which spec file documents a subsystem; the module identity (M-SSH, M-CLOUDCONFIG) and dependencies are unchanged. This is a one-line `<path>` edit per affected module record.

## Risks / Trade-offs

- **[Risk: cross-reference breakage]** Other specs or archived changes may link to the deleted/merged spec names. → **Mitigation:** The `grep` in D5 already enumerated all live cross-references (`domain-ports`→`ssh-machine-repository`/`ssh-machine-session`, `config-parser-assembly`→`cloud-config-dtos`). Archived changes under `openspec/changes/archive/` are frozen historical records and are NOT updated (they document the state at archive time). The implementer re-runs `grep -rn "<old-name>" openspec/specs/` after each batch to catch any missed reference.
- **[Risk: merge loses a contract]** Consolidating three SSH specs into one could drop a scenario in the process. → **Mitigation:** The merge is content-preserving: every requirement and scenario from the three source specs is copied into the merged spec's sub-requirements, then de-duplicated (overlapping `download_outputs`/`start_task_on_machine` text is kept once). The implementer diffs the merged spec line-count against the sum of the three originals as a sanity check (merged should be ~80-90% of the sum after de-dup + transitional-prose removal).
- **[Risk: `SSHMachineGateway` disambiguation is ambiguous]** The substitution table says "disambiguate by reading the surrounding requirement." → **Mitigation:** The surrounding context is almost always clear: collection operations (`connect`/`disconnect`/`list_free`/`disconnect_all`) → `SSHMachineRepository`; per-machine operations (`start_task_on_machine`/`download_outputs`/`occupancy_check`/`run`/`get_cpu_cores`) → `SSHMachineOperations` or `SSHMachineSession`; per-machine identity (`ip`/`machine`/`is_closed`/`occupy`/`release`) → `SSHMachineSession`. Where a `gateway:` parameter is passed to a use case, it becomes `repository:` + `operations:` (two params). The implementer runs `uv run python -c "import yascheduler.infra as i; print([s for s in dir(i) if 'Machine' in s])"` to confirm the live symbols at edit time.
- **[Risk: validator passes but semantic drift remains]** `openspec validate` checks structure, not semantic accuracy. → **Mitigation:** The substitution table is the semantic source of truth; the implementer verifies a sample of edits by reading the surrounding spec prose against the corresponding `yascheduler/` source (e.g. `orchestrator.py:104-105` for the `repository`/`operations` split).
- **[Trade-off: BREAKING for spec consumers]** Anyone with a deep link to `ssh-machine-repository/spec.md` breaks. → **Mitigation:** Git history preserves the originals; the change is reversible. The BREAKING markers in the proposal signal this clearly. No external system consumes these spec paths.

## Migration Plan

This is a docs-only change; there is no runtime migration. The implementation order is task-batched in `tasks.md` to keep each step verifiable:

1. **Batch 1 — Delete 3 specs.** Remove the 3 directories. Re-run `openspec validate --all --json` (expect failures from dangling cross-refs — fixed in later batches).
2. **Batch 2 — Create 2 new merged specs.** Write `ssh-infrastructure/spec.md` and `cloud-config/spec.md` by consolidating the source specs per D2/D3. Delete the 5 source spec directories (`ssh-gateway`, `ssh-machine-repository`, `ssh-machine-session`, `cloud-config-dtos`, `cloud-config-parsers`, `cloud-config-protocol`).
3. **Batch 3 — Absorb 2 exception specs into `domain-exceptions`.** Delete the 2 source directories.
4. **Batch 4 — Apply the D5 substitution table to the 12 modified specs.** One edit per row; re-run `grep` after each spec to confirm no residual stale symbol.
5. **Batch 5 — Apply D6 (remove `utils.py` requirement from `cli-commands`).**
6. **Batch 6 — Update `docs/knowledge-graph.xml` per D7.** Re-run `python3 scripts/grace_check.py`.
7. **Batch 7 — Validation.** `openspec validate --all --json` (exit 0, all valid), `python3 scripts/grace_check.py` (exit 0).

**Rollback:** `git revert` the change commit. No partial-rollback path needed — the change is atomic (all batches land in one commit).

## Open Questions

None. All decisions are settled by the audit findings and the substitution table. The implementer does not make architectural choices, only applies the table.