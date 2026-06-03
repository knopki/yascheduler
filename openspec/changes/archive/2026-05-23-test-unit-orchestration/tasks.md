## 1. Mock Fixtures

- [x] 1.1 Create `tests/fixtures/mock_remote_machine.py` with `make_mock_remote_machine(ip, platforms, busy, hostname)` returning `MagicMock(spec=RemoteMachine)` with configured `.meta`, `.platforms`, `.hostname`
- [x] 1.2 Create `tests/fixtures/mock_clouds.py` with `make_mock_clouds()` returning `AsyncMock` with stubbed `allocate`, `deallocate`, `get_capacity`, `mark_task_done`, `apis`, `stop`
- [x] 1.3 Create `tests/fixtures/mock_scheduler.py` with `make_scheduler(db, config, clouds, remote_machines)` helper constructing a `Scheduler` with injected mocks

## 2. RemoteMachineMetadata Tests

- [x] 2.1 Create `tests/unit/test_remote_machine.py` with tests for initial state (busy=None, free_since set)
- [x] 2.2 Add tests for busy state transitions (busy=True → free_since=None, busy=False → free_since=recent)
- [x] 2.3 Add tests for `is_free_longer_than` (free and long enough, busy returns False, not long enough returns False)

## 3. RemoteMachineRepository Tests

- [x] 3.1 Add tests for `filter(busy=True)` and `filter(busy=False)` with mixed busy/free machines
- [x] 3.2 Add tests for `filter(platforms=[...])` with matching and non-matching platforms
- [x] 3.3 Add tests for `filter(free_since_gt=timedelta(...))` with recently-freed and long-freed machines
- [x] 3.4 Add tests for `filter(reverse_sort=True)` verifying sort order
- [x] 3.5 Add test verifying filter returns a new instance without modifying the original

## 4. OS Check Tests

- [x] 4.1 Create `tests/unit/test_checks.py` with tests for `check_is_linux` (True for "Linux", False for "Darwin", False for non-zero returncode)
- [x] 4.2 Add tests for `check_is_debian_like` and `check_is_debian` with mocked `_get_os_release` output
- [x] 4.3 Add tests for `check_is_windows` (True for returncode=0, False for non-zero)

## 5. RemoteMachineAdapter Structure Tests

- [x] 5.1 Add tests verifying `linux_adapter`, `debian_adapter`, etc. have correct platform names and non-None callable fields
- [x] 5.2 Add test verifying adapter chain (debian_adapter.checks is superset of debian_like_adapter.checks)

## 6. Scheduler Unit Tests

- [x] 6.1 Create `tests/unit/test_scheduler.py` with a scheduler fixture using mocked DB, clouds, remote_machines, and real Config from inline INI
- [x] 6.2 Add tests for `Scheduler.__attrs_post_init__` (queue names and maxsizes match config)
- [x] 6.3 Add tests for `create_new_task` validation: unknown engine raises RuntimeError, missing input file raises RuntimeError
- [x] 6.4 Add tests for `create_new_task` success path: verifies db.add_task, db.update_task_meta (with remote_folder), db.commit calls, and returned TaskModel
- [x] 6.5 Add tests for `allocate_task` with free matching machine: verifies db.set_task_running and clouds.mark_task_done
- [x] 6.6 Add tests for `allocate_task` with no free machine: verifies clouds.allocate is called, returns False
- [x] 6.7 Add tests for `allocate_task` with unsupported engine: verifies db.set_task_error called
- [x] 6.8 Add tests for `clouds_get_capacity`: capacity available (positive result), over capacity (returns 0)
- [x] 6.9 Add tests for `WebhookPayload` dataclass construction and field access
