# Implementation Tasks: cloud-error-hierarchy

## 1. Knowledge graph (top-down: update shared truth first)

- [x] 1.1 In `docs/knowledge-graph.xml`, add to `M-DOMAIN-EXCEPTIONS`
  annotations: `<class-CloudError PURPOSE="Cloud provider operational errors (base for CloudAllocateError/CloudSetupError)" />`
- [x] 1.2 Append `(subclass of CloudError)` to the existing
  `class-CloudAllocateError` and `class-CloudSetupError` PURPOSE text in
  `M-DOMAIN-EXCEPTIONS`; KEEP the existing `(re-exported for backwards compat)`
  note (still accurate — D3/task 3.3 preserve those re-exports). No new
  `M-`/`CrossLink`/`depends` changes (internal-only addition).

## 2. Domain exceptions module

- [x] 2.1 In `yascheduler/domain/exceptions.py`, insert a new
  `class CloudError(DomainError):` immediately before `CloudAllocateError`,
  with a docstring stating it covers **operational** cloud-provider failures
  and that capacity planning lives in `CloudCapacityExhaustedError` under
  `SchedulingError`.
- [x] 2.2 Reparent `class CloudAllocateError(Exception):` →
  `class CloudAllocateError(CloudError):` (body unchanged, no `__init__`).
- [x] 2.3 Reparent `class CloudSetupError(Exception):` →
  `class CloudSetupError(CloudError):` (body unchanged, no `__init__`).
- [x] 2.4 Add `CloudError - Cloud provider operational errors` to the
  `START_MODULE_MAP` block; bump `VERSION` and add a `START_CHANGE_SUMMARY`
  entry (LAST_CHANGE: cloud-error-hierarchy — add CloudError root, reparent
  CloudAllocateError/CloudSetupError).
- [x] 2.5 Confirm no raise site or `except CloudSetupError` site in
  `yascheduler/adapters/cloud/manager.py` is touched (10 raise sites: 3
  `CloudAllocateError`, 7 `CloudSetupError`; 2 `except CloudSetupError`).

## 3. Domain package export

- [x] 3.1 In `yascheduler/domain/__init__.py`, add `CloudError` to the import
  from `.exceptions` and to `__all__`.
- [x] 3.2 Add a `CloudError` line to the `START_MODULE_MAP` block; add a
  `START_CHANGE_SUMMARY` entry.
- [x] 3.3 Confirm `yascheduler/adapters/cloud/__init__.py` is unchanged
  (`CloudError` NOT re-exported; `CloudAllocateError`/`CloudSetupError`
  re-exports preserved).

## 4. Tests (domain-exceptions unit)

- [x] 4.1 Add `issubclass(CloudError, DomainError)` is true.
- [x] 4.2 Add `issubclass(CloudAllocateError, CloudError)` and
  `issubclass(CloudSetupError, CloudError)` are true; both catchable via
  `except CloudError`, `except DomainError`, `except Exception`.
- [x] 4.3 Add negative guard: `issubclass(CloudError, SchedulingError)` is
  false (locks D2).
- [x] 4.4 Add `issubclass(CloudCapacityExhaustedError, SchedulingError)` is
  true AND `issubclass(CloudCapacityExhaustedError, CloudError)` is false.
  Confirm existing tests still cover `NoCompatibleNodeError.task_id/platforms`
  and `CloudCapacityExhaustedError.task_id` (the unchanged scenarios in the
  MODIFIED `SchedulingError hierarchy` requirement); add if missing.
- [x] 4.5 Add free-form message test: `str(CloudAllocateError("Unknown provider: foo")) == "Unknown provider: foo"`.
  Also assert no custom `__init__` on either leaf class (e.g.
  `"__init__" not in CloudAllocateError.__dict__` and same for
  `CloudSetupError`) to guard against a future structured-field regression.
- [x] 4.6 Add import tests: `from yascheduler.domain.exceptions import CloudError`,
  `from yascheduler.domain import CloudError` (and `CloudError in yascheduler.domain.__all__`).
- [x] 4.7 Add adapter export-surface tests:
  `from yascheduler.adapters.cloud import CloudError` raises `ImportError`;
  `from yascheduler.adapters.cloud import CloudAllocateError, CloudSetupError`
  succeeds.

## 5. Verification

- [x] 5.1 `uv run pytest -m unit` passes (new tests + existing
  domain-exceptions tests green).
- [x] 5.2 `uv run zuban check`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run lint-imports` all pass.
- [x] 5.3 `python3 scripts/grace_check.py` exits 0 (graph + source markup
  consistent).
- [x] 5.4 `openspec validate cloud-error-hierarchy` passes.
