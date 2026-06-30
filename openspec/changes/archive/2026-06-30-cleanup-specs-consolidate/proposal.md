## Why

`openspec/specs/` (35 specs, ~7640 lines) accumulated three classes of noise after the
recent architecture migrations (`decompose-ssh-gateway`, `session-based-machine-handle`,
`resolve-type-bridge-debt`, `engine-to-domain-frozen`, config-relocation series) plus the
`2026-06-28-cleanup-stale-specs` pass that did not reach all of it:

1. **Active contradictions** — specs assert things the code no longer matches: a
   `capacity()` method declared "removed" yet still scenario-tested in `domain-ports`;
   an entire `ConfigLocal` requirement block in `ssh-keys-loading` referencing the
   deleted `yascheduler.config` package; old class names (`ConfigDb`, `ConfigRemote`)
   in `postgres-schema-apply`/`postgres-uow`/`cloud-config`; a stale implementation
   path (`yascheduler/client.py` shim) in `testing-unit`.
2. **Migration residue** — 7 specs still describe completed migrations as live
   contracts: "replacing the former `gateway: MachineGateway`", "`machine_gateway`
   attribute is renamed", "relocated from `yascheduler.config.cloud`",
   "resolve-type-bridge-debt D1", ~20 "X SHALL NO LONGER be re-exported" blocks in
   `package-facades`, defensive scenarios of the form "the removed symbol is still
   removed". Once a migration is done the spec should assert what IS, not keep
   documenting what WAS removed.
3. **Fragmentation + bloat** — three config value-object specs that describe one
   concern; a 1482-line `cli-commands` with the 0/1/2 exit-code contract repeated
   verbatim per command; `testing-infrastructure` overlapping `testing-unit`;
   a 41-line `allocation-tracker` tightly coupled to `use-cases`.

Readers navigate by stale coordinates; the validator passes because it checks
structure, not semantics.

## What Changes

**Fix active defects (specs stay, content corrected):**
- `domain-ports`: delete the "Report capacity" scenario that tests the method the
  same requirement declares removed; keep `select_provider` only.
- `ssh-keys-loading`: delete the "ConfigLocal migrated to stdlib dataclass"
  requirement (describes removed `ConfigLocal` + deleted `yascheduler.config`);
  rename surviving `ConfigLocal` → `LocalSettings`.
- `testing-unit`: fix `yascheduler/client.py` (now a shim) → `entrypoints/client.py`
  as the implementation location.
- `postgres-schema-apply`, `postgres-uow`: rename `ConfigDb` → `PostgresDbConfig`.
- `cloud-config`: rename `ConfigRemote` → `RemoteDefaults` in the
  `parse_clouds(cfg, remote: …)` signature.
- `package-facades`: the entire `yascheduler/config/__init__.py SHALL re-export`
  block (L485-498) removed — the `yascheduler/config` package is deleted, so the
  block (including the `Config`/`ConfigDb`/`ConfigLocal`/`ConfigRemote` re-exports
  and the `AzureImageReference`/`ConfigCloud*` NO-LONGER blocks) describes a
  non-existent file.

**Strip migration residue (keep only positive assertions about current state):**
- `domain-ports`: rewrite the "…ports replace MachineGateway" requirement as
  "three Protocols are defined"; delete the defensive "MachineGateway not
  exported" and "No stale prose under MachineGateway port" scenarios; drop
  `decompose-ssh-gateway` references.
- `cloud-provisioner`: drop "`machine_gateway` attribute is renamed
  `machine_repository`", "relocated", "renamed from".
- `cloud-config`: drop "resolve-type-bridge-debt D1", "engine-to-domain-frozen
  D4", "relocated from `yascheduler.config.cloud`".
- `use-cases`: drop "replacing the former `gateway: MachineGateway`", "legacy
  `RemoteMachineRepository`".
- `cli-commands`: drop the `@to_sync` → `asyncio.run` migration narrative.
- `daemon-common`: keep the positive "entry points use `asyncio.run`" rule,
  drop the "not `@to_sync`" framing.
- `package-facades`: remove ~20 "X SHALL NO LONGER be re-exported" /
  "the prior Y is removed" negative blocks; keep only positive per-facade
  export lists.
- `ssh-keys-loading`: drop "the prior `get_private_keys` method" framing and the
  defensive `ConfigLocal SHALL NOT carry a get_private_keys() method` clause +
  `Scenario: ConfigLocal has no get_private_keys method` (stale SHALL-NOTs about a
  renamed symbol).

**Merge (consolidate fragmented subsystems) — BREAKING:**
- **BREAKING** Merge `app-settings` + `db-config` + `config-aggregate` → new
  `config-value-objects` spec (Requirements: `LocalSettings`, `RemoteDefaults`,
  `PostgresDbConfig`, `Config`; preserves the `config-aggregate` layering rule
  "no `application`/`infra` module imports `Config`").
- Merge `testing-infrastructure` → `testing-unit` (absorb pytest-config,
  dir-structure, CI-workflow requirements; de-duplicate the overlapping
  `UniqueQueue` and shared-fixture requirements).
- Merge `allocation-tracker` → `use-cases` (add as a requirement; drop the
  standalone spec).

**Trim bloat:**
- `cli-commands`: trim-in-place ~1482 → ~800 lines — extract one shared "CLI
  exit-code contract" requirement referenced by per-command requirements;
  de-duplicate the repeated 0/1/2 blocks. Not split into per-command specs
  (that would raise the count, against the goal).

