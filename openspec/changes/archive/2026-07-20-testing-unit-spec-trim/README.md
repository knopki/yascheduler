# testing-unit-spec-trim

Trim testing-unit spec to requirements-only; relocate design rationale, dedup invariant, and `SHALL NOT` negative-space language about removed APIs into GRACE markup on `yascheduler/application/queue.py`. Remove the stale "Shared test fixtures" requirement (its target files were deleted in `3fba272` / `9d1350c`).
