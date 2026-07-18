## Why

`openspec/specs/domain-ports/spec.md` currently mixes three kinds of content: (a) actual SHALL requirements and scenarios, (b) design rationale and historical narrative (e.g., why `MachineOperations` was removed, why `add_tmp` is absent, why hostname-keyed lookups are not on the Protocol, why `insert` is the sole `NewTask → Task` conversion site), and (c) cross-spec duplicate prose already stated authoritatively in `cloud`, `ssh-infrastructure`, and `use-cases`.

The result is a 196-line spec where the same fact is often restated 2–3 times across paragraphs, where the line between a normative requirement and design context is blurred, and where narrative churn from past refactors (REMOVED clauses, "unchanged in signature" notes) lives permanently next to live requirements. Readers cannot scan for the actual contract; reviewers cannot tell what is a behavior change vs an editing note.

Without this change: every future reader of the spec pays the cost of separating signal (SHALL) from noise (rationale/history) themselves, and every related refactor re-opens the same sprawling paragraphs instead of touching a tight requirements section.

## What Changes

- **TRIMMED** `domain-ports` spec to: Purpose, one SHALL requirement per port with method signatures, and behavior-level scenarios only.
- **RELOCATED** design rationale, invariants, and pre/post-conditions out of the spec and into GRACE markup on `yascheduler/domain/ports.py`.
- **REMOVED** from the spec: historical REMOVED clauses, "unchanged in signature" notes, hostname-vs-node_id migration narrative, `int`/`TaskId` facade-boundary prose, duplicate signature restatements, and use-case flow leakage (tmp-reservation belongs in `use-cases`).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `domain-ports`: requirements slimmed to SHALL statements and behavior scenarios; design context (rationale, invariants, method-level pre/post-conditions) relocated to GRACE markup on `yascheduler/domain/ports.py`. No port semantics, signatures, or behavioral requirements are added, removed, or changed.

## Impact

- `openspec/specs/domain-ports/spec.md` — substantial trim; same SHALL coverage retained.
- `yascheduler/domain/ports.py` — markup enriched on existing `CLASS_*` regions and on selected `METHOD_*` regions. Code semantics unchanged; only comments move.
- No change to: any port signature, any concrete adapter, DB schema, migrations, public API, CLI, other specs, other source files.
- No new tests required; existing port-conformance tests continue to pass unchanged.
