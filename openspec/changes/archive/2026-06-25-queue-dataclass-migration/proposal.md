## Why

`yascheduler/application/queue.py` carries a `# FIXME: use dataclasses instead
of attrs` marker on its only attrs-modeled class, `UMessage`. `attrs` is a
third-party dependency; `dataclasses` is stdlib. The current
`payload: TUMsgPayload = field(hash=False)` produces a non-obvious equality
semantics (full-message `__eq__`, id-only `__hash__`) that no caller relies on,
no test pins, and no spec states — migrating is the moment to make the
invariant explicit. This change is also intended as the **pilot** for a wider
multi-change attrs → dataclasses migration across `config/*` and `infra/*`,
validating the pattern on the smallest, lowest-risk module first.

## What Changes

- Migrate `UMessage` in `yascheduler/application/queue.py` from
  `@define(frozen=True)` (attrs) to `@dataclass(frozen=True, eq=False)`
  (stdlib `dataclasses`), with an explicit `__slots__ = ("id", "payload")`
  declaration (since `dataclass(slots=True)` requires Python 3.10 and the
  project minimum is `>=3.9`).
- Establish id-only equality and hash via **manual `__eq__`/`__hash__`**
  (with `@dataclass(eq=False)`): two `UMessage` instances are equal iff their
  `id` values are equal; `payload` does not participate in `__eq__` or
  `__hash__`. This matches the de-facto behavior of every current caller in
  `orchestrator.py` (id uniquely determines payload in all three producer
  patterns).
- `payload` is declared as a plain annotation (`payload: TUMsgPayload`) — no
  `field()`. The originally-drafted `payload: TUMsgPayload = field(compare=False)`
  was rejected because `dataclasses.field(...)` installs a class variable
  that conflicts with a same-named `__slots__` entry (raises
  `ValueError: 'payload' in __slots__ conflicts with class variable` at class
  creation, verified on CPython 3.9–3.13). Manual `__eq__`/`__hash__` achieves
  the same invariant without that conflict and keeps `__slots__` (no
  `__dict__`, ad-hoc attributes blocked).
- Remove the `from attrs import define, field` import from `queue.py`.
- Add three unit tests in `tests/unit/test_queue.py`:
  `test_dedup_by_id`, `test_dedup_first_wins`, `test_unhashable_payload`.
- Strengthen the deduplication requirement wording in
  `openspec/specs/testing-infrastructure/spec.md` and declaratively align the
  prose in `openspec/specs/testing-unit/spec.md` to state the id-only dedup
  invariant and that `payload` is excluded from `__eq__`/`__hash__`
  (unhashable payloads are valid).
- `UniqueQueue` is **unchanged** (it has no attrs usage — only bare class-level
  annotations for type checkers).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `testing-infrastructure`: strengthen the `UniqueQueue` deduplication
  requirement from "same `UMessage` put twice" to an explicit id-only invariant
  (two messages with equal `id` are duplicates regardless of `payload`;
  `payload` is excluded from `__eq__`/`__hash__`; unhashable `payload` is
  valid).
- `testing-unit`: declarative alignment of the `UMessage`/`UniqueQueue` test
  description with the id-only dedup invariant above (no new requirement
  category, no new scenario beyond what the prose already implies).

## Impact

- **Code**: `yascheduler/application/queue.py` (only `UMessage`; `UniqueQueue`
  untouched), `tests/unit/test_queue.py` (3 new tests).
- **API**: `UMessage` and `UniqueQueue` are internal symbols (per archived
  change `relocate-root-utils` — not re-exported, sole consumer is
  `orchestrator.py`). No public-API surface affected; AGENTS.md
  public-API-stability constraint does not apply.
- **Behavioral refinement**: under P1, two `UMessage(same_id, different_payload)`
  instances that previously coexisted in the queue will now be deduplicated.
  No current producer emits same-id-different-payload, so the change is
  observably no-op for existing callers; the new tests pin the chosen
  invariant against future regressions.
- **Dependencies**: `attrs>=22.2.0` **remains** a project dependency — other
  modules in `config/*`, `infra/cloud/*`, `infra/ssh/*` still use it. This
  change does not remove it. Subsequent changes will migrate those packages.
- **Python version**: unchanged (`>=3.9`). The manual `__slots__` approach is
  chosen precisely to avoid requiring 3.10's `dataclass(slots=True)`.
- **Systems**: none. The queue is in-process; no serialization or IPC surface.
- **Knowledge graph**: no edit to `docs/knowledge-graph.xml` required — the
  `M-QUEUE` public surface (`UMessage`/`UniqueQueue`/`TUMsgId`/`TUMsgPayload`)
  and `DEPENDS: none` are unchanged. Only the file-local `CHANGE_SUMMARY` in
  `queue.py` gets a new entry.
