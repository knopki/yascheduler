# Review Log: clean-architecture-imports

## proposal Round 1 — 2026-06-19

### 🔴 Serious issues (must fix before freeze)

**S1. Variant b exception routing is technically impossible as written.**
- `SFTPRetryExc`, `SSHRetryExc`, `AllSSHRetryExc` are **tuples of exception classes**
  (`yascheduler/adapters/ssh/platform/protocol.py:75,89,101`), not classes. The
  constituent classes are mostly third-party (asyncssh's `SFTPEOFError`,
  stdlib's `OSError`/`asyncio.TimeoutError`) — their base classes cannot be
  re-parented.
- Application usage (`consume_task.py:105,151`, `orchestrator.py:411`) is
  `backoff.on_exception(backoff.fibo, SFTPRetryExc, max_time=60)` — a decorator
  that takes a tuple of exception types, not a `try/except` block.
- Cannot make a tuple "inherit"; cannot swap tuple for `RetryableOperationError`
  in `backoff.on_exception` without changing raise semantics.
- **Requires design decision from user before next round.**

**S2. Four empty `__init__.py` facades missing from What Changes and Impact.**
- Brief lists them: `application/__init__.py`, `adapters/__init__.py`,
  `adapters/notifier/__init__.py`, `adapters/ssh/__init__.py`.
- These are load-bearing for R2 (cross-package imports through facade) — proposal
  must mention them in both sections. Will fix in next round.

### 🟡 Minor issues / suggestions

- **M1.** `RetryableOperationError` placement in `DomainError` tree not
  reconciled with existing `domain-exceptions` spec ("for all business-level
  exceptions" framing). Decide and state explicitly.
- **M2.** Outside-layer-set enumeration + "R2 still applies to composition root"
  absent from proposal. Add one-line note or pointer.
- **M3.** `root_package = "yascheduler"` import-linter setting dropped from
  proposal. Include for parity with brief.
- **M4.** `compat.py` internal-status not pinned in proposal's public-surface
  note. Add a clause.
- **M5.** Brief open question #1 (`package-facades` vs alternatives) resolution
  rationale missing. Half-sentence would help.

### ✅ Confirmed correct

- R1/R2/R3 definitions match brief.
- Layer direction `adapters → application → domain` consistent.
- `import-linter >=2.5,<2.6` pin for Python 3.9 — correct.
- `exclude_type_checking_imports = true` — correct.
- CI `lint-imports` check matches brief.
- Two existing R3 violations correctly identified.
- `domain/__init__.py` extension scope — correct.
- `adapters/cli/__init__.py` R1 fix — correct.
- `package-facades` is not an existing spec name.
- `domain-exceptions` correctly identified as the spec to modify.
- Out of scope correctly excludes db.py, ssh/platform trim, Python bump,
  R1/R2 enforcement beyond docs.

### 🔴 Outstanding (blocks freeze)

- **S1**: Variant b design is unsound. Need user decision on the actual
  exception-routing approach before specs/tasks can be drafted.
- S2, M1-M5: will be fixed in next round once S1 is resolved.

## proposal Round 2 — 2026-06-19

### 🔴 Fixed from Round 1
- S1: Variant b → Variant C (tuples of third-party classes cannot be re-parented; gateway wraps operations and re-raises as `RetryableOperationError`).
- S2: Four empty `__init__.py` facades now appear in What Changes and Impact.
- M1: `RetryableOperationError(DomainError)` placement explicit.
- M2: Outside-layer-set enumeration + R2-applies-to-composition-root stated.
- M3: `root_package = "yascheduler"` included.
- M4: `compat.py` internal status pinned.
- M5: `package-facades` rationale stated.

### 🔴 New serious issue (blocks freeze)

**S3. Variant C coverage hole — `gateway.get_sftp()` yields raw asyncssh `SFTPClient`.**
- `gateway.py:321-326` — `get_sftp` is just `async with state.conn.start_sftp_client() as sftp: yield sftp`. No wrapping. Gateway is not on the call stack when `sftp.get`/`sftp.makedirs`/`_write_remote_file` raise.
- `consume_task.py:107,110` — `async with gateway.get_sftp(ip) as sftp: await file_get_retry(sftp.get)(...)`. The `sftp` is a raw asyncssh `SFTPClient`; `sftp.get` raises `SFTPFailure`/`SFTPEOFError`/`OSError` (members of `SFTPRetryExc`). Replacing `SFTPRetryExc` with `RetryableOperationError` in `file_get_retry` (line 105) **silently disables SFTP retry entirely** — behavioral regression.
- `orchestrator.py:189` (`_upload_task_data`) — `sftp.makedirs`, `_write_remote_file(sftp, …)` — same raw-client problem.
- The gateway's existing internal retries (`gateway.py:67` → `run_full` at `:272`; `gateway.py:454` → `setup_node`) only cover `run_full` and `setup_node`. They do not cover SFTP operations done via `get_sftp`.
- Consequence: Variant C as written does NOT fix `consume_task.py` and only partially addresses `orchestrator.py:411`. The proposal's claim "backoff now retries on RetryableOperationError" is incorrect for the SFTP paths.

### 🟡 Minor issues
- m1: "Two-layer retry semantics preserved" only true for `run_full`/`setup_node`; SFTP path is currently single-layer (`file_get_retry` directly on `sftp.get`).
- m2: "Wraps its public operations" is ambiguous — only `run_full`/`setup_node` currently have internal backoff. Does "wrap" mean translate-on-existing-retries or add-retry-to-all-methods?
- m3: `RetryableOperationError` is operational, not business-level. Existing `domain-exceptions` spec calls `DomainError` "for all business-level exceptions" — wording needs reconciliation.
- m4: `adapters/ssh/exceptions.py` (the public facade that re-exports the tuples) is the actual import site being removed from application/. Proposal mentions `platform/protocol.py` but not this facade. Should clarify it becomes adapters-internal after the fix.

### 🔴 Outstanding (blocks freeze)

- **S3**: Variant C as written does not actually fix the R3 violations in `consume_task.py` and `orchestrator.py` because the application uses raw asyncssh SFTPClient via `gateway.get_sftp()`. Need user decision on one of:
  - **Option 1 (expand scope)**: refactor gateway to remove `get_sftp()` from public surface, add wrapped SFTP methods (`download_files`, `upload_files`, `make_remote_dir`) that retry internally and raise `RetryableOperationError`. Touches `consume_task._sftp_download_job`, `orchestrator._upload_task_data`, `adapters/cli/check_status.py:85-86`, `orchestrator.py:282`.
  - **Option 3 (split change)**: ship only import-linter + facades + cli fix in this change; add `ignore_imports` for the two known R3 violations (documented residual); follow-up change does the gateway SFTP refactor and removes the `ignore_imports`.
- m1-m4: cleanup, will be addressed in next round once S3 path is chosen.

## proposal Round 2 — Resolution

**User decision: Option 3 (split change).**

- Variant C gateway wrapping — **removed from this change**.
- `RetryableOperationError(DomainError)` introduction — **removed from this change** (would be unused; YAGNI).
- `domain-exceptions` spec modification — **removed** (no longer touching it).
- Two existing R3 violations — **documented as residual via `ignore_imports`** in the `layers` contract.
- Follow-up change `gateway-sftp-wrapping` scaffolded at `openspec/changes/gateway-sftp-wrapping/` with explore-brief capturing the full design context (Variant C done properly, including gateway `get_sftp` removal, new wrapped SFTP methods, all call sites, retry semantics).

This keeps `clean-architecture-imports` focused on import hygiene (its stated purpose). Gateway SFTP refactor is genuinely a separate architectural concern. Round 3 proposal revision reflects this narrowing.

## proposal Round 3 — 2026-06-19

### ✅ Confirmed correct
- S3 fix verified: zero occurrences of `RetryableOperationError`, "gateway wrapping", "wrap operations", or `domain-exceptions` in proposal.
- Round 1 fixes still hold.
- `package-facades` not in existing specs.
- Brief-proposal consistency (outside S4).
- Follow-up brief self-contained.
- Scope coherence sound.
- Internal consistency verified.

### 🔴 Fixed
- **S4**: Brief "Key cross-module data flows (post-change)" had orphan Variant C residue (lines 134, 141 — `RetryableOperationError` in domain/__init__.py box, "Application catches domain-level RetryableOperationError"). Rewrote to reflect actual post-change state (DomainError tree in facade box; residual edges shown explicitly with note about follow-up).

### 🟡 Fixed
- **m1**: Follow-up `gateway-sftp-wrapping/explore-brief.md` step 4 now notes that `domain/__init__.py` must re-export `RetryableOperationError` for R2-compliant import.
- **m2**: Proposal clarified "exceptions (the existing `DomainError` tree — no new symbols)".
- **m3**: Proposal Impact section now explicitly lists `openspec/specs/package-facades/spec.md` as a created file.

## proposal Round 4 — 2026-06-19

### ✅ All Round 3 fixes verified
- S4 fix verified: brief diagram and surrounding text no longer reference `RetryableOperationError`; actual post-change state shown.
- m1 fix verified: follow-up brief step 4 now mentions `domain/__init__.py` must re-export `RetryableOperationError` for R2-compliant import.
- m2 fix verified: proposal clarifies "existing DomainError tree — no new symbols".
- m3 fix verified: proposal Impact lists `openspec/specs/package-facades/spec.md`.
- No regressions confirmed.

### Verdict: **PASS**

### 🔴 Outstanding
- (none)

## Status

Batch 1 (proposal.md) — **FROZEN** per workflow §4a (single-round pass rule).

## design Round 1 — 2026-06-19

### 🔴 Serious issues (must fix before freeze)
- **S1.design**: GRACE-lite knowledge-graph update missing from migration plan. `docs/knowledge-graph.xml:186` M-DOMAIN's `<depends>` must extend from `M-DOMAIN-EVENTS` to include `M-DOMAIN-MODEL`, `M-DOMAIN-EXCEPTIONS`, `M-DOMAIN-PORTS`. Also missing: `CHANGE_SUMMARY` bumps for touched `__init__.py` files and `python3 scripts/grace_check.py` validation step.
- **S2.design**: Standard verification ladder (`pytest -m unit`, `zuban check`, `ruff check`, `ruff format --check`) missing from migration plan. AGENTS.md mandates.
- **S3.design**: No contingency policy if `lint-imports` surfaces a 3rd R3 edge not anticipated by static inspection.

### 🟡 Minor issues
- m1.design: Variant F rejection not enumerated in D4.
- m2.design: "static-checks CI workflow" naming imprecise — actual file is `.github/workflows/lint.yml`.
- m3.design: Outside-layer-set enumeration thinner than brief; no full list in design.
- m4.design: No layering diagram (brief had one).
- m5.design: D6 reads like fresh decision; should be one-line inheritance from proposal.
- m6.design: D7 leaves "other R1 deviations" ambiguous — should list or say none.
- m7.design: Three risk mitigations repeat "AGENTS.md TRIGGER pointer" — concentration risk worth noting.

### ✅ Confirmed correct
- All 8 decisions (D1-D8) rationale sound, alternatives rejected with reasons.
- TYPE_CHECKING claim verified (4 application files).
- Two residual R3 edges verified.
- cli/__init__.py absolute self-import verified.
- domain/__init__.py events-only verified.
- No import-cycle risk from extending domain/__init__.py (model.py only imports .exceptions; ports.py uses TYPE_CHECKING for .model; events.py depends on nothing).
- D2 Python pin verified against `pyproject.toml:7`.
- No decision-level contradictions with frozen proposal — soft-freeze respected.
- Cross-references accurate.
- Open questions genuinely open and non-blocking.
- Length tight (131 lines).

### Verdict: NEEDS_FIX

### 🔴 Outstanding
- S1.design, S2.design, S3.design will be fixed in Round 2.
- m1-m7 design will be addressed in same revision.

## design Round 2 — 2026-06-19

### 🔴 Fixed
- S1.design: GRACE-lite KG update step added (M-DOMAIN `<depends>` extension + CrossLink polish).
- S2.design: Standard verification ladder added to migration step 10.
- S3.design: 3rd-edge contingency policy added to Risks table.

### 🟡 Fixed
- m1-m7 all addressed (Variant F bullet, `.github/workflows/lint.yml` filename, full outside-layer-set enumeration in diagram, layering diagram added, D6 trimmed, D7 audit list, concentration note for TRIGGER mitigations).

### 🟡 Non-blocking note
- CrossLink `relation` text polish suggested by reviewer — added as declarative clarification to migration step 5 before freeze.

### ✅ Confirmed correct
- All Round 1 fixes verified.
- No regressions.
- Three-way brief/proposal/design consistency holds.
- All external facts verified (`.github/workflows/lint.yml`, `pyproject.toml:7`, `knowledge-graph.xml:186`, M-* entries exist).

### Verdict: **PASS**

### 🔴 Outstanding
- (none)

## Status

Batch 2 (design.md) — **FROZEN** per workflow §4a.

## specs Round 1 — 2026-06-19

### 🟡 Minor issues (non-blocking, addressed in Round 2 for accuracy)
- m1.specs: R2 "SHALL NOT appear" creates logical tension with documented R2 residuals (the two `ignore_imports` edges are also R2 violations; plus pre-existing R2 violations in `manage_node.py:26`, `daemonize.py:26`, `postgres_uow.py:36`). Fixed by scoping R2 to "new imports introduced after this change is merged" + adding note that the two documented residual edges are both R2 and R3 violations.
- m2.specs: Scenario referenced non-existent symbol `SubmitTask` (actual code is `async def submit_task`). Replaced with real `submit_task`.

### ✅ Confirmed correct
- Format compliance VERIFIED: `## ADDED Requirements`, `### Requirement:`, 4-hashtag scenarios, SHALL/MUST language, ≥1 scenario per requirement.
- `openspec validate --all --json` reports `clean-architecture-imports` `valid: true`.
- Coverage: every commitment from proposal/design/brief captured as a requirement.
- All 5 codebase spot-checks verified (cli/__init__.py absolute self-imports, domain/__init__.py events-only, ports.py has 4 Protocols, two residual edges exist, top-level __init__.py exports).

### Verdict: PASS (APPROVE WITH NOTES)

### 🔴 Outstanding
- (none — both minor issues addressed in declarative clarifications before freeze)

## specs Round 2 — 2026-06-19

### ✅ Confirmed correct
- m1.specs fix verified: R2 properly scoped to new imports; clarification added that residual edges are both R2 and R3 violations.
- m2.specs fix verified: scenario now uses real `submit_task` symbol.
- Format compliance verified: `openspec validate --all --json` reports `valid: true`.
- No regressions.
- Four-way brief/proposal/design/spec consistency holds (ignore_imports edges, four empty facades, layer set, outside-layer-set enumeration all identical).

### 🟡 Non-blocking note
- Reviewer suggested replacing "tracked separately" with more concrete wording for non-residual pre-existing R2 violations. Current wording is clear enough; suggestion not applied.

### Verdict: **PASS**

### 🔴 Outstanding
- (none)

## Status

Batch 3 (specs/package-facades/spec.md) — **FROZEN** per workflow §4a.

## tasks Round 1 — 2026-06-19

### 🟡 Minor issues (non-blocking, all addressed before freeze)
- m1.tasks: Task 1.1 dev-deps hint pointed to non-existent `[project.optional-dependencies]`. Fixed: concrete pointer to `[dependency-groups] dev` (PEP 735, `pyproject.toml:68`).
- m2.tasks: Task 5.1 step-name ambiguity. Fixed: explicitly references "step named `type check` (`uv run zuban check`)".
- m3.tasks: Task 2.1 missed `MODULE_CONTRACT`/`MODULE_MAP` updates (GRACE-lite rule 2). Fixed: task 2.2 expanded to cover PURPOSE/SCOPE/DEPENDS + MODULE_MAP + CHANGE_SUMMARY.
- m4.tasks: AGENTS.md path style inconsistent with existing entries (no `/spec.md` suffix). Fixed: aligned to `openspec/specs/package-facades`.
- m5.tasks: Tasks 5.2/6.5 overlapped. Fixed: 5.2 removed (6.5 covers `lint-imports` exit 0).
- m6.tasks: Task 6.9 diff base ambiguous. Fixed: explicit `git diff $(git merge-base HEAD main) -- yascheduler/db.py`.

### ✅ Confirmed correct
- Format compliance verified: 30 tasks (after removing 5.2), `## N.` groups, `- [ ] N.M` checkboxes, ≤2h each, dependency-ordered.
- `openspec validate --all --json` reports `valid: true`, no issues.
- Coverage check complete: all 8 proposal commitments, all 11 design migration steps (incl. CHANGE_SUMMARY bumps and CrossLink), all 9 spec requirements mapped to tasks.
- Quality checks pass: actionable, testable, correctly-sized, ordered.
- Codebase spot-checks 5/5 verified.
- Out-of-scope documentation (tasks 7.1-7.6) matches Non-Goals exactly.

### Verdict: PASS (APPROVE WITH NOTES)

### 🔴 Outstanding
- (none — all 6 minor issues addressed before freeze)

## tasks Round 2 — 2026-06-19

### ✅ Confirmed correct
- All six Round 1 fixes verified against codebase facts:
  - m1: `[dependency-groups]` `dev` at `pyproject.toml:68` confirmed.
  - m2: `lint.yml:38` is `name: type check` with `uv run zuban check`, last step at line 39 — confirmed.
  - m3: tasks 2.2 and 2.4 cover full GRACE-lite metadata updates — confirmed.
  - m4: AGENTS.md existing pointers (lines 48-55) all use bare spec paths — confirmed.
  - m5: task 5.2 removed, 6.5 still covers lint-imports — confirmed.
  - m6: explicit merge-base base ref — confirmed.
- Format compliance: `openspec validate --all --json` reports `valid: true`, `issues: []`.
- No regressions.
- Five-way proposal/design/spec/tasks/brief consistency holds.

### Verdict: **PASS**

### 🔴 Outstanding
- (none)

## Status

Batch 4 (tasks.md) — **FROZEN** per workflow §4a.

---

## Change Status: ALL BATCHES FROZEN

- ✅ Batch 1: proposal.md (4 rounds, PASS at Round 4)
- ✅ Batch 2: design.md (2 rounds, PASS at Round 2)
- ✅ Batch 3: specs/package-facades/spec.md (2 rounds, PASS at Round 2)
- ✅ Batch 4: tasks.md (2 rounds, PASS at Round 2)

`clean-architecture-imports` is **ready for apply phase** (`/opsx-apply`).

Follow-up change `gateway-sftp-wrapping` is scaffolded with full explore-brief at `openspec/changes/gateway-sftp-wrapping/explore-brief.md` — pick up when ready to tackle the gateway SFTP refactor.
