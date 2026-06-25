# Explore Brief — queue-dataclass-migration

## Decision context

`yascheduler/application/queue.py` uses `attrs` (`@define(frozen=True)`) for the
`UMessage` record. The file carries a `# FIXME: use dataclasses instead of attrs`
marker. This change migrates `UMessage` to stdlib `dataclasses` and is intended
as the **pilot** for a broader (multi-change) attrs → dataclasses migration
across `config/*` and `infra/*`. Other files are explicitly out of scope.

## Scope

- **In scope**: `UMessage` class in `yascheduler/application/queue.py`; its unit
  tests in `tests/unit/test_queue.py`; spec wording in
  `openspec/specs/testing-infrastructure/spec.md` and
  `openspec/specs/testing-unit/spec.md` that describe `UniqueQueue`/`UMessage`
  deduplication semantics.
- **Out of scope**: `UniqueQueue` class (no attrs usage — only bare class-level
  annotations); every other attrs usage in `config/*`, `infra/cloud/*`,
  `infra/ssh/*`; dropping the `attrs` runtime dependency (it remains, other
  files still use it); bumping `requires-python`.

## Rejected alternatives

- **Migrate everything, drop attrs (path C)**: rejected — `config/utils.py`,
  `config/cloud.py`, `config/engine.py` are heavily coupled to attrs
  (`validators`, `converters`, `Attribute`, `fields()`, `asdict`, `evolve`);
  one big change has too much blast radius and too many semantic pitfalls per
  module. Do it as separate changes per package.
- **Migrate only `queue.py`, leave the invariant implicit (path A with P2)**:
  rejected — preserves an oddball "full-message eq, id-only hash" semantics
  that no caller relies on and that is hard to express in stdlib dataclasses
  without ugly manual `__hash__`.
- **`@dataclass(frozen=True, slots=True)`**: rejected — `slots=True` requires
  Python 3.10; project minimum is `>=3.9`. Use `@dataclass(frozen=True)` with
  an explicit `__slots__ = ("id", "payload")` declaration instead (decision S2).

## Final approach

### Labels / dimensions

- **Migration target**: `UMessage` only, in `yascheduler/application/queue.py`.
- **Decorator**: `@dataclass(frozen=True)` with manual `__slots__`.
- **Payload field**: `payload: TUMsgPayload = field(compare=False)`.
- **Equality invariant (P1)**: two `UMessage` instances are equal iff their
  `id` values are equal. `payload` does not participate in `__eq__` or
  `__hash__`.
- **Hash invariant**: `__hash__` is computed over `id` only. `payload` may be
  unhashable.
- **Dedup invariant in `UniqueQueue.put`**: a put is skipped iff an `UMessage`
  with the same `id` is already in `_queue` (deque, eq) or `_done_pending`
  (set, hash+eq). Dedup is **first-wins** (existing item is kept; the new one
  is silently dropped) — unchanged from current behavior.
- **`UniqueQueue` itself**: untouched.
- **Module version**: `queue.py` `v1.7.0` → `v1.8.0` (minor: behavioral
  refinement of equality, even if observably no-op for current callers).

### Spec wording choice (W2 — full contract)

In `openspec/specs/testing-infrastructure/spec.md`, strengthen the
deduplication requirement to:

> deduplication key is the message `id`; two `UMessage` instances with equal
> `id` are duplicates regardless of `payload`; `payload` does not participate
> in `__eq__` or `__hash__`, therefore an unhashable `payload` is valid.

In `openspec/specs/testing-unit/spec.md`, declarative edit to align the prose
with the above (no new capability, no new requirement category).

### Test additions (T1 + T2 + T3)

In `tests/unit/test_queue.py`, add:

- **T1** `test_dedup_by_id`: put `UMessage("a", "x")` then
  `UMessage("a", "y")`; assert `qsize() == 1`. Pins the P1 invariant.
- **T2** `test_dedup_first_wins`: same setup; assert the queued item is the
  first one (`payload == "x"`), not the second. Pins first-wins semantics.
- **T3** `test_unhashable_payload`: construct `UMessage("a", {"k": "v"})`
  (dict is unhashable), put, get, item_done; assert no raise. Canary that
  proves `payload` is excluded from `__hash__`.

## Cross-module data flow

```
  yascheduler/application/orchestrator.py
    │ (only consumer)
    │ imports UMessage, UniqueQueue
    ▼
  yascheduler/application/queue.py
    UMessage  ← MIGRATED (attrs → dataclass)
    UniqueQueue ← unchanged
    │
    │ UMessage instances flow through:
    │   UMessage(node.ip, node)     # id=node.ip, payload=Node
    │   UMessage(task.task_id, task)# id=task_id, payload=Task
    │   UMessage(ip, ip)            # id=ip, payload=ip
    ▼
  tests/unit/test_queue.py  ← +3 tests
```

No other module imports `UMessage` or `attrs` from `queue.py`. `queue.py`
itself imports nothing project-internal (`DEPENDS: none`).

## Knowledge graph

`docs/knowledge-graph.xml` `M-QUEUE` record:
- `<path>`, `<purpose>`, `<depends>`, public `<annotations>` — all unchanged
  (`UMessage`/`UniqueQueue`/`TUMsgId`/`TUMsgPayload` surface preserved).
- **No graph edit required** for this change. Only `CHANGE_SUMMARY` in the
  file itself gets a new entry.

## Public API stability

`UMessage`/`UniqueQueue` are **internal symbols** (per archived change
`relocate-root-utils`): not re-exported, sole consumer is `orchestrator.py`.
AGENTS.md public-API-stability constraint does **not** apply.

## Static checks after implementation

- `uv run zuban check`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run lint-imports` (verifies `from attrs import …` is gone from
  `queue.py`)
- `uv run pytest -m unit` (queue tests pass, orchestrator tests unaffected)
- `python3 scripts/grace_check.py` (markup valid, file sizes within limits)
- `openspec validate --all --json` (specs delta valid)

## Open questions

None. All decisions captured above.
