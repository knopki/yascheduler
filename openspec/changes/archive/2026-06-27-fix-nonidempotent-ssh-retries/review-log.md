# Review Log — fix-nonidempotent-ssh-retries

## proposal Round 1 — 2026-06-27

### Reviewer: k-reviewer-fast

### Result: APPROVE (no blocking issues)

### Coverage check (3 bugs + 4 explore-phase reviewer adjustments)

| Item | Covered | Location |
|------|---------|----------|
| Bug 1: `run_bg` double-spawn | ✓ | Why L6-21, What L49-56 |
| Bug 1b: sticky BUSY on failure | ✓ | L16-21, L57-64 |
| Bug 2: `download_outputs` nested backoff | ✓ | L22-34, L69-71 |
| Bug 2b: sticky `transient_errors` gate | ✓ | L28-33, L75-80 |
| Bug 3: `upload`/`download` half-written files | ✓ | L35-41, L65-68 |
| Fix 3 🔴: fresh SFTP client per file | ✓ | L72-74 |
| Fix 3 🟡: rmtree gate `AND not permanent_errors` | ✓ | L77-80 |
| Fix 2 🟡: drop `@my_backoff_sftp()` from `download` too | ✓ | L65-68 |
| Fix 1b 🟡: release() always, warn if not BUSY | ✓ | L60-63 |

### 🟡 Addressed (post-review, pre-freeze)
- "Relationship to active changes" → "Relationship to other changes": `fix-download-rmtree-data-loss` is already merged in HEAD (commit `e7d87cb`), not active. Reworded to reflect it established the v1.7.0 3-tuple contract this change builds on.

### 🔴 Outstanding
<!-- none — batch frozen -->

### Freeze
`proposal.md` frozen after Round 1. Baseline for design + specs.

## design + specs Round 1 — 2026-06-27

### Reviewer: k-reviewer-fast

### Result: APPROVE WITH NOTES (no blocking issues)

### Coverage check (against frozen proposal)

| Proposal item | Design decision | Spec delta |
|---|---|---|
| Drop `@my_backoff_exc()` from `run_bg` | D1 | MODIFIED "Backoff on gateway methods" |
| Roll back gateway BUSY on failure | D2 | ADDED "start_task_on_machine rolls back gateway BUSY on failure" |
| Drop `@my_backoff_sftp()` from `upload` + `download` | D3 | MODIFIED "Backoff on gateway methods" |
| Restructure `download_outputs` (drop outer retry, per-file SFTP, single post-loop rmtree gate on both lists) | D4 (D4.1-D4.4) | MODIFIED "SSHMachineGateway implements MachineGateway" |
| No new types / no return-type change | Goals + D4.4 sketch | preserved |

### Explore-phase reviewer adjustments folded in
- A1 (🔴 per-file SFTP isolation): D4.2 + spec "Per-file SFTP isolation bounds dead-connection blast radius" scenario ✓
- A2 (🟡 rmtree gate both lists): D4.3 + spec "Remote directory removed only on full success" / "Remote directory preserved on any errors" scenarios ✓
- A3 (🟡 drop download decorator too): D3 + spec "download does not retry on SFTP failure" scenario ✓
- A4 (🟡 always release + warn): D2 + spec "Concurrent disconnect skips rollback with warning" / "Unexpected non-BUSY state still releases and warns" scenarios ✓

### Spec delta structural checks
- MODIFIED vs ADDED decomposition: correct (download_outputs folded into existing "SSHMachineGateway implements MachineGateway" MODIFIED; rollback is ADDED) ✓
- Full updated content for MODIFIED: all 13 original scenarios + 4 backoff scenarios preserved, zero deletions ✓
- 23 scenarios, all `####` (4 hashtags) ✓
- Every requirement has ≥1 scenario ✓
- SHALL/MUST normative language consistent ✓
- Scenarios testable (concrete WHEN/THEN) ✓

### 🟡 Addressed (post-review, pre-freeze)
- `openspec validate` ERROR: ADDED requirement "must contain SHALL or MUST" — the validator scanned only the first line of the requirement body; SHALL was on line 203 (wrapped). Rewrote the opening paragraph so the first sentence ends with SHALL on line 202. Re-validated: `valid: true`. Also restored backticks in the heading (matching `fix-write-remote-file-swallow` style) — backticks were not the issue.

### 🟡 Note (not a blocker — address during apply)
- `docs/knowledge-graph.xml:936` `fn-download_outputs` PURPOSE says "conditional rmtree (only when transient_errors empty)" — will be stale after this change (new condition: both error lists empty). D6 correctly says no graph update is *required* per AGENTS.md rule 3, but updating the PURPOSE string during apply keeps the graph accurate. Low effort.

### 🔴 Outstanding
<!-- none — batch frozen -->

### Freeze
`design.md` and `specs/ssh-gateway/spec.md` frozen after Round 1. Baseline for tasks.

## tasks Round 1 — 2026-06-27

### Reviewer: k-reviewer-fast

### Result: APPROVE (no blocking issues)

### Coverage check
- Spec → task: 4 backoff scenarios → 1.1-1.4; 6 download_outputs scenarios → 3.1-3.6 + 5.9-5.11; 5 rollback scenarios → 2.1 + 5.4-5.8 ✓
- Design → task: D1→1.1 | D2→2.1 | D3→1.2,1.3 | D4.1-D4.4→3.1-3.6 | D5→frozen | D6→4.3 ✓
- Granularity: all 27 tasks ≤2h ✓
- Dependency ordering: decorators → rollback → download_outputs → metadata → tests → static checks ✓
- Verifiability: every task has observable done-signal ✓
- No scope creep ✓
- Checkbox format: all `- [ ] N.M ...` parseable ✓
- e2e/integration coverage per `e2e-testing` / `test-db-integration`: task 6.7 ✓

### Minor observation (not a finding)
- Task 5.6 (`CancelledError` test) will need `pytest.raises(asyncio.CancelledError)` since `CancelledError` is `BaseException` subclass in Python 3.8+. Standard pytest pattern, no issue.

### 🔴 Outstanding
<!-- none — batch frozen -->

### Freeze
`tasks.md` frozen after Round 1. All apply-required artifacts complete.