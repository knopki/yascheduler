# Review Log — cloud-configs-to-infra-registry (P3)

## proposal Round 1 — 2026-06-25

Reviewer: code-review-agent
Scope: proposal.md, explore-brief.md, docs/config-layer-split-plan.md, P2 proposal+design+tasks, existing specs

---

### 1. Capabilities: NEW vs MODIFIED

**Assessment: Correctly categorized. No overlap with existing specs.**

Three new capabilities are correctly identified as NEW:
- `cloud-config-dtos` — pure data definitions, no parsing. Distinct from `cloud-providers` (which covers provider code relocation + `CloudConfig.render()` stability — unrelated concerns).
- `cloud-config-protocol` — Protocol in domain/ports.py. New addition to `domain-ports`, correctly also listed as a MODIFIED capability for that spec.
- `cloud-config-parsers` — INI parsing + registry in entrypoints. Distinct from `cloud-config-dtos`.

Five modified capabilities all have genuine requirement-level changes (see §7 below). No overlap or double-counting.

🟡 **Clarity note**: `cloud-config-protocol` is redundantly listed as both a NEW capability and the sole change in the `domain-ports` MODIFIED capability. This is not a bug (the Protocol itself is new; the spec delta documents the existing spec change), but the proposal could be clearer that the Protocol IS the modification to domain-ports, not a separate concern.

---

### 2. BREAKING changes

**Assessment: All breaking changes correctly identified. None missed.**

| Breaking change | Identified in proposal? | Notes |
|---|---|---|
| `from yascheduler.config.cloud import ...` → `from yascheduler.infra.cloud import ...` | Yes (§Impact) | |
| `from yascheduler.config import ConfigCloud*` / `AzureImageReference` → `from yascheduler.infra.cloud import ...` | Yes (§Impact) | |
| `ConfigCloudX.from_config_parser_section(...)` → `parse_cloud_section(sec, prefix)` | Yes (§What Changes, §Impact) | |
| `ConfigCloudX.get_valid_config_parser_fields(...)` → `cloud_valid_fields(...)` | Yes (§What Changes, §Impact) | |
| `cloud_variants` tuple removed from `Config.from_config_parser` | Yes (§What Changes) | |
| `infra/cloud/protocols.py` runtime import → intra-package | Yes (§What Changes) | |
| `config/__init__.py` loses cloud re-exports | Yes (§What Changes) | |
| `infra/cloud/__init__.py` gains cloud re-exports | Yes (§What Changes) | |

**No missed breaking changes:**
- `ConfigCloud` Union consumers: all covered (protocols.py TypeVar, `CloudProvisionerImpl.configs` typing, application-layer TYPE_CHECKING).
- `AzureImageReference.from_urn`: retained as a pure parser (no INI dependency); only the import path changes (covered).
- Application-layer consumers (`deallocate_nodes`, `orchestrator`): all switch from `ConfigCloud` → `CloudConfig` under TYPE_CHECKING (covered).
- `CloudProvisionerImpl._connect_to_vm` `getattr` fallbacks for `jump_host`/`jump_username`: can become direct attribute access (non-breaking improvement, correctly identified in explore-brief but the proposal mentions it only as a capability note — no harm since the existing `getattr` fallback with default `None` continues to work either way).

---

### 3. Registry placement decision

**Assessment: Proposal matches Decision (b). Explore-brief has a stale table cell.**

The proposal places `CLOUD_CONFIG_PARSERS` in `entrypoints/config_parser.py` (line 45-49), which is consistent with Decision (b) in the explore-brief (line 132-135): *"Registry in `entrypoints/config_parser.py` (R3-legal direction)."*

🟡 **Stale data in explore-brief**: The module relocation table (line 63) shows `CLOUD_CONFIG_PARSERS` target as `yascheduler/infra/cloud/cloud_configs.py`, which contradicts Decision (b) in the same document. The table was not updated after the decision was made. The proposal correctly follows the decision, not the stale table cell. This should be corrected in the explore-brief when the proposal is finalized.

---

### 4. Composition with P2

**Assessment: Correctly described. No composition gap.**

The proposal states (line 20-21): *"P3 composes with P2 (each removes its own `config/` re-exports; the parser module gains cloud parsers alongside the engine parsers P2 added)."*

Verified against P2's proposal + tasks:
- P2 creates `entrypoints/config_parser.py` with `parse_engine_section`, `parse_engines`, `engine_valid_fields` and the validator helpers.
- P3 extends the same file with `parse_cloud_section`, `parse_clouds`, `cloud_valid_fields`, and the `CLOUD_CONFIG_PARSERS` registry.
- Both import `make_default_field`/`warn_unknown_fields` from `config/utils.py` (consistent).
- P2 removes `Engine`/`EngineRepository`/`Deploy*` from `config/__init__.py`; P3 removes `ConfigCloud*`/`AzureImageReference`/`ConfigCloud`. Each removes its own re-exports — no conflict.
- P2 modifies `Config.from_config_parser` to call `parse_engines`; P3 modifies the same method to call `parse_clouds`. Different function calls within the same method — no conflict, clean merge.

The proposal correctly handles the sequencing uncertainty: *"created by P2 or extended here if P2 not yet implemented"* (line 153). If P3 runs before P2, P3 creates `entrypoints/config_parser.py` with only cloud parsers, and P2 later adds engine parsers. Both changes are additive to the same file; standard merge handles this.

The `infra/cloud/manager.py` TYPE_CHECKING import update in P3 only touches the `ConfigCloud` part of the import; the `EngineRepository` part is P2's concern. P3 does not interfere.

