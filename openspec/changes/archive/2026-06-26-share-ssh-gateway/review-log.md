# Review Log — share-ssh-gateway

## Round 1 — proposal + design + specs + tasks (all-in-one batch)

Reviewer: `@k-reviewer-fast` (task `ses_0fad4ec83ffe4NWUH2R4eyQX78`)

### Scope reviewed

Newly created artifacts (no frozen baseline yet — first round):
- `explore-brief.md` (baseline checklist)
- `proposal.md`
- `design.md`
- `specs/dependency-injection/spec.md` (ADDED Requirement)
- `specs/cloud-provisioner/spec.md` (ADDED Requirement)
- `tasks.md`

### ✅ Confirmed

- All factual claims (line numbers, function names, idempotency of
  `disconnect_all`, parameter-equivalence table) verified against source on
  disk.
- Every `explore-brief.md` commitment captured downstream: 3 problem
  consequences, 2 rejected alternatives, behavior mapping (prod vs pre-built),
  `_await_first_machine` analysis, `Orchestrator.stop` ordering, files-touched.
- Spec well-formedness: each Requirement has ≥1 Scenario; scenarios use
  exactly `####`; SHALL/MUST consistent (no `should`/`may`).
- No contradiction with existing specs:
  - `orchestrator/spec.md` "Graceful shutdown" (lines 52-54) still satisfied.
  - `dependency-injection/spec.md` "make_daemon accepts pre-built clouds"
    scenario is additive, not contradicted.
  - `cloud-provisioner/spec.md` does not constrain `stop()` today; delta adds
    a constraint on the concrete method.
- No scope creep: every task maps to a stated proposal/design change.

### 🟡 Addressed (Round 1 → applied to `tasks.md`)

1. Task 3.1 tightened: existing `mock_gateway.assert_called()` →
   `assert_called_once()` to lock the "exactly one SSHMachineGateway" spec
   scenario against future regression to two gateways.
2. Task 3.2 augmented: added assertion
   `orch_kwargs["gateway"] is not custom_clouds.machine_gateway` to cover the
   "pre-built clouds path keeps its own gateway" spec scenario.

### 🔴 Outstanding

None — batch is freezeable per single-round pass rule.

### Outcome

All four artifacts (proposal, design, specs, tasks) **frozen**. Ready for
`/opsx-apply`.
