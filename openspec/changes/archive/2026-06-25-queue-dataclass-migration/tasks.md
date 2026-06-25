## 1. Migrate `UMessage` class in `yascheduler/application/queue.py`

- [x] 1.1 Replace `from attrs import define, field` with `from dataclasses import dataclass` (no `field` import — `field()` is not used)
- [x] 1.2 Replace the `@define(frozen=True)` decorator on `UMessage` with `@dataclass(frozen=True, eq=False)` and add `__slots__ = ("id", "payload")` immediately **after** the existing `"""Async queue message"""` docstring (placing `__slots__` first would orphan the docstring and set `UMessage.__doc__` to `None`)
- [x] 1.3 Declare both fields as plain annotations (`id: TUMsgId`, `payload: TUMsgPayload` — no `field()`); add manual `__eq__` (returns `NotImplemented` for non-`UMessage`, else compares `id`) and `__hash__` (returns `hash(self.id)`) keyed on `id` only. (`field(compare=False)` was rejected — it conflicts with `__slots__`, see design D1/D2.)
- [x] 1.4 Remove the `# FIXME: use dataclasses instead of attrs` comment (line 22)
- [x] 1.5 Bump `VERSION` from `1.7.0` to `1.8.0`
- [x] 1.6 Add a `CHANGE_SUMMARY` entry: `LAST_CHANGE: v1.8.0 - Migrated UMessage from attrs to stdlib dataclasses; equality and hash are now keyed on id only via manual __eq__/__hash__ with eq=False (payload excluded; field(compare=False) was rejected because it conflicts with __slots__); manual __slots__ retained for immutability parity with prior attrs @define.`
- [x] 1.7 Visually confirm `UniqueQueue` is **untouched** (its class-level annotations are not attrs-modeled and require no changes)

## 2. Add unit tests in `tests/unit/test_queue.py`

- [x] 2.1 Add `test_dedup_by_id` (T1): put `UMessage("a", "x")` then `UMessage("a", "y")`; assert `queue.qsize() == 1`. Include a `START_CONTRACT: test_dedup_by_id` block.
- [x] 2.2 Add `test_dedup_first_wins` (T2): same setup as T1; additionally assert the retained item's `payload == "x"` (first-wins, not last-wins). Include a `START_CONTRACT: test_dedup_first_wins` block.
- [x] 2.3 Add `test_unhashable_payload` (T3): construct `UMessage("a", {"k": "v"})` (dict is unhashable), put, `get`, `item_done`; assert no exception is raised. Include a `START_CONTRACT: test_unhashable_payload` block.
- [x] 2.4 Update the `MODULE_MAP` in `tests/unit/test_queue.py` to list the three new test entries.
- [x] 2.5 Bump `tests/unit/test_queue.py` `VERSION` from `1.0.0` to `1.1.0` and add a `CHANGE_SUMMARY` entry recording the three new tests and the id-only invariant they pin.

## 3. Sync spec deltas to main specs

- [x] 3.1 Apply the testing-infrastructure delta: replace the `### Requirement: UniqueQueue unit tests` block (and its scenarios) in `openspec/specs/testing-infrastructure/spec.md` with the MODIFIED content from `openspec/changes/queue-dataclass-migration/specs/testing-infrastructure/spec.md`.
- [x] 3.2 Apply the testing-unit delta: replace the `### Requirement: UniqueQueue` block (and its scenario) in `openspec/specs/testing-unit/spec.md` with the MODIFIED content from `openspec/changes/queue-dataclass-migration/specs/testing-unit/spec.md`.

## 4. Verification

- [x] 4.1 Run `uv run pytest -m unit` — all queue tests pass (including the 3 new ones); orchestrator tests (`test_application_orchestrator.py`) unaffected.
- [x] 4.2 Run `uv run zuban check` — no type errors introduced.
- [x] 4.3 Run `uv run ruff check .` and `uv run ruff format --check .` — both clean.
- [x] 4.4 Run `uv run lint-imports` — confirms `from attrs import …` is no longer present in `queue.py`.
- [x] 4.5 Run `python3 scripts/grace_check.py` — GRACE-lite markup valid, file sizes within soft/hard limits.
- [x] 4.6 Run `openspec validate --all --json` — main specs and the change directory both pass validation.
