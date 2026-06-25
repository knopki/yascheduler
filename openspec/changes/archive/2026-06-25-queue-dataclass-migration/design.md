## Context

`yascheduler/application/queue.py` defines `UMessage` — a frozen two-field
record used as the message type flowing through `UniqueQueue` (an
`asyncio.Queue` subclass with id-based deduplication). Today `UMessage` is
modeled with `attrs. define(frozen=True)`:

```python
from attrs import define, field

@define(frozen=True)
class UMessage(Generic[TUMsgId, TUMsgPayload]):
    id: TUMsgId = field()
    payload: TUMsgPayload = field(hash=False)
```

Two properties of this definition matter for the migration:

1. **attrs `@define` is slotted by default.** Instances have no `__dict__`; the
   frozen contract is airtight (no ad-hoc attribute can be set).
2. **`field(hash=False)` on `payload`** is the only attrs-specific field
   feature used anywhere in `queue.py`. It produces an asymmetry:
   `__eq__` compares both `id` and `payload`, but `__hash__` is computed from
   `id` only. This combination is **not directly expressible in stdlib
   `dataclasses`**, where `compare=False` removes a field from both `__eq__`
   and `__hash__`.

The deduplication logic in `UniqueQueue.put` relies on both protocols:

```python
async def put(self, item):
    if item in self._queue or item in self._done_pending:   # deque→eq ; set→hash+eq
        return
    await super().put(item)
```

`_queue` is a `deque` (membership uses `__eq__`); `_done_pending` is a `set`
(membership uses `__hash__` then `__eq__`). Whatever equality invariant we
choose must be consistent across both containers.

No caller relies on the current asymmetry. Every producer in `orchestrator.py`
binds `id` and `payload` one-to-one (`UMessage(node.ip, node)`,
`UMessage(task.task_id, task)`, `UMessage(ip, ip)`), so the "same id, different
payload" case never arises at runtime. The migration is therefore the moment
to **make the intended invariant explicit** rather than faithfully reproduce an
odd and unstated one.

Project constraints (from `pyproject.toml` and `AGENTS.md`):

- `requires-python >= 3.9` → `dataclass(slots=True)` (added in 3.10) is not
  available.
- `attrs>=22.2.0` remains a declared dependency — other modules
  (`config/*`, `infra/cloud/*`, `infra/ssh/*`) still use it. This change does
  not remove it.
- `UMessage`/`UniqueQueue` are internal symbols (archived change
  `relocate-root-utils`): no public-API-stability constraint applies.

## Goals / Non-Goals

**Goals:**

- Replace `attrs` with stdlib `dataclasses` for `UMessage` only.
- Preserve slotted, frozen, immutable-instance semantics (no `__dict__`, no
  ad-hoc attributes, no field mutation).
- Establish and pin an explicit, documented equality invariant: equality and
  hash are determined by `id` alone.
- Add unit tests that pin the chosen invariant so a future regression (e.g.
  someone drops `compare=False`) is caught.
- Strengthen the relevant spec wording so the invariant is contract-level,
  not implementation-level.

**Non-Goals:**

- Migrating any other module (`config/*`, `infra/*`). Those are subsequent
  changes.
- Removing the `attrs` runtime dependency.
- Changing `UniqueQueue` (no attrs usage there).
- Changing the `requires-python` floor.
- Changing `UMessage`'s public surface (field names, order, Generic
  parameters, constructor signature).
- Re-exporting `UMessage`/`UniqueQueue` anywhere new.

## Decisions

### D1. `@dataclass(frozen=True, eq=False)` + manual `__eq__`/`__hash__` + manual `__slots__` (choice S2+B)

The class becomes:

```python
from dataclasses import dataclass

@dataclass(frozen=True, eq=False)
class UMessage(Generic[TUMsgId, TUMsgPayload]):
    __slots__ = ("id", "payload")
    id: TUMsgId
    payload: TUMsgPayload

    def __eq__(self, other):
        if not isinstance(other, UMessage):
            return NotImplemented
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)
```

**Why not `@dataclass(frozen=True, slots=True)`** — needs Python 3.10;
project floor is `>=3.9`. Reject.

**Why not plain non-slotted `@dataclass(frozen=True)`** — would reintroduce
`__dict__` on instances and open a small immutability hole (ad-hoc attribute
assignment like `m.ad_hoc = 1` would succeed despite "frozen"). For a
transient queue message the memory delta is negligible, but the semantic
regression from "slotted frozen" (current attrs) to "non-slotted frozen" is
real and avoidable. Choose slots.

