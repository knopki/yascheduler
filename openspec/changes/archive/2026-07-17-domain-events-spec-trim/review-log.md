## proposal / specs / tasks Round 1 — 2026-07-17

Single comprehensive self-review of all three artifacts (proposal.md, specs/
domain-events-and-dispatch/spec.md, tasks.md) written in one pass. Reviewer =
author. The review is run against the GRACE-lite review checklist, the
project's `domain-entities-spec-trim` and `orchestrator-spec-dehydrate`
precedents, and the user's explicit constraints:

- "выдумывать поля нельзя" — no invented contract fields.
- "Использовать поля не по назначению нельзя" — fields must be used per their
  defined purpose.
- "новых полей типа SHALL NOT" — no invented `SHALL NOT` pseudo-normative
  enumerations of absent code in the spec.
- "записывания в RATIONALE просто всего подряд" — RATIONALE is Q/A only, not a
  dumping ground.
- "PURPOSE должно быть WHY, а не WHAT" — every PURPOSE states why, not what.
- "блок должен обрамлять всё содержимое" — a `CLASS_*` region encloses the full
  class body, not only the contract header.

Validation run before review:
- `openspec validate --all --json` → 22/22 passed (1 new change + 1 pre-existing
  change + 20 specs), exit 0.
- `grep -nE "SHALL NOT|no such|do not exist"` on the spec delta → 0 hits in
  requirement text; 1 hit in a scenario `THEN` clause (the observable
  "`task_id` is a `TaskId` instance (not a bare `int`)" assertion — kept).
- `grep` for `with_event|record_event|pull_events|functools|asdict` on the spec
  delta → 0 hits.

### 🔴 Issues (found and fixed in this round)

- **Spec delta requirement 1 carried a redundant implementation-flow
  paragraph.** The original draft had a second paragraph after the field
  declaration: "`task_id` SHALL be a `TaskId` value object (not a bare `int`);
  `.value` SHALL be unwrapped at external boundaries (e.g. webhook
  serialization)." The "not a bare int" half is redundant with the field type
  `task_id: TaskId` already stated in the same requirement; the "unwrapped at
  external boundaries" half is construction-site flow that the proposal moves
  to `events.py::MODULE_CONTRACT INVARIANTS` (task 1.1). Fixed by deleting the
  paragraph; the `#### Scenario: All events carry webhook fields and TaskId`
  assertion still locks the observable property.

- **Spec delta requirement 2 carried a redundant "closed-set + emission-site"
  paragraph.** The original draft appended: "`TaskAllocated` and `TaskAbandoned`
  carry `node_id: NodeId`. `TaskAbandoned` SHALL carry a non-`None` `node_id`;
  the event is emitted only when a node exists. `TaskCompleted` carries
  `local_folder: str` and SHALL NOT carry a `has_errors` field." Three
  complaints: (a) the "TaskAllocated and TaskAbandoned carry node_id" sentence
  duplicates the bullet list above it; (b) the "non-None node_id" + "emitted
  only when a node exists" is implementation flow that the proposal moves to
  `CLASS_TaskAbandoned RATIONALE` (task 1.7); (c) "`SHALL NOT` carry a
  `has_errors` field" is exactly the invented-normative pattern the user
  called out — the scenario `#### Scenario: TaskCompleted carries local_folder
  and no has_errors` already asserts the closed set observably, and the "why"
  goes to `CLASS_TaskCompleted RATIONALE` (task 1.5). Fixed by deleting the
  paragraph in full; the scenario is the sole acceptance criterion, the
  rationale lives in code.

### 🟡 Suggestions (considered, not blocking)

- **Spec delta line count is modest (~20% trim, 220 → 175 lines).** This is
  intentional. The `domain-events-and-dispatch` spec is already mostly
  behavioral scenarios — most of the bloat the user called out was concentrated
  in 4–5 specific paragraphs (the `.value`-extraction flow, the `pull_events`
  `SHALL NOT`, the absent-primitive enumerations, the `WebhookPayload`-builds-
  from narration). Those are gone. The use-case-to-event mapping table and all
  22 behavioral scenarios are preserved verbatim. A larger trim would require
  dropping behavioral scenarios, which the proposal explicitly forbids
  ("No behavioral change; every existing scenario survives").

