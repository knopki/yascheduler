# Explore Brief — cleanup-specs-consolidate

## Goal
Specs-only hygiene pass over `openspec/specs/` (35 specs, ~7640 lines): fix live
contradictions, strip migration residue, consolidate fragmented specs, trim the two
giants. No code/DB/CLI changes. Target: 35 → 31 specs, ~7640 → ~5000 lines.

## Alternatives rejected
- **Split cli-commands into per-command specs** — increases spec count, contradicts
  the reduction goal. Chose trim-in-place (~1482 → ~800 lines: dedup the repeated
  0/1/2 exit-code contract into one shared requirement, drop the to_sync narrative).
- **Merge abstract-uow (into use-cases or postgres-uow)** — mixes layers
  (application Protocol vs infra impl) or loses the boundary-contract role. Leave
  standalone.
- **Merge domain-services / domain-events / cli-args / daemon-common** — each is a
  distinct contract, not fragmentation. Leave.
- **Split the work into multiple proposals** — fragments review; the 4 categories
  are cohesive specs-hygiene. One change.

## Final mapping tables

### Category A — active defects (spec contradicts code)
| Defect | Spec | Fix |
|---|---|---|
| `capacity()` contradiction (req says removed, scenario tests it) | domain-ports | delete the Report-capacity scenario; keep select_provider only |
| `ConfigLocal` block describes removed class + `yascheduler.config` pkg | ssh-keys-loading | delete "ConfigLocal migrated" requirement; rewrite `ConfigLocal`→`LocalSettings` in surviving text |
| stale impl path `yascheduler/client.py` (now shim) | testing-unit | rewrite to `entrypoints/client.py` |
| old name `ConfigDb` (current `PostgresDbConfig`) | postgres-schema-apply L12, postgres-uow L46 | rename to PostgresDbConfig |
| old-name sweep (ConfigLocal traces, etc.) | TBD by sweep | rename to current symbols |

### Category B+G — migration residue to strip (keep only positive assertions)
domain-ports, package-facades (~20 "X SHALL NO LONGER be re-exported" blocks),
cloud-provisioner ("machine_gateway renamed", "relocated", "renamed from"),
cloud-config ("resolve-type-bridge-debt D1", "engine-to-domain-frozen D4",
"relocated from yascheduler.config.cloud"), use-cases ("replacing the former
gateway: MachineGateway", "legacy RemoteMachineRepository"), ssh-keys-loading
("the prior get_private_keys method"), cli-commands (to_sync narrative),
daemon-common (light: keep "uses asyncio.run", drop "not @to_sync" framing).

### Category B continued — defensive scenarios to delete
domain-ports: "MachineGateway not exported", "No stale prose under MachineGateway
port", the whole "MachineRepository/Session/Operations ports replace
MachineGateway" framing → rewrite as "three Protocols are defined" without
referencing the removed predecessor.

### Category C — merges (35 → 31)
| Merge | Into | Δ |
|---|---|---|
| app-settings + db-config + config-aggregate | config-value-objects (new) | −2 |
| testing-infrastructure | testing-unit | −1 |
| allocation-tracker | use-cases | −1 |

config-value-objects keeps 4 Requirements: LocalSettings, RemoteDefaults,
PostgresDbConfig, Config (colocated, not restructured). Preserves the
config-aggregate layering rule ("no application/infra module imports Config").

## Cross-module data flows
N/A — specs-only change. No code, no DB schema, no CLI surface, no engine contract.
Knowledge graph (`docs/knowledge-graph.xml`) tracks M-* code modules, not specs; no
graph update required.

## AGENTS.md
Update OpenSpec Rule section: list all 31 final specs as `` `path/to/spec` ``
entries (no prose links), terse one-line description only where the name is not
self-explanatory. Remove the 4-bullet testing-only subset.

## Open questions
None. All decisions confirmed.