🟡 **Minor**: The proposal says P2 *"already migrated or this proposal assumes P2 done"* for the `EngineRepository` import in manager.py (implied by the consumer table). This is fine because if P2 is NOT done, the existing `from yascheduler.config import ... EngineRepository ...` still works (P2 hasn't removed it yet). P3 only changes the `ConfigCloud` import, leaving `EngineRepository` untouched for P2. The composition is clean in both directions.

---

### 5. `CloudConfig` Protocol field set

**Assessment: Complete. All 6 fields present, matching the explore-brief's consumer-usage table.**

| Field | Proposal | Explore-brief | Match |
|---|---|---|---|
| `prefix: str` | Yes | Yes | ✓ |
| `max_nodes: int` | Yes | Yes | ✓ |
| `idle_tolerance: int` | Yes | Yes | ✓ |
| `username: str` | Yes | Yes | ✓ |
| `jump_username: str \| None` | Yes | Yes | ✓ |
| `jump_host: str \| None` | Yes | Yes | ✓ |

All application-layer consumers (`deallocate_nodes`, `orchestrator._clouds_get_capacity`, `orchestrator._connect_machine_consumer`) access only these 6 fields. Infra-layer consumers (`CloudProvisionerImpl`) stay typed against the concrete DTOs for provider-specific fields — correct by design.

---

### 6. `yascheduler.config` exemption list and `forbidden` contract

**Assessment: Correctly preserved. Not removed in P3.**

The proposal does not claim to:
- Remove `yascheduler.config` from the outside-layer-set exemption list (P4 job, per umbrella plan §4 P4).
- Remove the `forbidden` contract (P4 job, per umbrella plan §2.6 + §4 P4).

The config package still exists after P3 (with `config/config.py`, `config/db.py`, `config/local.py`, `config/remote.py`, `config/utils.py`). Only `config/cloud.py` is deleted and its re-exports removed from `config/__init__.py`.

🟡 **Clarity gap**: The proposal does not explicitly state *"`yascheduler.config` remains in the outside-layer-set exemption list"* like the explore-brief does (line 232-233). This is inferable (the package still exists), but for readers who haven't read the brief, the exemption-list status is a meaningful design constraint that should be stated in the proposal's Impact section.

---

### 7. Modified Capabilities delta spec scoping

**Assessment: All 5 have genuine requirement-level changes, though `cloud-provisioner` is thin.**

| Modified capability | Nature of spec change | Assessment |
|---|---|---|
| `cloud-providers` | Provider modules' TYPE_CHECKING imports change from `yascheduler.config` → `yascheduler.infra.cloud`; DTO form changes from attrs → frozen dataclass | **Genuine**: The existing spec has scenarios for provider importability (e.g., `az_create_node` from `adapters.cloud.providers.az`); the import path for config DTOs is a spec-level concern. |
| `cloud-provisioner` | `CloudProvisionerImpl.configs` typed against relocated union; `_connect_to_vm` `getattr` fallbacks become direct attribute access | **Thin**: The spec's existing requirements are about provisioning behavior (allocate, deallocate, select_provider, cloud-init), not about import paths or typing annotations. The `configs` dict typing and `getattr`→direct access are implementation details. However, the spec's `select_provider` scenarios reference `configs[name].max_nodes`, which references the DTOs — the import-path change is implicit. **Suggestion**: Consider whether a delta spec is needed here or whether the change is fully captured by the `cloud-config-dtos` and `package-facades` deltas. No harm in including it, but it's documentation overhead. |
| `package-facades` | Config facade loses cloud DTO re-exports; infra.cloud facade gains them; exemption list shrinks (one edge removed) | **Genuine**: The spec explicitly lists facade contents (§"Extended facade contents" / "Requirement: Outside-layer-set exemptions"). Both need updating. |
| `domain-ports` | `CloudConfig` structural Protocol added alongside `OccupancyConfig` and `TaskExecutionEngine` | **Genuine**: New Protocol requirement + field set + structural satisfaction scenario. |
| `testing-unit` | Cloud-parsing tests migrate from `from_config_parser_section` direct calls to `parse_clouds`/`parse_cloud_section`; assert frozen + no parser methods | **Genuine**: The spec's "Config parsing and validation" requirement (line 112-124) has explicit scenarios for cloud config parsing that need updating. |

🟡 **Recommendation**: Keep `cloud-provisioner` delta for completeness, but keep it minimal (one scenario documenting that `configs` typing resolves from the infra facade).

---

### Cross-document issues

🟡 **Umbrella plan §4 P3 vs proposal: registry location differs**

The umbrella plan §4 P3 (line 230-231) says: *"Introduce `CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy], CloudConfig]]` in `infra/cloud/`"*. The proposal places the registry in `entrypoints/config_parser.py` instead. The explore-brief explicitly resolves this via Decision (b), but the proposal does not call out the deviation from the umbrella plan. This is a valid design evolution (Decision (b) was made during explore), but for traceability the proposal should note that the registry placement was moved from `infra/cloud/` (umbrella plan) to `entrypoints/config_parser.py` by Decision (b) in the explore-brief, to avoid confusion for future readers who cross-reference the umbrella plan.

🟡 **Explore-brief `CLOUD_CONFIG_PARSERS` type signature**: The code example (line 108-113) shows `Callable[[SectionProxy], "ConfigCloud"]` (returning the concrete Union), while the proposal shows `Callable[[SectionProxy], CloudConfig]` (returning the Protocol). Both are valid (the DTOs satisfy the Protocol structurally), but the inconsistency between the brief and the proposal should be reconciled. The proposal's `CloudConfig` return type is more correct since the registry is consumed by `parse_clouds` which returns `list[CloudConfig]`.

🟡 **Explore-brief module relocation table stale for `CLOUD_CONFIG_PARSERS`** (line 63): Already noted in §3 above. The table row shows target `infra/cloud/cloud_configs.py` but Decision (b) places it in `entrypoints/config_parser.py`. The table should be updated to reflect the decision.

---

### Summary

| Severity | Count | Items |
|---|---|---|
| 🔴 Blocking | 0 | |
| 🟡 Addressed / Minor | 7 | Stale explore-brief table cell (CLOUD_CONFIG_PARSERS target); missing explicit exemption-list statement in proposal; registry placement vs umbrella plan deviation not called out in proposal; `cloud-provisioner` delta thinness; explore-brief registry type signature discrepancy with proposal; redundant NEW/MODIFIED labeling for `cloud-config-protocol`; explore-brief module relocation table not updated after Decision (b) |
| ✅ Correct | 6 | Capabilities split (distinct, non-overlapping); breaking changes fully identified; registry placement matches Decision (b); P2 composition handles both sequencing scenarios; CloudConfig field set complete; exemption list / forbidden contract correctly preserved for P4 |

**Recommendation: APPROVE WITH NOTES** — No blocking issues. Address the 🟡 items (primarily explore-brief cleanup and adding the exemption-list statement to the proposal) before or during implementation.

## design Round 1 — 2026-06-25

Reviewer: code-review-agent
Scope: design.md, proposal.md (frozen), explore-brief.md, docs/config-layer-split-plan.md §3–4, P2 design.md D7, package-facades spec.md R1/R2 rules, current codebase imports

---

### 1. Decisions (D1–D7) alignment with frozen proposal

**Assessment: All aligned. No contradictions.**

| Decision | Design | Proposal | Alignment |
|---|---|---|---|
| D1: frozen dataclass, no parser methods | `@dataclass(frozen=True)`, parser-side validation | Same | ✓ |
| D2: registry in `entrypoints/config_parser.py` | Decision (b), explicitly notes umbrella-plan deviation | Same, with same deviation note | ✓ |
| D3: lazy-import cloud assembly | `parse_clouds(cfg, remote)` lazy-imported in `Config.from_config_parser` | Same pattern | ✓ |
| D4: `CloudConfig` Protocol, 6 fields | `prefix, max_nodes, idle_tolerance, username, jump_username, jump_host` | Same 6 fields | ✓ |
| D5: protocols.py intra-package import | `from .cloud_configs import ConfigCloud` | Same | ✓ |
| D6: provider imports via facade path | `from yascheduler.infra.cloud import ConfigCloudAzure, ...` | "Prefer facade import for consistency" (proposal) | ✓ |
| D7: getattr→direct access (optional) | Non-breaking improvement, optionally deferrable to P4 | Mentioned as "can become" capability note | ✓ |

---

### 2. D2 — registry placement matches umbrella-plan deviation

**Assessment: Correctly handled.**

Design D2 explicitly states (lines 144-145): *"The umbrella plan §4 P3 placed the registry in `infra/cloud/`; the explore-brief Decision (b) corrects this — the proposal and design follow Decision (b)."*

The umbrella plan §4 P3 (line 230-231) placed registry in `infra/cloud/`. The explore-brief Decision (b) moved it to `entrypoints/config_parser.py`. The design explicitly acknowledges the deviation, which provides the necessary traceability for future readers. ✓

Note: the explore-brief's module relocation table (line 63) has been updated since the proposal review — it now correctly shows `entrypoints/config_parser.py` as the target. The stale-table issue from the proposal round is resolved.

---

### 3. D3 composition with P2 D7 — two lazy-imported `parse_*` calls in the same method

**Assessment: No conflict. Verified against P2 design D7.**

P2 D7: `Config.from_config_parser` calls `parse_engines(cfg, engines_dir)` via lazy import from `entrypoints/config_parser.py`.
P3 D3: `Config.from_config_parser` calls `parse_clouds(cfg, remote)` via lazy import from `entrypoints/config_parser.py`.

Both add a lazy-imported call to the same `Config.from_config_parser` method body, referencing different functions from the same target module. After both P2 and P3, the method body contains:

```python
from yascheduler.entrypoints.config_parser import parse_engines
from yascheduler.entrypoints.config_parser import parse_clouds  # added by P3
# ... db, local, remote assembly inline until P4 ...
engines = parse_engines(cfg, local.engines_dir)
clouds = parse_clouds(cfg, remote)  # added by P3
```

No name collision, no conflicting imports, no method signature change. The design's claim that "P3 and P2 compose cleanly — both add a lazy-imported `parse_*` call to the same method; no conflict" (lines 172-174) is correct.

Sequencing is also handled: the design notes (line 320) that if P2 is not yet implemented, P3 creates `entrypoints/config_parser.py` with only cloud parsers, and P2 later adds engine parsers. Both changes are additive; git merge resolves cleanly. ✓

---

### 4. D4 — `CloudConfig` Protocol field set matches explore-brief

**Assessment: Exact match. All 6 fields justified by consumer-usage evidence.**

| Field | Design D4 | Explore-brief field-set table | Match |
|---|---|---|---|
| `prefix: str` | ✓ | ✓ | ✓ |
| `max_nodes: int` | ✓ | ✓ | ✓ |
| `idle_tolerance: int` | ✓ | ✓ | ✓ |
| `username: str` | ✓ | ✓ | ✓ |
| `jump_username: str \| None` | ✓ | ✓ | ✓ |
| `jump_host: str \| None` | ✓ | ✓ | ✓ |

Justification in explore-brief (lines 67-74) identifies each field's consuming code path: `deallocate_nodes` uses `prefix`, `idle_tolerance`; `orchestrator._clouds_get_capacity` uses `prefix`, `max_nodes`; `orchestrator._connect_machine_consumer` uses `prefix`, `jump_host`, `jump_username`; `CloudProvisionerImpl._connect_to_vm` uses `username`, `jump_host`, `jump_username`; `provider_selection_pure` and `di.make_daemon` use `max_nodes`. All 6 fields have at least one concrete consumer. ✓

---

### 5. D6 — provider import path: R1/R2 analysis

**Assessment: Facade path `from yascheduler.infra.cloud import ...` is correct. R1 relative path is not available; deep path would violate R2.**

The providers (`infra/cloud/providers/{az,hetzner,upcloud,vastai}.py`) sit inside the `infra.cloud` subpackage alongside `cloud_configs.py`. The R1 rule says modules within the same package should use relative imports, but the spec also says:

> **No parent-traversal relative imports anywhere**: no `from .. import`, `from ... import` (or deeper) — only `from .` (single-level sibling) permitted.

Since the providers are in `infra/cloud/providers/` and `cloud_configs.py` is in `infra/cloud/`, the R1 relative path would be `from ..cloud_configs import ...` — a parent-traversal relative import, which is explicitly banned by the package-facades spec (scenario "No parent-traversal relative imports anywhere").

The deep absolute path `from yascheduler.infra.cloud.cloud_configs import ...` would bypass the subpackage facade, violating the R2 requirement.

The only compliant import path is `from yascheduler.infra.cloud import ...` (the subpackage facade), which is also consistent with the existing provider-module style (`from yascheduler.infra.cloud import get_rnd_name`). D6 correctly chooses this path. ✓

🟡 **Explore-brief consumer call site table divergence**: The explore-brief's consumer call site table (lines 90-93) still lists `from yascheduler.infra.cloud.cloud_configs import ...` as the preferred import path for provider modules. D6 corrects this to the facade path. The explore-brief table should be updated to match D6 — the deep path bypasses the facade (R2 violation) and the relative path is banned (R1 parent-traversal rule).

---

### 6. Risks/Trade-offs — completeness vs proposal

**Assessment: Complete. No gaps.**

| Proposal Impact element | Covered in design Risks? |
|---|---|
| BREAKING API changes (import paths) | Migration Plan §steps 5–10; Non-Goals |
| Layers contract exemption shrinks | Design Context §constraints; D5 mentions one edge removed |
| attrs remains project dependency | Risk #4 explicitly states attrs stays in other config modules |
| MagicMock(spec=ConfigCloud) audit | Risk #1 explicitly covers this |
| Parser locality loss | Risk #2 explicitly covers this |
| Config.from_config_parser partial extraction | Risk #3 explicitly covers this |
| Registry import-time ordering | Risk #5 (new, not in proposal — reasonable addition) |
| CloudConfig vs ConfigCloud naming confusion | Risk #6 (new, not in proposal — reasonable addition) |

The design adds 3 risks not in the proposal (Risk #3 partial extraction, Risk #5 import ordering, Risk #6 naming confusion). All are genuine and do not contradict the proposal. No proposal risks are missing. ✓

---

### 7. Migration Plan — consistency with proposal Impact

**Assessment: Consistent. All 12 steps map to proposal Impact items.**

| Proposal Impact | Design Migration Plan steps |
|---|---|
| New `cloud_configs.py` | Step 1 |
| Cloud parsers + registry in `entrypoints/config_parser.py` | Step 2 |
| `CloudConfig` Protocol in `domain/ports.py` | Step 3 |
| `Config.from_config_parser` delegation | Step 4 |
| Delete `config/cloud.py`; update `config/__init__.py`, `config/config.py` | Step 5 |
| `infra/cloud/__init__.py` re-exports | Step 6 |
| Import switches in `infra/cloud/*` | Step 7 |
| Application-layer TYPE_CHECKING switches | Step 8 |
| `entrypoints/di.py` TYPE_CHECKING update | Step 9 |
| `_connect_to_vm` getattr cleanup (optional) | Step 10 |
| Knowledge graph update | Step 11 |
| Test migration | Step 12 |
| Verification commands | Step 13 |

All proposal Impact items (code, APIs, layers contract, dependencies, specs, tests, knowledge graph) are covered by at least one migration step. ✓

🟡 **Minor gap**: Migration Plan step 5 says "update `config/config.py` to drop the `from .cloud import (...)` block" but does not specify what replaces the import for the `Config.clouds` field type annotation (`Sequence[ConfigCloud]`). Currently `config/config.py:34-40` imports `ConfigCloud` from `.cloud` for use in the `clouds` field annotation. After `config/cloud.py` is deleted, this import is a dangling reference. The replacement import (`from yascheduler.infra.cloud import ConfigCloud` or similar) should be explicitly stated in step 5 or step 4. This isn't blocking — the implementer can infer it — but a gap this concrete can cause confusion.

---

### 8. Open Questions — "None" justified

**Assessment: Justified. No genuine open architectural questions remain.**

- Q5–Q9 are locked in `docs/config-layer-split-plan.md` §3.
- Registry placement is resolved by Decision (b) in the explore-brief.
- `MagicMock(spec=ConfigCloud)` audit is an implementation-time discovery task (tasks.md), not an architectural open question.
- D7 (`getattr`→direct access) is scoped as optional; deferral to P4 is clean.

The only implementation-time unknown is which tests use `from_config_parser_section` or `get_valid_config_parser_fields` via `MagicMock(spec=...)` — this is explicitly called out in the risks section (Risk #1) and in the explore-brief as a grep discovery task. No need to list it as an open question. ✓

---

### Summary

| Severity | Count | Items |
|---|---|---|
| 🔴 Blocking | 0 | |
| 🟡 Addressed / Minor | 2 | Explore-brief consumer call site table still shows deep import path for providers (contradicts D6's correct facade-path decision); Migration Plan step 5 omits replacement import for `Config.clouds` field type annotation |
| ✅ Correct | 8 | D1–D7 alignment with proposal; D2 umbrella-plan deviation handling; D3 composition with P2 D7; D4 field set match; D5 correct; D6 R1/R2 analysis correct; Risks complete; Open Questions justified |

The design is structurally sound, consistent with the frozen proposal, and provides sufficient detail for implementation. The two 🟡 items are documentation-quality gaps in the explore-brief and migration plan, not design flaws.

**Recommendation: APPROVE WITH NOTES** — No blocking issues. Address the two 🟡 items during implementation:
1. Update the explore-brief consumer call site table for provider imports to match D6's facade path.
2. Add explicit mention in Migration Plan step 5 that `config/config.py` needs a new import for `ConfigCloud` (from `yascheduler.infra.cloud`) to replace the deleted `from .cloud import (...)` block.

## specs Round 1 — 2026-06-25

Reviewer: code-review-agent
Scope: delta specs (3 NEW, 5 MODIFIED) vs existing specs, proposal.md (frozen), design.md (frozen), explore-brief.md

---

### 1. MODIFIED requirement header matching

**Assessment: All 6 headers match verbatim. No mismatches.**

| Spec delta | Existing header | Delta header | Match |
|---|---|---|---|
| `cloud-providers` | `### Requirement: Provider code relocated` | same | ✓ |
| `cloud-provisioner` | `### Requirement: CloudProvisionerImpl implements CloudProvisioner` | same | ✓ |
| `package-facades` (1) | `### Requirement: Extended facade contents (lazy publication driven by consumers)` | same | ✓ |
| `package-facades` (2) | `### Requirement: Outside-layer-set exemptions` | same | ✓ |
| `domain-ports` (1) | `### Requirement: MachineGateway port` | same | ✓ |
| `domain-ports` (2) | `### Requirement: Ports are importable from domain` | same | ✓ |
| `testing-unit` | `### Requirement: Config parsing and validation` | same | ✓ |

No whitespace, punctuation, or wording discrepancies. Archive header-matching will succeed.

---

### 2. MODIFIED content completeness — requirement body (🔴 2 issues)

**🔴 Issue A: `package-facades` delta — "Extended facade contents" requirement body is incomplete**

The existing requirement body (lines 446–478) lists all subpackage facades and their re-exports:
- `yascheduler/infra/__init__.py` (layer facade: SSHMachineGateway, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork)
- `yascheduler/application/__init__.py` (AbstractUnitOfWork, Orchestrator, MessageBus, submit_task)
- `yascheduler/infra/notifier/__init__.py` (webhook_handler)
- `yascheduler/infra/cloud/__init__.py` (get_rnd_name + existing re-exports)
- `yascheduler/infra/persistence/__init__.py` (apply_schema, PostgresUnitOfWork)
- `yascheduler/config/__init__.py` (AzureImageReference)

The delta body only lists the TWO facades that change (cloud subpackage gains DTOs, config facade loses them). The other four facade definitions (infra layer, application, notifier, persistence) are **absent**. At archive time, if the delta body replaces the existing body, those facade re-export requirements would be lost — including the critical `yascheduler/infra/__init__.py` layer facade definition that `CloudProvisionerImpl` re-export depends on.

**Fix**: Either include the unchanged facade sections in the delta body, or confirm the archive mechanism merges at the sub-bullet level (not full body replacement). If the latter, the delta format is ambiguous and needs documentation.

**🔴 Issue B: `package-facades` delta — "Outside-layer-set exemptions" requirement body is incomplete**

The existing body (lines 306–333) lists three exemption bullets:
- `yascheduler.config` (modified — P3 sentence added) ✓
- `yascheduler.data` — **omitted from delta**
- `yascheduler.client` — **omitted from delta**

And the composition root relocation paragraph (lines 314–319) — **omitted from delta**.

The delta body only includes `yascheduler.config` (with the P3 addition) and the `yascheduler.shared` kernel definition. The `yascheduler.data` and `yascheduler.client` exemption bullets and the composition-root relocation note are lost.

Scenarios are complete (7 existing + 1 new = 8), but the scenario text references `yascheduler.data` and `yascheduler.client` in the "Outside-set modules not flagged for layer direction" scenario: `modules in the outside-set list (yascheduler.config, yascheduler.data, yascheduler.client)`. If the requirement body drops those exemption bullets, the scenario becomes unsupported by the requirement text.

**Fix**: Add back the `yascheduler.data` and `yascheduler.client` exemption bullets and the composition root relocation paragraph.

---

### 3. MODIFIED content completeness — scenarios within requirements

**Assessment: All existing scenarios preserved, new scenarios added. No scenario lost.** (Separate from the body-completeness issues in §2.)

| Requirement | Existing scenarios | Preserved? | New scenarios | Total |
|---|---|---|---|---|
| `cloud-providers`: Provider code relocated | 3 (Azure, Hetzner, UpCloud accessible) | ✓ | 2 (DTO import path, frozen dataclass) | 5 |
| `cloud-provisioner`: CloudProvisionerImpl | 7 (allocate/deallocate/DB scenarios) | ✓ | 2 (configs typing, getattr→direct) | 9 |
| `package-facades`: Extended facade contents | 6 (layer facade, app facade, notifier, cloud get_rnd_name, persistence, config AzureImageReference) | 5 preserved; 1 replaced | 2 (cloud DTOs, config no longer exports) | 7 |
| `package-facades`: Outside-layer-set exemptions | 7 (outside-set, composition root, facades, client shim, shared kernel, single-layer, daemon launchers) | ✓ | 1 (infra cloud protocols import) | 8 |
| `domain-ports`: MachineGateway port | 11 (list free, run command, etc.) | ✓ | 1 (CloudConfig runtime_checkable) | 12 |
| `domain-ports`: Ports importable | 1 (import ports) | ✓ | 1 (CloudConfig import) | 2 |
| `testing-unit`: Config parsing | 3 (AzureImageReference, VastAI round-trip, ConfigLocal) | ✓ | 5 (DTO frozen, parse_clouds dispatch, username inherits, CloudConfig satisfaction, facade import) | 8 |

Note: The "Config facade exposes AzureImageReference" scenario was intentionally replaced (config facade loses that re-export) — correct by design, not an omission.

**🟡 Minor**: `cloud-providers` delta only lists one of three existing requirements (`Provider code relocated`). The `Support modules relocated` and `Optional provider SDKs handled gracefully` requirements are absent from the delta. If the archive mechanism replaces by requirement header (match → replace, no match → preserve), the other two survive. If it replaces the full file, they are lost. This risk applies to all 5 MODIFIED deltas (see §8).

---

### 4. NEW capability scenario format

**Assessment: All scenarios use exactly `#### Scenario:` (4 hashtags). None use 3 hashtags or bullet format.**

| Spec | Scenarios | Correct format? |
|---|---|---|
| `cloud-config-dtos` | 7 | ✓ All 4 `#` |
| `cloud-config-protocol` | 6 | ✓ All 4 `#` |
| `cloud-config-parsers` | 9 | ✓ All 4 `#` |

---

### 5. SHALL/MUST normative language

**Assessment: No weakening "should"/"may" found in requirements. All use SHALL consistently.**

Every requirement statement across all 8 specs uses SHALL. The only "may" instances are in permissive context (*"may be imported by any layer"* in package-facades — correct, non-normative permission).

---

### 6. Spec–proposal alignment

**Assessment: Complete. Every "What Changes" proposal bullet maps to ≥1 spec requirement.**

| Proposal bullet | Spec(s) |
|---|---|
| Move DTOs to `infra/cloud/cloud_configs.py` as frozen dataclass | `cloud-config-dtos` |
| Drop parser classmethods from DTOs | `cloud-config-dtos` |
| Move parser functions to `entrypoints/config_parser.py` | `cloud-config-parsers` |
| `CLOUD_CONFIG_PARSERS` registry | `cloud-config-parsers` |
| `Config.from_config_parser` delegates to `parse_clouds` | `cloud-config-parsers` |
| `CloudConfig` Protocol in `domain/ports.py` | `cloud-config-protocol`, `domain-ports` |
| Application-layer TYPE_CHECKING switches | `cloud-config-protocol` |
| `infra/cloud/protocols.py` import → intra-package | `package-facades` |
| Provider modules import from infra facade | `cloud-providers` |
| Delete `config/cloud.py`, update facades | `package-facades` |
| `_connect_to_vm` getattr→direct access | `cloud-provisioner` |
| Test migration | `testing-unit` |

**🟡 Minor gap**: The proposal says "Update `entrypoints/di.py` TYPE_CHECKING: `ConfigCloud` → `CloudConfig`" (consumer call-site table). No spec scenario explicitly tests di.py's import. The `cloud-config-protocol` covers application-layer consumers but not entrypoints. The `domain-ports` "CloudConfig import from domain facade" scenario verifies the import resolves, which indirectly covers it. Low risk.

---

### 7. Spec–design alignment (D1–D7)

**Assessment: All 7 design decisions reflected correctly. No contradictions.**

| Decision | Spec coverage | Alignment |
|---|---|---|
| **D1**: Frozen dataclass, no parser methods | `cloud-config-dtos` — `@dataclass(frozen=True)`, no INI methods | ✓ |
| **D2**: Registry in `entrypoints/config_parser.py` | `cloud-config-parsers` — "registry lives at the composition-root layer (entrypoints)" | ✓ |
| **D3**: Lazy import in `Config.from_config_parser` | `cloud-config-parsers` — "lazy import inside the method" | ✓ |
| **D4**: CloudConfig Protocol, 6 fields, structural | `cloud-config-protocol` + `domain-ports` — same 6 fields, `@runtime_checkable`, structural | ✓ |
| **D5**: `protocols.py` import → intra-package | `package-facades` — scenario "infra cloud protocols no longer imports from yascheduler.config" | ✓ |
| **D6**: Provider imports via facade path | `cloud-providers` — "from yascheduler.infra.cloud import ... (R2 facade path)" | ✓ |
| **D7**: `_connect_to_vm` getattr→direct access | `cloud-provisioner` — "config.jump_host or None / config.jump_username or None (direct attribute access)" | ✓ |

---

### 8. Explore-brief coverage

**Assessment: All 5 explore-brief commitments covered across the specs.**

| Explore-brief commitment | Spec(s) | Coverage |
|---|---|---|
| 6 CloudConfig fields (`prefix`, `max_nodes`, `idle_tolerance`, `username`, `jump_username`, `jump_host`) | `cloud-config-protocol` §Req line 9–14; `domain-ports` §Req line 52–58 | ✓ Exact field set |
| Consumer call-site table (10 files) | See §6 mapping | ✓ All covered |
| Registry placement Decision (b) — `entrypoints/config_parser.py` | `cloud-config-parsers` §Req line 9–12 | ✓ |
| Test migration map (6 test files) | `testing-unit` §Req + 5 new scenarios | ✓ |
| Config facade delta + infra.cloud facade gains | `package-facades` — cloud subpackage + config no longer re-export | ✓ |

---

### 9. Cross-spec consistency

**Assessment: Consistent across specs. No contradictions.**

**CloudConfig fields**: Both `cloud-config-protocol` (line 9–14) and `domain-ports` delta (line 52–58) define the same 6 fields with identical names and types. ✓

**Package-facades alignment with proposal**: The delta correctly shows `yascheduler.config` stopping re-exports and `yascheduler.infra.cloud` gaining them. The proposal says "canonical path becomes `from yascheduler.infra.cloud import ...`" — the delta's "Config facade no longer re-exports" scenario (ImportError) enforces this. ✓

**`cloud-config-dtos` ↔ `cloud-providers` alignment**: Both specify `@dataclass(frozen=True)`, no parser methods. ✓

**`cloud-config-protocol` ↔ `domain-ports` alignment**: Both define `CloudConfig` in `domain/ports.py`, structural, 6 fields. ✓

**`cloud-config-parsers` ↔ `cloud-config-dtos` alignment**: Parsers produce DTOs; DTOs have no parser methods. Consistent. ✓

---

### 10. Additional observations

**🟡 `package-facades` "Extended facade contents": unchanged facade descriptions not carried forward (same as §2 Issue A)**

The delta body omits the unchanged `yascheduler/infra/__init__.py`, `application/__init__.py`, `notifier/__init__.py`, and `persistence/__init__.py` bullet lists. Even if the archive mechanism preserves them by requirement header, the delta format does not signal intent — a future reader cannot tell whether these were intentionally dropped or accidentally omitted. The `yascheduler/config/__init__.py` bullet in the existing spec lists `AzureImageReference` from `.cloud`; the delta replaces it with `SHALL NO LONGER re-export [...]`. The replacement is explicit and correct, but the absence of the other four facades creates ambiguity.

**🟡 `cloud-providers` delta VastAI scenario gap**: The existing spec has no VastAI accessibility scenario (only Azure, Hetzner, UpCloud). The delta does not add one. This is not a P3 regression (P3 tests VastAI in the parser path via `cloud-config-parsers` and `testing-unit`), but if the `cloud-providers` spec is meant to enumerate all supported providers, VastAI is missing. Pre-existing issue, not P3's fault — noted for optional cleanup.

**🟡 `testing-unit` delta — P1 regression scenario renamed but covered**: The existing spec's "Config.from_config_parser recognises `[cloud.vastai]` sections and produces a `ConfigCloudVastAI` entry" (the P1 band-aid) is updated to "Config.from_config_parser recognises `[cloud.vastai]` sections via the `CLOUD_CONFIG_PARSERS` registry (regression coverage; the prior P1 band-aid of appending to the `cloud_variants` tuple is replaced)". The new scenario "VastAI cloud section round-trips through Config.from_config_parser" maintains the P1 regression coverage. ✓

---

### Summary

| Severity | Count | Items |
|---|---|---|
| 🔴 Blocking | 2 | (A) `package-facades` "Extended facade contents" body omits 4 unchanged facade definitions — archive would lose them; (B) `package-facades` "Outside-layer-set exemptions" body omits `yascheduler.data`, `yascheduler.client`, and composition root note — archive would lose them |
| 🟡 Addressed / Minor | 3 | `entrypoints/di.py` import change not explicitly tested; unchanged requirements absent from all 5 MODIFIED deltas (archive-tool convention dependency); `cloud-providers` VastAI scenario pre-existing gap |
| ✅ Correct | 8 | Headers match (7/7); scenarios preserved within requirements; NEW scenario format (4 `#`); SHALL language clean; proposal alignment complete; design alignment (D1–D7); explore-brief coverage; cross-spec consistency |

**Recommendation: REQUEST CHANGES** — Two 🔴 blocking issues in `package-facades` delta (requirement body incompleteness for "Extended facade contents" and "Outside-layer-set exemptions"). The other deltas are structurally sound. Fix the two body-completeness issues before archiving, or document the archive-tool merge convention explicitly in the delta format to clarify that unchanged sections survive.

## specs Round 2 — 2026-06-25

Reviewer: code-review-agent
Scope: package-facades/spec.md (fix verification), 7 unchanged spec files (regression check)
Method: Direct file reads, codebase cross-reference

---

### 1. 🔴 Issue A — "Extended facade contents" body completeness

**Verdict: FIXED ✓**

The delta now includes all 6 facade groups:
- `yascheduler/infra/__init__.py` — 7 bullet items (SSHMachineGateway, CloudProvisionerImpl, CloudAdapter, apply_schema, webhook_handler, PostgresUnitOfWork, list_private_keys) ✓
- `yascheduler/application/__init__.py` — 4 bullet items (AbstractUnitOfWork, Orchestrator, MessageBus, submit_task) ✓
- `yascheduler/infra/notifier/__init__.py` — 1 bullet (webhook_handler) ✓
- `yascheduler/infra/cloud/__init__.py` — 3 bullets: get_rnd_name + cloud DTO re-exports (NEW) + existing re-exports preserved ✓
- `yascheduler/infra/persistence/__init__.py` — 2 bullets (apply_schema, PostgresUnitOfWork) + existing preserved ✓
- `yascheduler/config/__init__.py` — 6 bullets: Config/ConfigDb/ConfigLocal/ConfigRemote unchanged + AzureImageReference NO LONGER + ConfigCloud* NO LONGER ✓

All scenarios preserved (6 existing → 1 replaced, 1 new added = 7 total). The "Config facade exposes AzureImageReference" scenario was correctly replaced by "Config facade no longer re-exports cloud config DTOs".

No facade definitions would be lost at archive. **Resolved.**

---

### 2. 🔴 Issue B — "Outside-layer-set exemptions" body completeness

**Verdict: FIXED ✓**

The delta now includes:
- `yascheduler.config` exemption bullet with P3-addition sentence ✓
- `yascheduler.data` exemption bullet ✓
- `yascheduler.client` exemption bullet ✓
- Composition root relocation paragraph (yascheduler.di → yascheduler.entrypoints.di) ✓
- `yascheduler.shared` kernel definition paragraph ✓
- All 7 existing scenarios ✓
- 1 new "infra cloud protocols no longer imports from yascheduler.config" scenario ✓

All 3 exemption bullets present. The composition-root-relocation note is present. The scenario text's `yascheduler.data` and `yascheduler.client` references are now supported by the requirement body. **Resolved.**

---

### 3. New finding introduced by the fix

🟡 **`package-facades` "Extended facade contents": `list_private_keys` in infra facade is ahead of committed state**

The delta's `yascheduler/infra/__init__.py` section includes `list_private_keys` from `.ssh` (line 18):

    - `list_private_keys` from `.ssh` (consumed by the composition root ...; ssh-keys-extraction-vastai-parser-fix).

This re-export exists in the **working tree** (`yascheduler/infra/__init__.py` line 29, uncommitted) and was added by a prior change (`ssh-keys-extraction-vastai-parser-fix`). However:

- The **committed code** at HEAD does NOT have `list_private_keys` in `yascheduler/infra/__init__.py`.
- The **main spec** at HEAD (`openspec/specs/package-facades/spec.md`) does NOT mention `list_private_keys`.

The delta is forward-looking — it assumes the main spec will already contain `list_private_keys` by the time P3 is archived. If `ssh-keys-extraction-vastai-parser-fix` is archived before P3, this is correct. If P3 is archived first, the P3 delta would add `list_private_keys` to the main spec (scope creep).

This is not a blocking issue (additive, not data-losing) but should be noted for sequencing awareness during implementation.

No other differences from the committed spec were found in the infra facade. All other unchanged facade sections match the committed spec content.

---

### 4. Other 7 spec files — regression check

All 7 files are unchanged from Round 1 (no new modifications):

| Spec file | Round 1 status | Current | Assessment |
|---|---|---|---|
| `cloud-config-dtos` (NEW) | Clean, 7 scenarios | Unchanged | ✅ Still clean |
| `cloud-config-protocol` (NEW) | Clean, 6 scenarios | Unchanged | ✅ Still clean |
| `cloud-config-parsers` (NEW) | Clean, 9 scenarios | Unchanged | ✅ Still clean |
| `cloud-providers` (MODIFIED) | Clean, 5 scenarios, headers match | Unchanged | ✅ Still clean |
| `cloud-provisioner` (MODIFIED) | Clean, 9 scenarios, headers match | Unchanged | ✅ Still clean |
| `domain-ports` (MODIFIED) | Clean, 12 scenarios, headers match | Unchanged | ✅ Still clean |
| `testing-unit` (MODIFIED) | Clean, 8 scenarios, headers match | Unchanged | ✅ Still clean |

No new issues found in any of the 7 files. Headers still match, scenarios still correct, SHALL language clean.

---

### Summary

| Severity | Count | Items |
|---|---|---|
| 🔴 Fixed | 2 | Issue A (Extended facade contents completeness); Issue B (Outside-layer-set exemptions completeness) |
| 🔴 Outstanding | 0 | |
| 🟡 Addressed / Minor | 1 | `list_private_keys` in infra facade section is ahead of committed spec — sequencing note only, not blocking |

All 🔴 items are resolved. The 2 original blocking issues are fixed. No new blocking issues exist.

**Recommendation: APPROVE** — single-round pass rule applies (empty 🔴 Outstanding section).

## tasks Round 1 — 2026-06-25

Reviewer: code-review-agent
Scope: tasks.md vs proposal.md (frozen), design.md (frozen), 8 delta specs, explore-brief.md, docs/config-layer-split-plan.md, current codebase (P2 implemented)
Method: Full line-by-line mapping of tasks → spec requirements → design decisions → explore-brief commitments

---

### 1. Spec coverage — each requirement has ≥1 implementing task

**Assessment: Complete. Every spec requirement in all 8 delta specs maps to ≥1 task.**

| Spec | Reqs | Scenarios | Tasks that implement | Coverage |
|---|---|---|---|---|
| `cloud-config-dtos` | 1 | 7 | 1.1–1.8 (create file, 5 DTOs, union, verify) | ✓ Full |
| `cloud-config-protocol` | 1 | 6 | 3.1–3.3 (define Protocol, re-export, verify), 8.1–8.2 (application types), 11.11 (end-to-end verify) | ✓ Full |
| `cloud-config-parsers` | 3 | 9 | 2.1–2.12 (registry + parses + delegation), 4.1 (lazy import), 4.3 (MODULE_CONTRACT) | ✓ Full |
| `cloud-providers` | 1 | 5 | 7.5–7.8 (provider import switches) | ✓ Full |
| `cloud-provisioner` | 1 | 9 | 7.4 (configs typing), 7.9 (D7 getattr cleanup), 10.3, 10.4 (test migration) | ✓ Full |
| `package-facades` | 2 | 9 | 5.1–5.2 (config facade loses), 6.1–6.2 (cloud facade gains), 7.1 (protocols.py intra-package) | ✓ Full |
| `domain-ports` | 2 | 12 | 3.1–3.2 (CloudConfig in ports + domain facade), 3.3 verify | ✓ Full |
| `testing-unit` | 1 | 8 | 10.1–10.8 (test migration per test file), 11.11 (structural satisfaction) | ✓ Full |

**No spec requirement without an implementing task found.**

---

### 2. Design decision coverage (D1–D7)

| Decision | Tasks | Status |
|---|---|---|
| **D1**: Frozen `@dataclass(frozen=True)`, no parser methods, parser-side validation | 1.2–1.6 (frozen fields), 1.8 (verify), 2.2–2.8 (parser-side validators), 2.10–2.11 (parse_clouds/parse_cloud_section) | ✓ |
| **D2**: Registry in `entrypoints/config_parser.py` | 2.9 (`CLOUD_CONFIG_PARSERS` dict), 2.10 (dispatch via `CLOUD_CONFIG_PARSERS[prefix]`) | ✓ |
| **D3**: Lazy-import cloud assembly in `Config.from_config_parser` | 4.1 (lazy import inside method body; TODO comment for P4) | ✓ |
| **D4**: `CloudConfig` Protocol, 6 fields (`prefix`, `max_nodes`, `idle_tolerance`, `username`, `jump_username`, `jump_host`), structural | 3.1 (Protocol in ports.py + field set + START_CONTRACT), 3.3 (structural satisfaction assertion) | ✓ |
| **D5**: `protocols.py` intra-package import (`from .cloud_configs import ConfigCloud`) | 7.1 (intra-package relative import + MODULE_CONTRACT DEPENDS) | ✓ |
| **D6**: Provider imports via facade path (`from yascheduler.infra.cloud import ...`) | 7.5–7.8 (az, hetzner, upcloud, vastai each switch to facade import) | ✓ |
| **D7**: Optional `getattr`→direct access in `_connect_to_vm` | 7.9 (`config.jump_host or None` / `config.jump_username or None`; function contract INPUTS note) | ✓ |

All 7 design decisions implemented. No contradiction between tasks and design.

---

### 3. Explore-brief coverage

**Consumer call sites (10 production files):**

| File in explore-brief table | Task | Status |
|---|---|---|
| `infra/cloud/protocols.py:37` | 7.1 | ✓ |
| `infra/cloud/protocols.py:41-45` (TypeVar ×3) | implicit — unchanged (bound to relocated Union) | ✓ |
| `infra/cloud/adapters.py:40` | 7.2 | ✓ |
| `infra/cloud/provider_selection.py:27` | 7.3 | ✓ |
| `infra/cloud/manager.py:49-54` | 7.4 (split: ConfigCloud → .cloud_configs; EngineRepository stays from domain) | ✓ |
| `infra/cloud/providers/az.py:84-86` | 7.5 (facade path) | ✓ |
| `infra/cloud/providers/hetzner.py:53` | 7.6 | ✓ |
| `infra/cloud/providers/upcloud.py:48` | 7.7 | ✓ |
| `infra/cloud/providers/vastai.py:48` | 7.8 | ✓ |
| `application/deallocate_nodes.py:31` | 8.1 | ✓ |
| `application/orchestrator.py:54` | 8.2 (split: CloudConfig + EngineRepository) | ✓ |
| `entrypoints/di.py:61` | 8.3 (split: CloudConfig + EngineRepository) | ✓ |
| `config/config.py:32-38` | 4.1–4.2 (delete block + replacement import) | ✓ |
| `config/__init__.py:42-49` | 5.2 (drop cloud re-exports) | ✓ |

**Test migration entries (6 test files):**

| Test file | Task | Status |
|---|---|---|
| `tests/unit/test_config.py:46-58` | 10.1 | ✓ |
| `tests/unit/test_config.py` cloud-parsing | 10.2 | ✓ |
| `tests/unit/test_provider_selection.py:32` | 10.3 | ✓ |
| `tests/unit/test_application_use_cases.py:52` | 10.4 | ✓ |
| `tests/unit/test_di.py:31` | 10.5 | ✓ |
| `tests/unit/test_application_orchestrator.py:54` | 10.6 | ✓ |
| `MagicMock(spec=ConfigCloud)` audit | 10.7 | ✓ |
| Zero `from yascheduler.config` cloud imports in tests | 10.8 (grep assertion) | ✓ |

**Registry placement Decision (b):** Task 2.9 places `CLOUD_CONFIG_PARSERS` in `entrypoints/config_parser.py` (R3-legal, matches Decision b). The explore-brief's stale table cell (`CLOUD_CONFIG_PARSERS` target was `infra/cloud/cloud_configs.py`) has been corrected since the proposal review — current explore-brief line 63 correctly shows `entrypoints/config_parser.py`. ✓

---

### 4. P2 composition — handle "P2 not yet implemented" case

**Assessment: Correctly handled. P2 is already implemented, but the tasks handle both scenarios.**

P2 status: **IMPLEMENTED** in current codebase:
- `entrypoints/config_parser.py` exists with engine parsers (177 lines)
- `config/config.py:32` imports `EngineRepository` from `yascheduler.domain` (P2 migrated)
- `config/__init__.py` no longer re-exports engine types (P2 removed them)
- `infra/cloud/manager.py:54` imports `EngineRepository` from `yascheduler.domain` (P2 migrated)
- `application/orchestrator.py:54` imports `EngineRepository` from `yascheduler.domain` (P2 migrated)
- `entrypoints/di.py:61` imports `EngineRepository` from `yascheduler.domain` (P2 migrated)

Tasks that handle the P2-not-done path:

| Task | P2-done branch | P2-not-done branch | Correctness |
|---|---|---|---|
| **2.1** | Extend existing `entrypoints/config_parser.py` — do not duplicate MODULE_CONTRACT | Create it with cloud-only MODULE_CONTRACT | ✓ (P2 is done, so extension path) |
| **7.4** (manager.py) | `EngineRepository` already from `yascheduler.domain` — no-op for P3 | Stay from `yascheduler.config` | ✓ |
| **8.2** (orchestrator.py) | `EngineRepository` already from `yascheduler.domain` — no-op for P3 | Stay from `yascheduler.config` | ✓ |
| **8.3** (di.py) | `EngineRepository` already from `yascheduler.domain` — no-op for P3 | Stay from `yascheduler.config` | ✓ |

**Merge is clean in both directions**: P3 only touches `ConfigCloud`/`CloudConfig` parts of imports; `EngineRepository` parts are untouched by P3. Git merge would auto-resolve.

---

### 5. Task granularity — ≤2 hours per task

**Assessment: All tasks are ≤2 hours. No oversized or vague tasks.**

Largest individual task estimation:
- **Task 1.3** (ConfigCloudAzure, 17 fields): mechanical dataclass translation from 22-line attrs block. ≤30 min.
- **Task 2.4** (`_parse_azure_section`): copy+adapt ~40 lines from config/cloud.py. ≤45 min.
- **Task 2.11** (`parse_clouds`): implement ~20 lines of logic. ≤30 min.
- **Task 7.9** (D7 getattr→direct): changing 2 lines + contract note. ≤10 min.
- **Task 10.2** (cloud-parsing tests): migrate `from_config_parser_section` calls to `parse_cloud_section`. ~45 min.
- **Task 10.7** (MagicMock audit): grep + inspect ~5 test files. ≤45 min.

No task group exceeds 2 hours if each subtask is done serially. The breakdown into individual file-level changes (7.1–7.8 = 8 separate import switches, each a single file edit) is appropriate.

---

### 6. Verification completeness

**Umbrella plan §7 P3 verification covered:**

| Umbrella plan requirement | Task(s) | Status |
|---|---|---|
| `uv run pytest -m unit` | 11.1 | ✓ |
| `uv run pytest -m integration` | 11.2 | ✓ |
| `uv run lint-imports` | 11.5 | ✓ |
| `openspec validate --all --json` | 11.7 | ✓ |

**Additional verification tasks:**

| Check | Task | Rationale |
|---|---|---|
| `uv run ruff check .` | 11.3 | Standard project CI |
| `uv run ruff format --check .` | 11.4 | Standard project CI |
| `python3 scripts/grace_check.py` | 11.6 | GRACE-lite compliance per AGENTS.md |

**BREAKING change grep assertions:**

| Breaking change | Grep pattern | Task |
|---|---|---|
| No `from yascheduler.config import ConfigCloud*` | `from yascheduler.config import.*ConfigCloud\|from yascheduler.config.cloud\|from yascheduler.config import.*AzureImageReference` | 11.8 |
| No `from_config_parser_section`/`get_valid_config_parser_fields` on cloud DTOs | `from_config_parser_section\|get_valid_config_parser_fields` on `ConfigCloud*` | 11.9 |
| `config/cloud.py` deleted | `attrs` in `config/cloud.py` + `ls` verification | 11.10 |

All umbrella plan and BREAKING-change checks are covered. ✓

---

### 7. GRACE-lite compliance

**Task 9 group — knowledge graph updates:**

| Task | Action | Status |
|---|---|---|
| 9.1 | Add `M-CLOUD-CONFIGS` element (TYPE=DATA_LAYER, STATUS=implemented) with `<purpose>`, `<path>`, `<depends>` (M-CLOUD-PROTOCOLS, M-SHARED), annotations (4 × class-*, type-ConfigCloud) | ✓ |
| 9.2 | Remove `M-CONFIG-CLOUD` element | ✓ |
| 9.3 | Add `protocol-CloudConfig` annotation to `M-DOMAIN-PORTS` | ✓ |
| 9.4 | Update `M-ENTRYPOINTS-CONFIG-PARSER` annotations + `<depends>` (add M-CLOUD-CONFIGS) | ✓ |
| 9.5 | Repoint CrossLinks from M-CONFIG-CLOUD → M-CLOUD-CONFIGS or M-DOMAIN-PORTS | ✓ |
| 9.6 | Update `M-CONFIG` DEPENDS (drop M-CONFIG-CLOUD) | ✓ |

**Code-creation tasks with GRACE-lite contracts:**

| File | MODULE_CONTRACT | MODULE_MAP | CHANGE_SUMMARY | Task | Status |
|---|---|---|---|---|---|
| `infra/cloud/cloud_configs.py` (new) | ✓ PURPOSE: Cloud provider config DTOs... | ✓ | ✓ LAST_CHANGE: v1.0.0 - Relocate... | 1.1 | ✓ |
| `entrypoints/config_parser.py` (extend) | ✓ PURPOSE extends to include cloud... | ✓ (add parse_cloud_section, etc.) | ✓ (add CHANGE_SUMMARY for P3) | 2.1 | ✓ |
| `domain/ports.py` (extend) | ✓ START_CONTRACT: CloudConfig block | implicit | implicit (CHANGE_SUMMARY in ports.py) | 3.1 | ✓ |
| `config/config.py` (modify) | ✓ Update DEPENDS and CHANGE_SUMMARY | ✓ | ✓ | 4.3 | ✓ |
| `config/__init__.py` (modify) | ✓ Update SCOPE, DEPENDS, CHANGE_SUMMARY | ✓ | ✓ | 5.3 | ✓ |
| `infra/cloud/__init__.py` (modify) | ✓ Update SCOPE, DEPENDS, CHANGE_SUMMARY | ✓ | ✓ | 6.2 | ✓ |
| `infra/cloud/*.py` (modify) | ✓ Update DEPENDS/LINKS per task | — | — | 7.x | ✓ |
| `application/*.py` (modify) | ✓ Update DEPENDS per task | — | — | 8.x | ✓ |

---

### Findings

#### 🟡 Finding 1: Knowledge graph `<depends>` not fully updated for all affected modules

Task 9.5 repoints CrossLinks but the `<depends>` elements in the knowledge graph XML for several modules still reference `M-CONFIG-CLOUD`. These are not explicitly mentioned in the task group 9 nor covered by task 7.x file-level contract updates (which update MODULE_CONTRACT DEPENDS in the Python files, not the knowledge graph XML).

**Affected knowledge graph entries:**
- `M-CLOUD-PROTOCOLS` (line 761): `<depends>M-CONFIG-CLOUD</depends>` → should be `M-CLOUD-CONFIGS`
- `M-CLOUD-PROVISIONER` (line 725): `<depends>...M-CONFIG-CLOUD</depends>` → should add `M-CLOUD-CONFIGS`, drop `M-CONFIG-CLOUD`
- `M-CLOUD-PROVIDERS` (line 747): `<depends>M-CONFIG-CLOUD, ...</depends>` → should be `M-CLOUD-CONFIGS`
- `M-CONFIG-HUB` (line 662): `<depends>...M-CONFIG-CLOUD</depends>` → drop `M-CONFIG-CLOUD`
- `M-CLOUD-ADAPTERS-NEW` (line 786): currently `<depends>M-CLOUD-PROVIDERS, M-CLOUD-PROTOCOLS</depends>` — no M-CONFIG-CLOUD, but its code imports `ConfigCloud` from `yascheduler.config` (line 40). After P3, this becomes intra-package, so `<depends>` should gain `M-CLOUD-CONFIGS`.

**Fix:** Add a task 9.7 to update `<depends>` on all affected modules:
- `M-CLOUD-PROTOCOLS`: `M-CONFIG-CLOUD` → `M-CLOUD-CONFIGS`
- `M-CLOUD-PROVISIONER`: add `M-CLOUD-CONFIGS`, drop `M-CONFIG-CLOUD`
- `M-CLOUD-PROVIDERS`: `M-CONFIG-CLOUD` → `M-CLOUD-CONFIGS`
- `M-CONFIG-HUB`: drop `M-CONFIG-CLOUD`
- `M-CLOUD-ADAPTERS-NEW`: add `M-CLOUD-CONFIGS`

The `grace_check.py` (task 11.6) would likely catch these inconsistencies, but the tasks should explicitly cover the `<depends>` updates rather than leaving them as discovery items during verification.

---

#### 🟡 Finding 2: Task 2.4–2.7 reference "all 4 valid field lists" before `cloud_valid_fields` is created (task 2.8)

Task 2.4 says the Azure parser should call `warn_unknown_fields([...all 4 valid field lists...], sec)`. Task 2.8 (`cloud_valid_fields`) is listed after 2.4–2.7, creating a forward-reference dependency.

The implementer can reorder (do 2.8 before 2.4) or inline the field lists directly. Not a blocking issue — any Python developer would resolve this naturally — but the task ordering creates unnecessary friction.

**Fix:** Move task 2.8 to before tasks 2.4–2.7 in the checklist, or change 2.4 to say "collect valid fields via `dataclasses.fields(ConfigCloudX)`" (which doesn't depend on 2.8).

---

#### 🟡 Finding 3: Task 9 does not explicitly update `M-APPLICATION-DEALLOCATE` and `M-APPLICATION-ORCHESTRATOR` knowledge graph `<depends>`

Task 9.5 repoints CrossLinks but the `<depends>` on these application-layer modules in the knowledge graph still references M-CONFIG-CLOUD:
- `M-APPLICATION-DEALLOCATE` (line 475): `<depends>...M-CONFIG-CLOUD...</depends>` — after P3, application types against `CloudConfig` Protocol, so `<depends>` should gain `M-DOMAIN-PORTS` and drop `M-CONFIG-CLOUD`.
- `M-APPLICATION-ORCHESTRATOR` (line 494): `<depends>...M-CONFIG...</depends>` — currently does not reference M-CONFIG-CLOUD directly (it references M-CONFIG as a whole). After P3, orchestrator no longer imports ConfigCloud from config, so the Config dependency remains (for `Config`), but the cloud config dependency is via `CloudConfig` from domain. `M-DOMAIN-PORTS` is already in the depends list. So this may be correct already.

Actually, looking more carefully: `M-APPLICATION-ORCHESTRATOR` `<depends>` (line 494) doesn't list `M-CONFIG-CLOUD`. It lists `M-CONFIG` (the aggregate). After P3, the orchestrator still imports `Config` from `yascheduler.config` (TYPE_CHECKING), so `M-CONFIG` stays. The `CloudConfig` Protocol comes from `M-DOMAIN-PORTS`, which is already in the depends. So `M-APPLICATION-ORCHESTRATOR` is fine.

For `M-APPLICATION-DEALLOCATE` (line 475): `<depends>...M-CONFIG-CLOUD</depends>`. After P3, `deallocate_nodes.py` imports `CloudConfig` from `yascheduler.domain`, not `ConfigCloud` from config. So `M-CONFIG-CLOUD` should be removed and `M-DOMAIN-PORTS` added. But `M-DOMAIN-PORTS` is already not in the depends. Actually, `M-APPLICATION-DEALLOCATE` already depends on `M-DOMAIN-PORTS` for the `CloudProvisioner` and `MachineGateway` Protocols. So adding `M-DOMAIN-PORTS` again is redundant. The fix is just to drop `M-CONFIG-CLOUD`.

For `M-ENTRYPOINTS-DI` (line 509): `<depends>...M-CONFIG...</depends>`. After P3, `di.py` still imports `Config` from `yascheduler.config` but imports `CloudConfig` from `yascheduler.domain`. `M-DOMAIN-PORTS` is not in the depends but the di depends are: `M-APPLICATION-ORCHESTRATOR, M-APPLICATION-SUBMIT, M-APPLICATION-UOW, M-PERSISTENCE-UOW, M-CONFIG, M-SSH-GATEWAY, M-SSH-KEYS, M-CLOUD-PROVISIONER, M-APPLICATION-MESSAGE-BUS, M-NOTIFIER-WEBHOOK, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE, M-APPLICATION-ALLOCATION-TRACKER`. It doesn't list M-CONFIG-CLOUD, so no change needed. But the file-level MODULE_CONTRACT DEPENDS should be checked.

This is a minor gap, captured by Finding 1's broader observation.

---

#### 🟡 Finding 4: `di.py` MODULE_CONTRACT DEPENDS may need `M-DOMAIN-PORTS` added

Task 8.3 changes the TYPE_CHECKING import `ConfigCloud` → `CloudConfig` (from `yascheduler.domain`). The current `di.py` MODULE_CONTRACT DEPENDS (line 6) does not list `M-DOMAIN-PORTS`. Since `CloudConfig` is a Port Protocol in `domain/ports.py`, the DEPENDS should include `M-DOMAIN-PORTS`. Task 8.3 says "Update the `make_daemon` contract INPUTS note" but does not explicitly say to update MODULE_CONTRACT DEPENDS.

**Fix:** Task 8.3 should also update `di.py` MODULE_CONTRACT DEPENDS to add `M-DOMAIN-PORTS` (for `CloudConfig`).

---

### Summary

| Severity | Count | Items |
|---|---|---|
| 🔴 Blocking | 0 | |
| 🟡 Addressed / Minor | 4 | (1) Knowledge graph `<depends>` not fully updated for M-CLOUD-PROTOCOLS, M-CLOUD-PROVISIONER, M-CLOUD-PROVIDERS, M-CONFIG-HUB, M-CLOUD-ADAPTERS-NEW; (2) Task 2.8 (cloud_valid_fields) sequenced after its consumers 2.4–2.7; (3) Same knowledge graph `<depends>` gap for M-APPLICATION-DEALLOCATE; (4) `di.py` MODULE_CONTRACT DEPENDS missing M-DOMAIN-PORTS |
| ✅ Correct | 7 | Spec coverage (all 8 specs mapped); Design decisions D1–D7 all implemented; Explore-brief consumer table (14/14) + test map (6/6) all covered; P2 composition handles both orderings; All tasks ≤2 hours; Verification covers umbrella plan + BREAKING checks; GRACE-lite contracts on all new/modified files |

No 🔴 blocking issues found. The 4 🟡 items are documentation/ordering gaps that do not prevent implementation.

**Recommendation: APPROVE WITH NOTES** — Address the 4 🟡 items during implementation:
1. Add task 9.7 to update knowledge graph `<depends>` for M-CLOUD-PROTOCOLS, M-CLOUD-PROVISIONER, M-CLOUD-PROVIDERS, M-CONFIG-HUB, M-CLOUD-ADAPTERS-NEW, M-APPLICATION-DEALLOCATE.
2. Reorder task 2.8 before 2.4–2.7, or reword 2.4 to use `dataclasses.fields()` directly.
3. Same as #1 (covered by adding 9.7).
4. Add "Update MODULE_CONTRACT DEPENDS (add M-DOMAIN-PORTS)" to task 8.3.
