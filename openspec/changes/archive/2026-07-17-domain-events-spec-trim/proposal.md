## Why

The `domain-events-and-dispatch` spec (220 lines, 7 requirements) mixes two
content kinds that the GRACE methodology assigns to code-local contracts, not to
spec text:

1. **Implementation flow and construction-site detail** — "`task_id` is a
   `TaskId`, not a bare `int`", "Events are constructed only inside `Task`
   transition methods ... each constructs the event with `task_id=self.task_id`
   (already a `TaskId` — no `.value` extraction at construction). At the webhook
   boundary, `.value` is extracted", "`webhook_handler` builds `WebhookPayload`
   (task_id=event.task_id.value, status=..., custom_params=...) — it does NOT
   read `node_id`". These describe how the code is wired; the field types and
   the public method signatures already carry the observable contract.
2. **Negative-space regression guards framed as invented normative language** —
   "No `with_event` or `record_event` primitives exist on `Task`", "No use case
   constructs `DomainEvent` subclasses directly or calls `record_event`/
   `with_event` (those methods do not exist on `Task`)", "it SHALL NOT call a
   `pull_events()` method (no such method exists)". The "SHALL NOT ... (no such
   thing exists)" pattern is a negative assertion against absent code — at best
   a `RATIONALE` Q/A on the class that owns the positive alternative, at worst
   pure drift bait.