- **Tasks 1.2–1.7 add six new `CLASS_*` regions to `events.py`.** Each is a
  small frozen dataclass (3–4 lines). The GRACE Python rule says "if an entity
  is annotated by markup, it must always be wrapped in a region" — but it also
  says "Do not mark up trivial code". A frozen dataclass with a single field
  COULD arguably be skipped under the trivial-code exemption. The proposal
  chose to mark them up anyway because (a) they are PUBLIC types exported via
  `yascheduler.domain.__all__`, (b) several carry non-trivial `RATIONALE` that
  absorbs spec content (TaskCompleted, TaskAbandoned), (c) consistency — once
  one event subclass is marked, marking all six keeps the file navigable, and
  (d) the existing `MODULE_CONTRACT` already establishes markup for this file,
  so the "if an entity is annotated by markup" clause triggers. Acceptable as
  proposed; an alternative is to mark only TaskCompleted and TaskAbandoned
  (the two with rationale) and leave the trivial four bare. Stays as proposed.

- **Task 6.1 `WebhookPayload` `INVARIANTS` states `task_id` is a bare `int`
  "never a `TaskId` instance".** The field is declared `task_id: int = field()`
  — the type system already prevents assigning a `TaskId` (mypy/pyright would
  complain). The invariant is therefore partly redundant with the type
  declaration. The redundancy is acceptable because (a) it states the WHY
  (the bare `int` is what `dataclasses.asdict` needs to produce the wire
  shape), which connects to the `webhook_handler RATIONALE` in task 6.2, and
  (b) the existing `CLASS_TaskId` markup in `model.py` uses the same
  INVARIANTS-extends-beyond-the-type-system style ("not equal to a bare int").
  Stays as proposed.

- **Task 1.1 expands `MODULE_CONTRACT INVARIANTS` in `events.py`.** The
  current INVARIANTS line is `Every event is frozen; task_id is always
  present.` — a single line. The task adds three more invariant bullets about
  construction-site flow. Multi-line INVARIANTS in `MODULE_CONTRACT` is
  consistent with `model.py::MODULE_CONTRACT` (which has 4-line
  `INVARIANTS`). Stays as proposed.

### ✅ Strengths

- **Every observable behavioral scenario from the original spec survives in
  the delta.** Scenario count pre/post: 22 → 22. The delta is purely
  MODIFIED-Requirements text trim + paragraph removal; no scenario deleted, no
  scenario reworded destructively. The proposal's "no behavioral change"
  promise is verifiable by `grep -c '^#### Scenario:'` on the pre/post spec.

- **All spec prose moved out maps to a concrete code-contract destination.**
  Each piece of removed prose has a corresponding task that places it in the
  correct GRACE field:
  - construction-site `.value` flow → `events.py::MODULE_CONTRACT INVARIANTS`
    (task 1.1) + `webhook.py::FUNC_webhook_handler RATIONALE` (task 6.2).
  - "no `with_event`/`record_event`/`pull_events` primitives" →
    `model.py::CLASS_Task RATIONALE` (task 2.1) + `postgres_uow.py::
    METHOD_collect_events RATIONALE` (task 5.1).
  - "why `TaskAbandoned.node_id` is `NodeId` not `NodeId | None`" →
    `events.py::CLASS_TaskAbandoned RATIONALE` (task 1.7).
  - "why `TaskCompleted` has no `has_errors`" → `events.py::CLASS_TaskCompleted
    RATIONALE` (task 1.5).
  - "functools.partial to bind dependencies" → `message_bus.py::
    METHOD_register RATIONALE` (task 4.1).
  - "builds `WebhookPayload(task_id=event.task_id.value, ...)` — does NOT read
    `node_id`" → `webhook.py::FUNC_webhook_handler ENSURES` (task 6.2).
  - "dataclasses.asdict recurses into nested dataclasses" →
    `webhook.py::FUNC_webhook_handler RATIONALE` (task 6.2).
  No prose is silently dropped — every line tracked to a destination.

