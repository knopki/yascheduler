# Review Log — relocate-manage-node-command

## proposal Round 1 — 2026-06-25

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md`
Frozen artifacts: none (batch 1)

### BLOCKER Fixed
- **Stale CrossLink quote.** The proposal quoted the `M-CLI-COMMANDS → M-DI`
  CrossLink as `relation="uses make_cli_deps for CLI submit; make_daemon for
  daemon entry"`, but the current `docs/knowledge-graph.xml:968` already reads
  `relation="uses make_daemon for daemon entry"` — the `CLI submit` clause was
  dropped by the archived `relocate-submit-command`. Fixed: re-quoted the
  actual current state and adjusted the surrounding prose ("covers daemon
  only; the `CLI submit` clause was already dropped by the archived
  `relocate-submit-command`"). Conclusion ("this change does NOT amend it")
  was already correct; only the factual premise was wrong.

### MAJOR Fixed
- **Missing explicit `make_cli_deps(config)` call.** The What Changes section
  described `SSHMachineGateway()` construction and UoW passing but never
  stated that `manage_node()` calls `Config.from_config_parser(CONFIG_FILE)`
  and `make_cli_deps(config)` to obtain `CLIDeps.uow_factory`. All three
  predecessors state this explicitly. Fixed: expanded the "Gateway
  instantiation moved" bullet to spell out the `Config.from_config_parser` →
  `make_cli_deps(config)` → `deps.uow_factory()` chain.

### Outstanding
- None. Round 2 to confirm.

## proposal Round 2 — 2026-06-25

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md`
Frozen artifacts: none (batch 1)

### Verified
- Fix 1 (BLOCKER): `proposal.md:194-199` now quotes the actual KG state
  (`relation="uses make_daemon for daemon entry"`, no `CLI submit` clause).
  Verified against `docs/knowledge-graph.xml:968`.
- Fix 2 (MAJOR): `proposal.md:137-139` now spells out
  `Config.from_config_parser` → `make_cli_deps(config)` → `deps.uow_factory()`.

### Outstanding
- None.

### Status
- **FROZEN.** Batch 1 (`proposal.md`) passes round 2; proceed to batch 2
  (`design.md`).

## design Round 1 — 2026-06-25

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + frozen `proposal.md`
Frozen artifacts: `proposal.md`

### Verdict
APPROVE WITH NOTES — no BLOCKER, no MAJOR. Three MINOR findings, all
declarative gaps (no decision-level changes).

### MINOR Fixed
- **D2 HostSpec table omitted port range.** Added `validated 1..65535` to
  the `port` row and `>= 0 enforced` to the `ncpus` row, so an implementer
  reading only D2 sees the validation constraints without cross-referencing
  the brief.
- **Description update not captured in Decisions.** Added D5a
  (`prog="yasetnode"` and the updated description text "Add or remove nodes
  from the yascheduler daemon"), closing the brief-coverage gap for the
  argparse-meta concerns.
- **D3 strawman alternative.** Reframed the rejected alternative from
  "Bracketed IPv4 too" (never proposed) to "Allow optional brackets around
  IPv4" with a concrete cost/benefit rejection (parser complexity, no
  disambiguation benefit).

### Outstanding
- None. Round 2 to confirm.

## design Round 2 — 2026-06-25

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + frozen `proposal.md`
Frozen artifacts: `proposal.md`

### Verified
- Fix 1 (MINOR): D2 HostSpec table — `port` row has `validated 1..65535`,
  `ncpus` row has `>= 0 enforced`.
- Fix 2 (MINOR): D5a added — `prog="yasetnode"` + updated description,
  matching `proposal.md:68` and `proposal.md:71` exactly.
- Fix 3 (MINOR): D3 alternative reframed to "Allow optional brackets around
  IPv4" with concrete cost/benefit rejection (no longer a strawman).

### Outstanding
- None.

### Status
- **FROZEN.** Batch 2 (`design.md`) passes round 2; proceed to batch 3
  (`specs/`).

## specs Round 1 — 2026-06-25

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + frozen `proposal.md` + frozen `design.md`
Frozen artifacts: `proposal.md`, `design.md`

### Verdict
APPROVE WITH NOTES — no BLOCKER, no MAJOR. Two MINOR suggestions, both
declarative precision improvements.

### MINOR Fixed
- **Gateway-construction-timing phrasing.** The MODIFIED scenario
  "yasetnode opens a UoW and dispatches via gateway" said "on the add path,
  an `SSHMachineGateway` is constructed at the top of `manage_node`", which
  read as conditional. Reframed to: the gateway is constructed at the top
  of `manage_node` (before the UoW is opened); on the add path it is passed
  to the add helper. Now consistent with the ADDED gateway-lifecycle
  requirement and design.md D11/D12.
- **D13 coverage gap.** Added a `yasetnode helpers return None` scenario
  under the dispatch requirement, asserting `_add_node`/`_remove_node_hard`/
  `_remove_node_soft` return `None` (outcomes signaled via side effects,
  exceptions, exit codes — not return values). Closes the traceability gap
  for design.md D13.

### Outstanding
- None. Round 2 to confirm.

## specs Round 2 — 2026-06-25

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + frozen `proposal.md` + frozen `design.md`
Frozen artifacts: `proposal.md`, `design.md`

### Verified
- Fix 1 (MINOR): gateway-construction timing rephrased — constructed at top
  of `manage_node` before UoW opened; on add path, passed to helper.
- Fix 2 (MINOR): new `yasetnode helpers return None` scenario added under
  the dispatch requirement; 4 hashtags, WHEN/THEN, covers all three helpers.

### Outstanding
- None.

### Status
- **FROZEN.** Batch 3 (`specs/`) passes round 2; proceed to batch 4
  (`tasks.md`).

## tasks Round 1 — 2026-06-25

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + frozen `proposal.md` + frozen `design.md` + frozen `specs/`
Frozen artifacts: `proposal.md`, `design.md`, `specs/`

### Verdict
APPROVE WITH NOTES — no BLOCKER. One MAJOR, three MINOR. All implementation-
detail clarifications; no decision-level changes (so no unfreeze of earlier
batches required).

### MAJOR Fixed
- **Username resolution location ambiguous between 1.7 and 1.8.** Task 1.7's
  `_add_node(uow, gateway, spec, config, skip_setup)` signature had no
  `username` param, yet 1.8 implied `manage_node` resolves username before
  the call. `HostSpec` is frozen, so the value can't be written back.
  Resolution rule (`spec.username or config.remote.username`) is the frozen
  decision (D4); the *location* is mechanical. Fixed: `_add_node` resolves
  username internally (it has both `spec` and `config`); task 1.8 now states
  "username resolution delegated to `_add_node`". No design.md unfreeze
  needed — D4's resolution rule is preserved either way.

### MINOR Fixed
- **Task 6.5 WARN-level assertion.** Added "AND root logger level set to
  `WARN`" so the test matches the spec scenario for logging.
- **Tasks 1.5 / 1.6 block anchors.** Added "+ `START_BLOCK_` anchors" for
  consistency with 1.4 and 1.7 (D17 requires block anchors on multi-step
  helpers).
- **Task 1.8 `CONFIG_FILE` provenance.** Added parenthetical noting
  `CONFIG_FILE` is imported from `yascheduler.shared` (same as predecessor
  modules).

### Outstanding
- None. Round 2 to confirm.

## tasks Round 2 — 2026-06-25

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + frozen `proposal.md` + frozen `design.md` + frozen `specs/`
Frozen artifacts: `proposal.md`, `design.md`, `specs/`

### Note
An earlier round-2 attempt reported `tasks.md` missing from disk (a
transient environment glitch — the file had been written and edited
successfully). The file was re-written with all four fixes baked in and
confirmed on disk (56 lines, `openspec validate` passes). This round-2
review reflects the on-disk content.

### Verified
- Fix 1 (MAJOR): task 1.7 resolves username inside `_add_node`
  (`spec.username or config.remote.username`); task 1.8 delegates. Mutually
  consistent; resolution rule matches D4; `_add_node` signature (D12)
  unchanged.
- Fix 2 (MINOR): task 6.5 asserts both `captureWarnings(True)` AND root
  logger WARN level.
- Fix 3 (MINOR): tasks 1.5/1.6 include `START_BLOCK_` anchors, matching
  1.4/1.7 (D17).
- Fix 4 (MINOR): task 1.8 notes `CONFIG_FILE` import from
  `yascheduler.shared`.

### Outstanding
- None.

### Status
- **FROZEN.** Batch 4 (`tasks.md`) passes round 2. All four batches
  (`proposal.md`, `design.md`, `specs/`, `tasks.md`) are frozen. The change
  is apply-ready.