This duplicates what `# region` contract markup already states (or, for several
public types in this very capability, *should* state but currently does not —
see Impact), leaves two sources that drift, and obscures the observable
behavioral scenarios (the WHEN/THEN contracts that are the spec's actual job).

Two public types in this capability currently lack the wrapping class region
that the GRACE Python rule requires ("if an entity is annotated by markup, it
must always be wrapped in a region"):

- `yascheduler/domain/events.py` declares `DomainEvent` + 5 subclasses as bare
  dataclasses under a `MODULE_CONTRACT` — no `CLASS_*` region encloses any of
  them.
- `yascheduler/infra/notifier/webhook.py::WebhookPayload` is a bare dataclass
  next to marked-up funcs.
- `yascheduler/application/uow.py::AbstractUnitOfWork` Protocol is a bare class
  next to a `MODULE_CONTRACT`.

## What Changes

- **MODIFIED `domain-events-and-dispatch`**: rewrite the spec to carry only
  behavioral contracts (requirements + Gherkin scenarios). Remove implementation
  mechanics (construction-site `.value` flow, internal mapping prose, "builds
  WebhookPayload ..." line-level narration), invented `SHALL NOT` enumerations
  of absent methods, and rationale prose that belongs as Q/A on the class that
  owns the positive alternative. Every observable behavioral scenario survives;
  the use-case-to-event mapping table stays (it IS the observable behavior).

- Add the missing `CLASS_*` regions required by the GRACE Python rule and
  extend existing regions with the rationale/invariants that leaves the spec,
  each in its correct contract field per its defined purpose:
  - `yascheduler/domain/events.py` — add `CLASS_DomainEvent`,
    `CLASS_TaskCreated`, `CLASS_TaskAllocated`, `CLASS_TaskCompleted`,
    `CLASS_TaskFailed`, `CLASS_TaskAbandoned`, each enclosing the full
    `@dataclass` block (`@dataclass(frozen=True)` line through the last field
    and trailing blank line, to `# endregion`). `DomainEvent.PURPOSE` states
    the why; per-subclass `RATIONALE` carries the design-choice Q/As that
    leave the spec (why `TaskAbandoned.node_id` is `NodeId` not `NodeId |
    None`; why `TaskCompleted` has no `has_errors`).
  - `yascheduler/domain/model.py` — extend `CLASS_Task` `INVARIANTS` /
    `RATIONALE` with the "transition methods own event construction; no
    `record_event`/`with_event`/`pull_events` primitives exist" rationale that
    leaves the spec.
  - `yascheduler/application/uow.py` — add `CLASS_AbstractUnitOfWork` region
    wrapping the entire `Protocol` class; add `METHOD_collect_events` and
    `METHOD_publish_events` regions with `PURPOSE`/`ENSURES`.
  - `yascheduler/application/message_bus.py` — add `RATIONALE` to
    `METHOD_register` covering the `functools.partial` binding pattern.
  - `yascheduler/infra/persistence/postgres_uow.py` — extend
    `METHOD_collect_events` `RATIONALE` with the "reads `task.events` directly;
    no `pull_events()` method exists" Q/A that leaves the spec.
  - `yascheduler/infra/notifier/webhook.py` — add `CLASS_WebhookPayload`
    region wrapping the full `@dataclass` block; extend `FUNC_webhook_handler`
    with `ENSURES` (wire shape built, `node_id` not read) and `RATIONALE` (why
    `.value` is extracted at construction — `dataclasses.asdict` recursion).

- No behavioral change. No code logic change. No test change. Every observable
  scenario in the trimmed spec MUST remain covered by the existing unit tests
  in `tests/unit/test_domain_events.py`, `tests/unit/test_message_bus.py`,
  `tests/unit/test_webhook_handler.py`, and the event-recording scenarios in
  `tests/unit/test_application_use_cases.py`.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `domain-events-and-dispatch`: relocate construction-site `.value` flow,
  implementation prose, and invented `SHALL NOT ... (no such thing exists)`
  enumerations out of the spec text and into the GRACE code contracts of
  `events.py`, `model.py`, `uow.py`, `message_bus.py`, `postgres_uow.py`, and
  `webhook.py`. Slim the spec to observable behavior + acceptance scenarios.
  Add the missing `CLASS_*` regions required by the GRACE Python rule. No
  behavioral change; every existing scenario survives (possibly reworded as a
  pure observable assertion, never deleted).

## Impact

- **Specs**: `openspec/specs/domain-events-and-dispatch/spec.md` rewritten
  (slimmed, ~220 → ~130–150 lines). `openspec validate --all --json` must still
  pass after the change.
- **Code (markup only, no logic)**:
  - `yascheduler/domain/events.py` — 6 new `CLASS_*` regions (full-block
    enclosure per the Python rule), each with `PURPOSE` and per-class
    `INVARIANTS` / `RATIONALE` as needed.
  - `yascheduler/domain/model.py` — `CLASS_Task` region extended with
    `INVARIANTS` / `RATIONALE` covering the "no record_event/with_event/
    pull_events primitives" rationale that leaves the spec.
  - `yascheduler/application/uow.py` — new `CLASS_AbstractUnitOfWork`,
    `METHOD_collect_events`, `METHOD_publish_events` regions.
  - `yascheduler/application/message_bus.py` — `METHOD_register` gains
    `RATIONALE` for the `functools.partial` pattern.
  - `yascheduler/infra/persistence/postgres_uow.py` — `METHOD_collect_events`
    gains `RATIONALE` (no `pull_events()`).
  - `yascheduler/infra/notifier/webhook.py` — new `CLASS_WebhookPayload`;
    `FUNC_webhook_handler` gains `ENSURES` + `RATIONALE`.
- **Tests**: no change. Existing scenarios in the slimmed spec remain the
  acceptance criteria; existing tests already assert them. A passing
  `uv run pytest -m unit` run on the events/bus/webhook/use-case test files
  after the change is the regression guard.
- **Public surface**: none. No CLI, API, INI, DB schema, or log-format change.
- **Pilot scope**: this change ONLY dehydrates the `domain-events-and-dispatch`
  spec. Other specs are explicitly out of scope. Follows the pattern set by
  `2026-07-17-domain-entities-spec-trim` and
  `2026-07-17-orchestrator-spec-dehydrate`.
- **Non-goals**:
  - No change to the `WebhookPayload` field types (`task_id: int`, `status:
    int`, `custom_params: Mapping[str, Any]` via `field(default_factory=dict)`)
    — the spec describes the wire shape, the code defines the field types; the
    two already agree on the wire shape.
  - No relocation of the use-case-to-event mapping out of this capability —
    it stays here; the mapping IS the observable behavior of the dispatch
    capability.
  - No spec split (unlike `domain-entities-spec-trim`, which spawned
    `engine-config-parsing`); all 7 requirements remain in this capability.
