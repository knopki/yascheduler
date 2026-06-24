## proposal Round 1 — 2026-06-24

### ✅ Covered
- Problem statement, selected approach (`with_event` + 5 overloads, `record_event` kept as primitive), and the six-call-site table all faithfully captured from the brief.
- "Modified Capabilities" correctly lists only `message-bus`; `domain-events`, `webhook-handler`, `domain-entities` correctly excluded. Verified against the four specs.
- All six call-site references match source (file, line range, event type, enclosing function). A repo-wide grep confirms no missed `.record_event(` sites.
- No new capabilities needed; `with_event` is a convenience over the existing record/pull/dispatch path.
- Schema complete (Why / What Changes / Capabilities / Impact). No internal contradictions.

### 🟡 Minor (non-blocking)
- `proposal.md:26` reads "typing.overloads" (plural); import is `typing.overload`. Cosmetic.
- Per-file breakdown only in What Changes; the "six call sites" count could also appear in Why. Optional.

### 🔴 Outstanding
None.

**Result: APPROVE — proposal frozen.**
## design Round 1 — 2026-06-24

### ✅ Covered
- D1 overload field lists match events.py exactly (verified field-by-field for all 5 subclasses).
- D3 silent-pop targets exactly the three DomainEvent base fields; substitution sources exist on Task/TaskContext.
- D4 verified: Task.fail() preserves webhook_url/webhook_custom_params in context, so with_event reads them correctly after fail() at orchestrator.py:309-317.
- Python 3.9 minimum and ParamSpec shim claims verified.
- All line citations accurate. Brief's three rejected alternatives surface in D1 with rationale.
- Proposal fidelity exact: 5 overloads, generic runtime, record_event unchanged, no scope creep, no new capability, no breaking change.
- Both risks acknowledged with mitigations.

### 🟡 Minor (applied)
- Added a one-line goal acknowledging the message-bus spec scenario rewording to close the loop with the proposal's Modified Capability.

### 🔴 Outstanding
None.

**Result: APPROVE — design frozen.**

## specs Round 1 — 2026-06-24

### ✅ Covered
- Delta schema well-formed: ADDED for `Task.with_event` requirement, MODIFIED with full updated content for "Use-case-to-event mapping".
- ADDED requirement: all five overload field sets match events.py exactly; silent-pop documented; record_event preserved as primitive; all 6 scenarios use exactly 4 hashtags.
- MODIFIED requirement: header text matches original verbatim; `TaskRejected` normative statement preserved; webhook invariant preserved (now distributed inline + per-scenario); all 6 scenarios use `task.with_event(...)` form with 4 hashtags.
- Call-site mapping verified against source — delta's function names (`_try_start_on_machine`, `_record_finalization_event`) are more accurate than the original spec's (`_allocate_free_machine`, `consume_task`).
- No scope creep: only "Use-case-to-event mapping" modified; other seven message-bus requirements untouched; no domain-events/webhook-handler/domain-entities deltas. `openspec validate` passes.

### 🟡 Addressed
- Reconciled proposal summary text to acknowledge the mapping-table column addition and the two corrected use-case function names (declarative append to the frozen proposal's Modified Capabilities note — no decision-level change).

### 🔴 Outstanding
None.

**Result: APPROVE — specs frozen.**

## tasks Round 1 — 2026-06-24

### ✅ Covered
- Checkbox format parseable; tasks grouped under numbered headings.
- Group 1 (domain): 5 overloads + generic runtime + silent pop + delegation, imports called out — matches design D1/D3 and ADDED requirement.
- Group 1 GRACE: MODULE_MAP/CHANGE_SUMMARY/VERSION + knowledge-graph `<class-Task>` annotation.
- Group 2: all 6 call-site conversions match spec MODIFIED mapping table, design call-site table, and brief — with precise function-name qualifiers.
- Group 3: test suite enumerates all 6 ADDED scenarios; confirms existing TestTaskEvents unchanged.
- Group 4: full validation suite (pytest unit, zuban, ruff check, ruff format, lint-imports, grace_check, openspec validate).
- Dependency ordering correct (1→2→3→4); granularity ≤2h; verifiable done-conditions; no scope creep.
- All cited line ranges verified against current code (6 call sites, model.py:150/262, knowledge-graph.xml:220, test_domain_events.py:175).

### 🟡 Addressed
- Added `START_CONTRACT: Task.with_event` block requirement to task 1.2 for GRACE-lite consistency (every existing public Task method carries a contract block).

### 🔴 Outstanding
None.

**Result: APPROVE — tasks complete; change is apply-ready.**