**Why not bump `requires-python` to 3.10 to get `slots=True`** — out of scope
for this change, and AGENTS.md discourages coupling unrelated version bumps to
feature work.

**Why manual `__eq__`/`__hash__` instead of `field(compare=False)`** — the
`__slots__ = ("id", "payload")` + `payload: TUMsgPayload = field(compare=False)`
combination originally favored in early drafts is **mutually incompatible**:
`dataclasses.field(...)` (with or without a default) installs a `Field`
object as a class variable for that attribute name, which conflicts with a
same-named `__slots__` entry and raises
`ValueError: 'payload' in __slots__ conflicts with class variable` at class
creation (verified empirically on CPython 3.9–3.13). The
`__slots__`-with-defaults pitfall noted under Risks was therefore
under-specified: the conflict applies to **any** use of `field()`, not only
fields with defaults.

`eq=False` suppresses the dataclass-generated `__eq__` (and `__hash__`), then
manual methods establish the id-only invariant directly. This preserves all
stated goals: slotted (no `__dict__`, ad-hoc attrs blocked by `__slots__`),
frozen (declared fields immutable), id-only equality, id-only hash, and
unhashable `payload` accepted (payload never participates in `__hash__` or
`__eq__`).

### D2. Id-only equality and hash (manual; choice P1, mechanism revised)

This is the central semantic decision. The three candidate behaviors:

| Variant                                | `__eq__` compares | `__hash__` over | Same-id-diff-payload |
| -------------------------------------- | ----------------- | --------------- | -------------------- |
| Current attrs (`hash=False` on payload)| `id` + `payload`    | `id` only       | coexist (not dupes)  |
| dataclass default (no `eq=False`)      | `id` + `payload`    | `id` + `payload` | coexist (not dupes)  |
| **manual `__eq__`/`__hash__` (chosen)** | `id` only          | `id` only       | **deduplicated**     |

Choosing manual id-only `__eq__`/`__hash__` (with `@dataclass(eq=False)`):

- Makes `__eq__` and `__hash__` consistent (both keyed on `id`), so `deque`
  membership and `set` membership in `UniqueQueue.put` agree.
- Matches the de-facto contract of every current producer in `orchestrator.py`
  (one id ↔ one payload).
- Allows `payload` to be unhashable (e.g. a mutable `dict` or a non-frozen
  `Task`/`Node`), because it no longer participates in `__hash__`. This was
  also true under attrs `hash=False` and is preserved.
- Is compatible with manual `__slots__` (no `field()` class-variable conflict
  — see D1).

