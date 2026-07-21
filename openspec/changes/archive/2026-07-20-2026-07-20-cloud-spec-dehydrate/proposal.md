## Why

`openspec/specs/cloud/spec.md` is 318 lines across 10 requirements and is the
last bloated behavior spec in the project after `orchestrator` and
`domain-ports` were dehydrated. It mixes three kinds of content that the GRACE
methodology assigns to code-local contracts, not to the spec:

1. **Method-level pre/post-conditions and invariants.** The DTO→Node field
   mapping in `CloudProvisionerImpl.allocate`, the "DTO mapping in `allocate` is
   the sole source for jump fields" invariant on `_setup_vm`, the
   "`machine_repository.connect(...)` carries no `jump_host` / `jump_username`
   kwargs" invariant, and the "standalone `get_cpu_cores()` is NOT invoked in
   the setup path" invariant. These are `METHOD_*` `ENSURES` / `INVARIANTS` on
   `manager.py`, not spec-level requirements.
2. **Architectural rationale.** "The concrete DTOs SHALL explicitly inherit the
   Protocol (a typing aid; structural matching per PEP 544 still applies)",
   "`package_upgrade` SHALL NOT be on the `CloudConfig` Protocol — it is read
   only by infra", "the runtime `from yascheduler.domain import CloudConfig`
   import in the DTO module is permitted by the layers contract",
   "`disconnect_all` is idempotent, so calling it from both `clouds.stop()` and
   `Orchestrator.stop()` is safe", "validation SHALL run inside the per-prefix
   parser functions before constructing the DTO — not in `__post_init__`". These
   are `RATIONALE` Q/A and `MODULE_CONTRACT` `INVARIANTS`.
3. **Provider implementation contracts.** "Hetzner SHALL resolve via
   `client.servers.get_by_id(int(external_id))` — an O(1) lookup that does NOT
   iterate all servers", "Each adapter is responsible for sourcing jump fields
   from its own config DTO". These are `INVARIANTS` on the provider
   `FUNC_*_create_node` / `FUNC_*_delete_node` regions.

The bloat causes drift (spec text and code comments describe the same algorithm
twice), obscures the actual acceptance criteria (the Given/When/Then scenarios),
and forces every reader to mentally separate signal (SHALL) from noise
(design narrative). The GRACE methodology explicitly assigns these content
kinds to code-local markup.

## What Changes

- **TRIM** `openspec/specs/cloud/spec.md` from 318 to ~275 lines (~13% reduction),
  keeping every observable behavioral scenario (all 28 Given/When/Then blocks,
  byte-for-byte) and every public-type signature. Remove implementation
  rationale, method-level pre/post-conditions, DTO-mapping step lists, and
  architectural-pitch prose from the spec body. The reduction is smaller than
  the `orchestrator` (~38%) and `domain-ports` (~44%) dehydrates because the
  `cloud` spec's bulk is type signatures and per-provider observable rules, not
  step-by-step algorithm narrative; most of the relocation targets GRACE
  `INVARIANTS` and `RATIONALE` on already-existing `METHOD_*` regions.
- **RELOCATE** the trimmed content into GRACE markup on the cloud modules:
  - `yascheduler/infra/cloud/cloud_configs.py` — tighten `MODULE_CONTRACT`
    `PURPOSE` to WHY; add `MODULE_CONTRACT` `INVARIANTS` (no `cast(...)` bridges
    in the composition root, no INI parsing on DTOs, validation in the parser
    not in `__post_init__`) and `RATIONALE` Q/A covering the structural-Protocol
    inheritance aid, the `package_upgrade`-not-on-Protocol split, and the
    `AzureImageReference` non-inheritance. Add `CLASS_AzureImageReference`,
    `CLASS_ConfigCloudAzure`, `CLASS_ConfigCloudHetzner`, `CLASS_ConfigCloudUpcloud`,
    `CLASS_ConfigCloudVastAI` regions, each wrapping the entire class.
  - `yascheduler/infra/cloud/dto.py` — add `CLASS_CloudCreateNodeDTO` region
    wrapping the entire dataclass; `PURPOSE` (WHY: carry the cloud-provisioned
    VM's connection identity across the adapter boundary so the provisioner
    stays provider-agnostic); `INVARIANTS` (`external_id` is the authoritative
    provider identifier; SSH defaults on `username`/`port`/`jump_*`).
  - `yascheduler/infra/cloud/manager.py` — extend `MODULE_CONTRACT`,
    `CLASS_CloudProvisionerImpl`, and the existing `METHOD_*` regions with the
    relocated invariants and rationale (DTO-mapping postconditions on
    `METHOD_allocate`; `_setup_vm` does-not-touch-jump-fields invariant on
    `METHOD__setup_vm`; `disconnect_all` idempotency `RATIONALE` on `METHOD_stop`;
    setup-failure-disconnect rationale on the failure `BLOCK`).
  - `yascheduler/infra/cloud/adapters.py` — add `CLASS_CloudAdapter` `RATIONALE`
    (adapter owns jump-field sourcing).
  - `yascheduler/infra/cloud/providers/{az,hetzner,upcloud,vastai}.py` — add
    `INVARIANTS` to the existing `FUNC_*_create_node` / `FUNC_*_delete_node`
    regions covering `external_id` semantics and resource-location rules.
  - `yascheduler/entrypoints/config_parser.py` — extend `MODULE_CONTRACT`
    `INVARIANTS` (validation runs inside per-prefix parsers before constructing
    the DTO; auto-register via DTO field set; no `cast(...)` bridges); extend
    `FUNC_parse_clouds` `INVARIANTS` and the four `FUNC__parse_*_section` regions.
- **NO BEHAVIORAL CHANGE.** No code logic change. No test change. Every
  observable scenario in the trimmed spec MUST remain covered by the existing
  unit and integration tests.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `cloud`: requirements slimmed to SHALL statements + behavior scenarios;
  design context (method-level pre/post-conditions, architectural rationale,
  provider implementation invariants) relocated to GRACE markup on
  `yascheduler/infra/cloud/*` and `yascheduler/entrypoints/config_parser.py`.
  No DTO definition, parser signature, Protocol member, provisioner behavior,
  scenario, or public-API surface is added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/cloud/spec.md` rewritten (slimmed from 318 to ~275
  lines, ~13% reduction). `openspec validate --all --json` must still pass after
  the change.
- **Code (markup only, no logic)**: `yascheduler/infra/cloud/cloud_configs.py`,
  `dto.py`, `manager.py`, `adapters.py`, `cloud_init.py`,
  `providers/{az,hetzner,upcloud,vastai}.py`, and
  `yascheduler/entrypoints/config_parser.py` gain/extend GRACE contract fields.
  Only comments move; no signature, body, or import changes.
- **Tests**: no change. Existing scenarios in the slimmed spec remain the
  acceptance criteria; existing tests already assert them. A passing
  `uv run pytest -m unit` run on the cloud tests after the change is the
  regression guard.
- **Public surface**: none. No CLI, API, INI, DB schema, or log-format change.
- **Scope boundary**: this change ONLY dehydrates the `cloud` spec. Other
  specs are out of scope.
