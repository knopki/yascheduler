# Review Log — move-cloud-package-upgrade

## proposal Round 1 — 2026-07-01

### Reviewer: @k-reviewer (baseline: explore-brief.md)
**Verdict: APPROVE WITH NOTES**

### 🟢 Looks good
- All 10 explore-brief commitments reflected, no contradictions.
- Proposal structure complete (Why / What Changes / Capabilities / Impact).
- Modified Capabilities list verified accurate AND complete at 3
  (`config-value-objects`, `cloud-config`, `cloud-provisioner`).
  `config-parser-assembly` confirmed NOT touched.
- Legacy-key `ConfigWarning` consequence correctly derived.
- "Not on Protocol" → `config` param typed `ConfigCloud` (concrete Union):
  typing consequence respected.
- cloud-provisioner's existing requirement "Cloud-init package_upgrade sourced
  from local config" (spec.md:274-293) correctly targeted for rewrite.

### 🟡 Addressed (applied as declarative refinements, no unfreeze)
- AGENTS.md "Public interface stability" tension → added a sentence in Impact
  citing the stability rule + the pre-release exemption.
- test_config.py coverage under-specified → named the absent-key-defaults-`True`
  regression-guard case in proposal.
- Knowledge-graph modules under-listed → added `M-CLOUD-MANAGER` (contract LINKS
  shift manager.py:301, `<depends>`/`CrossLink` edges follow; private method but
  GRACE-lite rule 3 applies).

### 🔴 Outstanding
- None.

**Frozen.** Moving to design batch.

## design Round 1 — 2026-07-01

### Reviewer: @k-reviewer-fast (baseline: explore-brief.md + frozen proposal.md)
**Verdict: APPROVE**

### 🟢 Looks good
- All 10 explore-brief commitments captured; no decision-level contradiction
  with frozen proposal.md.
- Typing-consequence trap captured (Decision 3): `config` param MUST be
  `ConfigCloud` (concrete Union), not `CloudConfig` (Protocol), or
  `config.package_upgrade` won't type-resolve.
- Auto-registration verified: `cloud_valid_fields` introspection →
  `{prefix}_package_upgrade` registers with no manual edit; `_ALL_CLOUD_VALID_FIELDS`
  follows.
- Removal side-effect verified: `_local_valid_fields()` introspection drops the
  key → legacy `[local] cloud_package_upgrade` becomes `ConfigWarning`.
- `allocate` resolves `config` at manager.py:155, before the call at :170 →
  minimal non-breaking threading.

### 🟡 Addressed (declarative refinement, no unfreeze)
- Added a Risk note clarifying `CloudInitConfig.package_upgrade` defaults `False`
  vs DTO default `True` — no runtime effect (DTO value always passed explicitly).

### 🔴 Outstanding
- None.

**Frozen.** Moving to specs batch.

## specs Round 1 — 2026-07-01

### Reviewer: @k-reviewer-fast (baseline: explore-brief + frozen proposal + frozen design)
**Verdict: APPROVE**

### 🟢 Looks good
- config-value-objects MODIFIED: header matches original, 3 surviving scenarios
  preserved verbatim, `cloud_package_upgrade` dropped from field enumeration,
  two new scenarios (no-field + legacy-key-warns) correct.
- cloud-config ADDED: 6 scenarios cover all design commitments (default True on
  4 DTOs, accepts False, NOT on Protocol, per-provider mixed parse, absent→True,
  no unknown-field warning). No contradiction with existing "Cloud config DTOs"
  or "CloudConfig structural Protocol" requirements.
- cloud-provisioner REMOVED+ADDED: REMOVED header matches main spec line 274
  exactly, has Reason+Migration; ADDED types `config: ConfigCloud` (not Protocol),
  covers True/False propagation, allocate pass-through, type annotation, default.
- Cross-spec consistency: field name `package_upgrade`, default True, NOT on
  Protocol, `ConfigCloud` Union in signature — uniform everywhere.
- Validate passes (`openspec validate move-cloud-package-upgrade` → valid: True,
  issues: none).

### 🟡 Addressed
- None needed.

### 🔴 Outstanding
- None.

**Frozen.** Moving to tasks batch.

## tasks Round 1 — 2026-07-01

### Reviewer: @k-reviewer-fast (baseline: all frozen artifacts)
**Verdict: APPROVE WITH NOTES**

### 🟢 Looks good
- Tasks 1..6 (now 1..7) cover every change from frozen artifacts: LocalSettings
  field removal (1), add to 4 DTOs (2), parser removal+per-prefix (3), manager
  signature+call-site (4), tests (5).
- No contradiction with frozen artifacts: `package_upgrade` name, NOT on
  Protocol, `config: ConfigCloud` param, default True, no `_CLOUD_FIELD_RULES`
  edit.
- Dependency ordering sound (DTO field before parser; manager sig before
  call-site; impl before tests).
- Knowledge-graph task covers M-DOMAIN-SETTINGS, M-CLOUD-CONFIGS,
  M-CLOUD-MANAGER + the CrossLink at ~line 1266.

### 🟡 Addressed (declarative refinements, no unfreeze)
- 3.1: removed the broken/no-op `python -c` verify snippet; verification now
  points at the unit test in 5.2.
- 5.2: added a `pytest.warns(None)` guard (new key does NOT warn) and a
  Protocol-negative assertion (`package_upgrade` not on `CloudConfig`).
- **User input (not a review finding)**: added Task Group 6 "User-facing docs:
  README.md" — document `*_package_upgrade` in the `[clouds]` common-keys list
  (~README lines 257-285). `[local]` never documented the key (prior
  add-hetzner-live-e2e omitted it), so nothing to remove there. Renumbered the
  knowledge-graph + validation group to 7.

### 🔴 Outstanding
- None.

**Frozen.** All artifacts complete; `openspec status` reports `isComplete: True`.
