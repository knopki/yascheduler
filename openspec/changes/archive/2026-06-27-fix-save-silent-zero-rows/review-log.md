# Review Log — fix-save-silent-zero-rows

## proposal Round 1 — 2026-06-27T09:49:54Z

### Summary

No blocking issues. The proposal captures all key commitments from the explore-brief correctly, with no contradictions or scope leaks. Minor gaps are limited to implementation reasoning details that belong in the delta spec, not the proposal. The batch passes and can be frozen.

### 🔴 Fixed (serious issues I found and you must fix)

None.

### 🟡 Addressed (minor issues I recommend fixing)

1. **Race semantics not in proposal (informational, not a fix)**
   The explore-brief spends ~15 lines on the race resolution semantics (exception raised before `_saved_tasks.append`, rollback clears empty list, TaskAbandoned event dropped correctly, self-heals via `list_by_status` next cycle). The proposal captures only the critical point ("before appending to `_saved_tasks`", line 22). The rest is correct implementation reasoning that belongs in the delta spec. No action needed — just flagging that whoever writes the delta spec must carry this reasoning forward.

2. **"Existing mock-based tests unaffected" not mentioned**
   The brief says existing `conftest.py` mock-based tests are unaffected because `AsyncMock()` doesn't raise. The proposal says "Not a breaking change for correct callers" (line 73) which implies existing tests pass, but doesn't call out the mock gap explicitly. Minor; the delta spec should state this.

3. **"Symmetric to allocator" — pattern differs slightly**
   The proposal says the worker wrap is "symmetric to the existing allocator-consumer wrap" (line 32). The allocator wraps `try/except Exception` inside the consumer function itself (`_allocator_consumer`, line 382-394). The proposal wraps in the inner `worker()` inside `_create_producer_consumers` (lines 580-586). These are semantically equivalent (both catch consumer exceptions so the worker survives), but structurally different. The proposal should be precise: the worker wraps at the worker-caller level, not inside the consumer function. The delta spec will need to resolve this. Suggest updating proposal line 31 to say "symmetric _in effect_ to the allocator-consumer wrap" or describe the exact location to avoid ambiguity.

### 🔴 Outstanding (serious issues still open after this round)

None. Batch passes.

## tasks Round 1 — 2026-06-27T09:55:31Z

### Summary

No blocking issues. All spec requirements and design decisions have corresponding tasks. Task format, grouping, and dependency order are correct. The batch passes and the change is apply-ready.

### 🔴 Fixed (serious — must fix)

None.

### 🟡 Addressed (minor — recommended)

1. **Task 7.1 vs 8.5 file path ambiguity**
   Task 7.1 allows consumer resilience tests in either `test_application_orchestrator.py` or a new `test_orchestrator_consumer_resilience.py`. Task 8.5 only references the new-file path. If the implementer chooses the existing file, 8.5's pytest invocation misses those tests. Non-blocking — the implementer adjusts the command naturally. Pick one location to resolve.

### 🔴 Outstanding (serious still open)

None. Batch passes.
