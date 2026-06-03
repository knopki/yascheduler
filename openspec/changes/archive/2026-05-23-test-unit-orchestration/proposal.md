## Why

`remote_machine/` and `scheduler.py` are the most complex and coupled modules in the codebase. `Scheduler` (808 lines) orchestrates the full task lifecycle through producer-consumer loops, depends on DB, Cloud, SSH, and queues. `RemoteMachineRepository` filters machines by busy/platform/free_since criteria. `RemoteMachineMetadata` tracks busy state and free-since timestamps. None of this has tests — any change to allocation logic, platform matching, or deallocation is effectively unverified.

## What Changes

- Add unit tests for `RemoteMachineMetadata` (busy state transitions, `is_free_longer_than`, free_since tracking)
- Add unit tests for `RemoteMachineRepository.filter` (busy, platforms, free_since_gt, reverse_sort combinations)
- Add unit tests for `Scheduler` methods with mocked dependencies: `create_new_task` (input validation, engine lookup, metadata assembly), `allocate_task` (free machine selection, cloud fallback, unsupported engine error), `clouds_get_capacity` (capacity calculation)
- Add unit tests for `WebhookPayload` dataclass
- Add unit tests for OS check functions in `checks.py` with mocked SSH connections
- Create mock helpers for `RemoteMachine`, `RemoteMachineAdapter`, and `CloudAPIManager` in `tests/fixtures/`

## Capabilities

### New Capabilities
- `test-remote-machine-unit`: Unit tests for RemoteMachineMetadata, RemoteMachineRepository, OS checks, and RemoteMachineAdapter structure
- `test-scheduler-unit`: Unit tests for Scheduler methods with mocked DB/SSH/Cloud

### Modified Capabilities
_(none)_

## Impact

- New test files in `tests/unit/`: `test_remote_machine.py`, `test_scheduler.py`, `test_checks.py`
- New mock helpers in `tests/fixtures/`: `mock_remote_machine.py`, `mock_clouds.py`
- No changes to production code