**Why not preserve the current asymmetry (P2)** — would require a hand-written
`__hash__` on top of a frozen dataclass. The semantics it preserves ("equal
only if both fields match, but hash only by id") are not relied on by any
caller and are not intuitive. Reject.

**Why not `field(compare=False)` (rejected after empirical check)** —
incompatible with manual `__slots__` (see D1): `field()` installs a class
variable that clashes with the `__slots__` entry, raising `ValueError` at
class creation. Manual `__eq__`/`__hash__` achieves the same invariant without
that conflict.

### D3. Dedup is first-wins (preserved)

`UniqueQueue.put` keeps the existing early-return: when the incoming item is
already in `_queue` or `_done_pending`, the **existing** item is kept and the
**new** one is silently dropped. T2 pins this. No design change here — calling
it out explicitly so the test is not mistaken for last-wins.

### D4. Three tests pin the invariant

| Test                       | Setup                                            | Asserts                                         | Pins                          |
| -------------------------- | ------------------------------------------------ | ----------------------------------------------- | ----------------------------- |
| `test_dedup_by_id` (T1)    | put `M("a","x")`; put `M("a","y")`               | `qsize() == 1`                                  | P1 invariant                  |
| `test_dedup_first_wins` (T2)| same setup                                      | queued item's `payload == "x"`                  | first-wins (D3)               |
| `test_unhashable_payload` (T3)| construct `M("a", {"k":"v"})`; put; get; `item_done` | no raise                                     | `payload` excluded from hash  |

T3 is the canary: if a future edit drops `compare=False`, an unhashable
`payload` would crash at construction or at set insertion, and T3 would catch
it. Without T3 the regression could slip past until a real unhashable payload
hits production.

### D5. Spec wording (choice W2 — full contract)

`openspec/specs/testing-infrastructure/spec.md` currently says (around line 29):

> Tests for `UniqueQueue` SHALL cover: put/get, deduplication (same `UMessage`
> put twice → only one in queue), item_done tracking (allows re-queueing after
> done), and `task_done` raising `NotImplementedError`.

"same `UMessage`" is too weak to express the chosen invariant. W2 strengthens
it to state explicitly:

- deduplication key is the message `id`;
- two `UMessage` instances with equal `id` are duplicates regardless of
  `payload`;
- `payload` does not participate in `__eq__` or `__hash__`;
- therefore an unhashable `payload` is valid.

`openspec/specs/testing-unit/spec.md` (around line 222) gets a declarative
alignment of its `UMessage` test-description prose with the same invariant. No
new capability, no new requirement category.

## Risks / Trade-offs

- **[Behavioral refinement: same-id-different-payload now deduplicates]**
  → Mitigation: no current producer emits that pattern; new tests pin the
  chosen behavior; spec wording makes the invariant contract-level. If a
  future producer genuinely needs same-id-different-payload coexistence, that
  would be a separate change proposing a different invariant.
- **[Manual `__slots__` is slightly more boilerplate than `slots=True`]**
  → Trade-off accepted to keep `requires-python >= 3.9`. Two lines, no
  runtime cost, no maintenance burden.
- **[`__slots__` + `dataclasses.field()` conflict]**
  → `field(compare=False)` (originally drafted in D2) was rejected because
  `field()` installs a class variable that clashes with a same-named
  `__slots__` entry (`ValueError: 'payload' in __slots__ conflicts with class
  variable`), verified on CPython 3.9–3.13. Resolution: do not use `field()`
  for `payload`; declare it as a plain annotation and establish id-only
  equality via manual `__eq__`/`__hash__` with `@dataclass(eq=False)` (D1/D2).
- **[Someone adds a third field to `UMessage` later and forgets to update
  `__slots__`]**
  → Mitigation: a third field declared without an `__slots__` entry would
  raise `AttributeError` at instance construction time on a slotted frozen
  dataclass (the field would have no slot to live in). Failure is loud, at
  import/first-instantiation time, not silent at runtime. (Verified
  empirically on CPython 3.x.) Note: adding a third field with a `field()`
  default would also trip the `__slots__`-class-variable conflict described
  above, so any future field addition must use a plain annotation plus a
  matching `__slots__` entry.
- **[`__slots__` interacts awkwardly with default values on dataclass
  fields]**
  → Not a concern here: both fields are required (no defaults), and neither
  uses `field()`, so the well-known `__slots__`-with-defaults pitfall does
  not apply. The broader `field()`-vs-`__slots__` conflict is addressed in
  D1/D2 by avoiding `field()` entirely.
- **[Reviewer / contributor unfamiliar with manual `__eq__`/`__hash__` on a
  frozen dataclass]**
  → Mitigation: the spec wording and the inline test names
  (`test_unhashable_payload`) document the intent at the contract and test
  level. The CHANGE_SUMMARY in `queue.py` also notes the invariant and the
  mechanism.

## Migration Plan

Single-process, single-file code swap; no deployment orchestration needed.

1. Edit `yascheduler/application/queue.py`:
   - Replace `from attrs import define, field` with
     `from dataclasses import dataclass` (no `field` import — `field()` is
     not used).
   - Replace the `@define(frozen=True)` decorator and field definitions per
     D1/D2 (`@dataclass(frozen=True, eq=False)`, plain annotations, manual
     `__eq__`/`__hash__`).
   - Bump `VERSION` from `1.7.0` to `1.8.0`.
   - Add a `CHANGE_SUMMARY` entry recording the migration, the chosen
     invariant, and the mechanism (manual eq/hash + slots).
2. Add the three tests (T1/T2/T3) to `tests/unit/test_queue.py` with their
   `START_CONTRACT:` blocks (per GRACE-lite).
3. Apply the spec deltas (W2) to `testing-infrastructure/spec.md` and the
   declarative alignment to `testing-unit/spec.md`.
4. Run static checks and tests (see Verification below).

**Rollback**: revert the single commit. No data, no schema, no config, no
external state involved.

**Verification**:

- `uv run pytest -m unit` (queue tests pass; orchestrator tests unaffected).
- `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run lint-imports` (confirms `from attrs import …` is gone from
  `queue.py`).
- `python3 scripts/grace_check.py` (markup valid, file sizes within limits).
- `openspec validate --all --json` (spec deltas valid).

## Open Questions

None. All decisions captured above.