**Update `AGENTS.md`:** OpenSpec Rule section lists all 31 final specs as
`` `openspec/specs/<name>` `` entries (no prose links); terse one-line
description only where the name is not self-explanatory. Replaces the current
4-bullet testing-only subset.

- Strip `yascheduler.config` defensive residue (same class — "not from the deleted
  package" / "the package does not exist" scenarios) from: `cloud-providers`,
  `platform-adapters`, `dependency-injection`, `config-parser-assembly`.

Net: 35 → 31 specs, ~7640 → ~5000 lines (~35% reduction). No code, DB, CLI, or
public API changes — specs-only.

## Capabilities

### New Capabilities
- `config-value-objects`: merged frozen-config value-object contract — `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`, `Config` frozen dataclasses with `__post_init__` validation, no INI-parsing methods, and the composition-root-only consumption rule for `Config`. Replaces `app-settings`/`db-config`/`config-aggregate`.

### Modified Capabilities
- `domain-ports`: delete the `capacity()` "Report capacity" scenario (contradicts the "removed" clause in the same requirement); rewrite the "…replace MachineGateway" requirement as a positive "three Protocols are defined" statement; delete the defensive "MachineGateway not exported" and "No stale prose under MachineGateway port" scenarios.
- `ssh-keys-loading`: delete the "ConfigLocal migrated to stdlib dataclass" requirement; rename `ConfigLocal` → `LocalSettings` in the surviving `list_private_keys` contract and scenarios; drop the "prior `get_private_keys` method" framing and the defensive `ConfigLocal SHALL NOT carry get_private_keys()` clause + `ConfigLocal has no get_private_keys method` scenario.
- `testing-unit`: fix `yascheduler/client.py` → `entrypoints/client.py` implementation path in the `queue_submit_task_async` / `queue_get_tasks_async` requirements; absorb `testing-infrastructure` content (pytest config, test dir structure, CI workflow) and de-duplicate the overlapping `UniqueQueue` + shared-fixture requirements.
- `postgres-schema-apply`: rename `ConfigDb` → `PostgresDbConfig` in the `apply_schema` signature and scenarios.
- `postgres-uow`: rename `ConfigDb` → `PostgresDbConfig` in the construction requirement.
- `cloud-provisioner`: strip "`machine_gateway` renamed", "relocated", "renamed from" residue from the `configs`/`CloudInitConfig`/`stop` requirements.
- `cloud-config`: strip "resolve-type-bridge-debt D1", "engine-to-domain-frozen D4", "relocated from yascheduler.config.cloud" residue; rename `ConfigRemote` → `RemoteDefaults` in the `parse_clouds` signature.
- `use-cases`: strip "replacing the former `gateway: MachineGateway`" and "legacy `RemoteMachineRepository`" residue; absorb the `allocation-tracker` requirement.
- `cli-commands`: extract one shared "CLI exit-code contract" requirement; drop per-command 0/1/2 duplication and the `@to_sync` migration narrative (~1482 → ~800 lines).
- `package-facades`: remove the ~20 "X SHALL NO LONGER be re-exported" / "the prior Y is removed" negative blocks and the entire `yascheduler/config/__init__.py SHALL re-export` block (L485-498 — the package is deleted); keep only positive per-facade export lists for packages that exist.
- `daemon-common`: drop the "not `@to_sync`" framing, keep the positive "uses `asyncio.run`" rule.
- `cloud-providers`: strip the "not from `yascheduler.config`" defensive residue (L17, L37).
- `platform-adapters`: strip the "not `from yascheduler.config import`" defensive residue (L52).
- `dependency-injection`: strip the "not `yascheduler.config`" / "package is removed" defensive residue (L16, L54, L78, L83).
- `config-parser-assembly`: strip the "SHALL NOT live in `yascheduler.config`" clause and the `Scenario: yascheduler.config package does not exist` defensive scenario (L36, L79-80).

### Removed Capabilities
- `app-settings`: merged into `config-value-objects`.
- `db-config`: merged into `config-value-objects`.
- `config-aggregate`: merged into `config-value-objects`.
- `testing-infrastructure`: merged into `testing-unit`.
- `allocation-tracker`: merged into `use-cases`.

## Impact

- **Code:** None. Specs-only change. No `yascheduler/` files touched.
- **Tests:** None. No test asserts spec text.
- **AGENTS.md:** OpenSpec Rule section rewritten — full list of 31 final specs as `` `openspec/specs/<name>` `` entries replacing the 4-bullet testing subset.
- **Knowledge graph (`docs/knowledge-graph.xml`):** Verify module records referencing the merged-away spec names; a grep for `app-settings`/`db-config`/`config-aggregate`/`testing-infrastructure`/`allocation-tracker` in the graph found no cross-refs in `openspec/specs/`, so likely no graph edit is needed (graph tracks M-* code modules, not specs). If any module annotation references a merged spec name, repoint it to the merge target.
- **OpenSpec validation:** `openspec validate --all --json` must pass after the merge. No cross-refs to the removed capability names exist in `openspec/specs/` (verified), so no repointing of spec-to-spec references is required.
- **Risk:** Low. Spec consumers are humans + the OpenSpec validator. Stale references are already misleading; this change reduces drift. Reversible via git history.