- **Zero invented contract fields.** Audit of every region the tasks touch:
  - `events.py::MODULE_CONTRACT` (task 1.1): uses `INVARIANTS` only — already
    a defined field.
  - `events.py::CLASS_*` (tasks 1.2–1.7): `PURPOSE` (required) +
    `INVARIANTS` + `RATIONALE` — all defined CLASS fields.
  - `model.py::CLASS_Task` (task 2.1): `RATIONALE` only — defined.
  - `uow.py::CLASS_AbstractUnitOfWork` (task 3.1): `PURPOSE` + `INVARIANTS` —
    defined.
  - `uow.py::METHOD_*` (tasks 3.2–3.3): `PURPOSE` only — defined.
  - `message_bus.py::METHOD_register` (task 4.1): `RATIONALE` only — defined.
  - `postgres_uow.py::METHOD_collect_events` (task 5.1): `RATIONALE` only —
    defined.
  - `webhook.py::CLASS_WebhookPayload` (task 6.1): `PURPOSE` + `INVARIANTS` —
    defined.
  - `webhook.py::FUNC_webhook_handler` (task 6.2): `ENSURES` + `RATIONALE` —
    both defined FUNC fields.
  No `EXAMPLE`/`NOTE`/`WARNING`/`SEE`/etc. invented.

- **No field is misused.** RATIONALE entries are all Q/A format (every task
  that adds RATIONALE specifies the Q and the A). INVARIANTS entries state
  properties that always hold (frozen, task_id-is-TaskId, wire shape), not
  rationale. ENSURES entries state postconditions observable after the call
  (no HTTP when webhook_url is None; payload built a specific way; exceptions
  suppressed). PURPOSE entries state WHY (the goal/need), not WHAT — audited
  per task: e.g. task 1.2 `DomainEvent.PURPOSE` is "anchor the per-transition
  payload the UoW dispatches so handlers receive an immutable record carrying
  everything they need without re-querying aggregates" (WHY: so handlers
  don't re-query), not "frozen dataclass base with three fields" (WHAT).

- **Every `CLASS_*` region task specifies full-block enclosure.** Tasks 1.2,
  1.3, 1.4, 1.5, 1.6, 1.7, 3.1, 6.1 each say "enclosing the FULL
  `@dataclass(frozen=True)` block (the decorator line through ... trailing
  blank line)". Task 1.8 spells out the enclosure rule as a verification
  step. This directly addresses the user's "блок должен обрамлять всё
  содержимое" constraint.

- **All referenced test files exist.** Verified via `ls tests/unit/`:
  `test_domain_events.py`, `test_domain_model.py`, `test_application_use_cases.
  py`, `test_persistence_adapter.py`, `test_message_bus.py`,
  `test_webhook_handler.py` all present. Tasks 3.5 and 5.2 were corrected in
  this round to point at `test_persistence_adapter.py` (which covers
  `PostgresUnitOfWork.collect_events` via `test_collect_events_preserves_
  shared_list`) instead of the non-existent `test_postgres_unit_of_work.py` /
  `test_abstract_unit_of_work.py`.

- **Spec delta validates cleanly.** `openspec validate --all --json` → 22/22
  pass. The MODIFIED-Requirements headers match the existing main spec
  requirement names exactly (whitespace-insensitive), so the archive step
  will apply correctly.

- **Follows the established precedent.** The proposal structure, the
  "markup-only, no behavioral change" framing, the Capabilities section
  (Modified only, no New), the Impact section enumerating per-file changes,
  the Non-Goals section, and the tasks.md group structure (per-file sections
  + final apply-and-verify section) all mirror `2026-07-17-domain-entities-
  spec-trim` and `2026-07-17-orchestrator-spec-dehydrate` row-for-row.

- **Non-Goals section explicit on the `WebhookPayload` field-type trap.**
  The implementation declares `custom_params: Mapping[str, Any]` (not
  `dict[str, object]`); the spec describes the wire shape, not the field
  type. The Non-Goals section states this is intentional and that the two
  agree on the wire shape — preventing a future implementer from "fixing" the
  field type and inadvertently touching behavior.

### Verdict: PASS

All 🔴 issues found in the round were fixed before the round closed (spec
delta trimmed of two redundant paragraphs; tasks 3.5 and 5.2 test-path
references corrected). All 🟡 suggestions are deliberate design choices
documented inline. No outstanding 🔴. The change is ready for implementation.

The implementation phase (apply tasks 1.1 – 7.7) is the next step — separate
from this proposal/specs/tasks review. The apply-phase reviewer should
re-verify, after implementation, that: (a) every `# region CLASS_*` block in
the changed files encloses the full class body, (b) no contract field is
invented, (c) every PURPOSE is a WHY, (d) `openspec validate --all --json`
still passes 22/22 (or 21/21 after this change archives), and (e) the
scenario count in `openspec/specs/domain-events-and-dispatch/spec.md` after
archive equals the pre-change count (22).
