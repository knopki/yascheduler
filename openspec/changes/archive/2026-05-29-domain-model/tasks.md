## 1. Scaffolding

- [x] 1.1 Create `yascheduler/domain/` directory with `__init__.py` (empty)
- [x] 1.2 Add GRACE-lite MODULE_CONTRACT to `__init__.py`

## 2. Domain Exceptions

- [x] 2.1 Create `domain/exceptions.py` with `DomainError(Exception)` base class
- [x] 2.2 Implement `ValidationError`, `UnsupportedEngineError`, `MissingInputFileError`
- [x] 2.3 Implement `TaskError`, `TaskAlreadyAllocatedError`, `TaskNotAllocatedError`
- [x] 2.4 Implement `MachineBusyError`
- [x] 2.5 Implement `SchedulingError`, `NoCompatibleNodeError`, `CloudCapacityExhaustedError`
- [x] 2.6 Add GRACE-lite markup to `domain/exceptions.py`
- [x] 2.7 Write unit tests for all exception classes (field access, messages, inheritance)

## 3. Domain Model

- [x] 3.1 Create `domain/model.py` with imports (dataclasses, enum, time, exceptions)
- [x] 3.2 Implement `TaskStatus(IntEnum)` — TO_DO=0, RUNNING=1, DONE=2
- [x] 3.3 Implement `MachineState(Enum)` — FREE, BUSY
- [x] 3.4 Implement `ProcessResult` frozen dataclass
- [x] 3.5 Implement `TaskContext` frozen dataclass with `extra` field
- [x] 3.6 Implement `Engine` frozen dataclass with `validate_inputs()` method
- [x] 3.7 Implement `Task` frozen dataclass with `allocate_to()`, `mark_running()`, `complete()`, `fail()` methods
- [x] 3.8 Implement `Node` frozen dataclass
- [x] 3.9 Implement `ConnectedMachine` frozen dataclass with `is_compatible()`, `occupy()`, `release()` methods
- [x] 3.10 Add GRACE-lite markup to `domain/model.py`
- [x] 3.11 Write unit tests for all entities: construction, defaults, state transitions, validation

## 4. Domain Ports

- [x] 4.1 Create `domain/ports.py` with `typing.Protocol` imports
- [x] 4.2 Implement `TaskRepository` Protocol (get, save, list_by_status)
- [x] 4.3 Implement `NodeRepository` Protocol (get, list_enabled, list_disabled, add, add_tmp, update, enable, disable, remove)
- [x] 4.4 Implement `MachineGateway` Protocol (list_free, run, upload, download)
- [x] 4.5 Implement `CloudProvisioner` Protocol (allocate, deallocate, capacity)
- [x] 4.6 Add GRACE-lite markup to `domain/ports.py`
- [x] 4.7 Write unit tests verifying Protocol structural conformance (a stub class that satisfies the Protocol passes `isinstance` check)

## 5. Domain Services

- [x] 5.1 Create `domain/services.py` with `match_task_to_node()` function
- [x] 5.2 Implement: filter free machines by engine platforms, return first match or None
- [x] 5.3 Add GRACE-lite markup to `domain/services.py`
- [x] 5.4 Write unit tests: match found, no match, all busy, empty list, multiple candidates

## 6. Verification

- [x] 6.1 Run `grace_check.py` — all new files pass GRACE-lite validation
- [x] 6.2 Run `openspec validate --all --json` — spec validation passes
- [x] 6.3 Run `uv run pytest tests/unit/ -k "domain"` — all new tests pass
- [x] 6.4 Run `uv run zuban check` — no type errors in new code
- [x] 6.5 Run `uv run ruff check yascheduler/domain/` — no lint errors
- [x] 6.6 Verify zero imports from `yascheduler` siblings in `domain/` (grep for `from yascheduler.` excluding `domain`)
- [x] 6.7 Verify existing tests still pass — no regressions from new code
