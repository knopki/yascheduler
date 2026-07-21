## Why

The `orchestrator` spec is the most bloated behavior spec in the project (403
lines across 10 requirements). The bulk is implementation prose that duplicates
the GRACE code contracts (`MODULE_CONTRACT` / `CLASS_Orchestrator` /
`METHOD_*` / `FUNC_*`) already present in `application/orchestrator.py` and the
delegate use-case modules. Three categories of content sit in the spec but
belong in code-level contracts:

1. **Internal invariants** — the in-process in-flight task-id set, the
   occupancy-started node-id set, the per-node connect-failure timer. These are
   in-memory state invariants of the `Orchestrator` instance, not behavioral
   contracts observable by external consumers.
2. **Internal algorithm sequences and preconditions** — step-by-step
   "the producer SHALL add the id to the set BEFORE awaiting, and remove it in
   a `finally` block" descriptions. These are method-level `REQUIRES`/`ENSURES`,
   not spec-level requirements.
3. **Local rationale** — "a transient SSH outage after a daemon restart must
   not silently delete an operator's node row", "the gate lives in the use case
   not the repository", the all-or-nothing jump-stamping explanation. These are
   `RATIONALE` Q/A for the methods/classes that implement them.

This bloat causes drift (spec text and code prose diverge over time), obscures
the actual acceptance criteria (the Given/When/Then scenarios), and makes the
spec harder to scan for the externally observable contract. The GRACE methodology
explicitly assigns these content kinds to code-local markup.

## What Changes

- Trim `openspec/specs/orchestrator/spec.md` from ~403 to ~200–250 lines,
  keeping every observable behavioral scenario (Given/When/Then) and every
  public-method signature. Remove implementation rationale, internal
  invariants, step-by-step algorithm sequences, and negative-space regression
  guards from the spec prose.

- Extend the existing GRACE markup regions in `application/orchestrator.py`
  with the relocated content: `MODULE_CONTRACT` `INVARIANTS`, `CLASS_Orchestrator`
  `INVARIANTS`, and `METHOD_*` `REQUIRES`/`ENSURES`/`RATIONALE` for the four
  producer-consumer loops and the connect-machine grace logic.

- Extend GRACE markup in the four delegate use-case modules
  (`abandon_node.py`, `allocate_task.py`, `consume_task.py`,
  `deallocate_nodes.py`) where a relocated invariant or rationale semantically
  belongs to the delegate's `FUNC_*`/`METHOD_*` contract rather than the
  orchestrator's.

- No behavioral change. No code logic change. No test change. Every observable
  scenario in the trimmed spec MUST remain covered by the existing unit tests
  in `tests/unit/test_application_orchestrator.py` and adjacent files.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `orchestrator`: Relocate implementation rationale, in-memory invariants
  (in-flight set, occupancy-started set, connect-failure timer), and
  method-level pre/post-conditions out of the spec text and into the GRACE
  code contracts of `application/orchestrator.py` and the four delegate
  use-case modules. Slim the spec to observable behavior + acceptance
  scenarios. No behavioral change; every existing scenario survives (possibly
  reworded as a pure observable assertion, never deleted).

## Impact

- **Specs**: `openspec/specs/orchestrator/spec.md` rewritten (slimmed).
  `openspec validate --all --json` must still pass after the change.
- **Code (markup only, no logic)**: `yascheduler/application/orchestrator.py`
  gains/extends `MODULE_CONTRACT` `INVARIANTS`, `CLASS_Orchestrator`
  `INVARIANTS`, and `METHOD_*` / `FUNC_*` `REQUIRES`/`ENSURES`/`RATIONALE`
  fields. The four delegate use-case modules gain the subset of relocated
  content that belongs to their contracts.
- **Tests**: no change. Existing scenarios in the slimmed spec remain the
  acceptance criteria; existing tests already assert them. A passing
  `uv run pytest -m unit` run on the orchestrator tests after the change is
  the regression guard.
- **Public surface**: none. No CLI, API, INI, DB schema, or log-format change.
- **Pilot scope**: this change ONLY dehydrates the `orchestrator` spec. Other
  bloated specs (`domain-entities`, `use-cases`, `cloud`, `package-facades`,
  etc.) are explicitly out of scope and would follow as separate change
  proposals once this pilot establishes the dehydrate pattern.
