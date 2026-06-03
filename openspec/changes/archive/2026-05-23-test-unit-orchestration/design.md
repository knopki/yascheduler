## Context

Two main module groups to test:

**`remote_machine/`** — SSH machine management:
- `RemoteMachineMetadata`: mutable busy/free_since state, `is_free_longer_than(delta)` logic
- `RemoteMachineRepository`: dict-like container with `filter(busy, platforms, free_since_gt, reverse_sort)` returning evolved copies
- `RemoteMachineAdapter`: frozen attrs with platform checks — pure data, trivially testable for structure
- `checks.py`: OS detection functions that call `conn.run()` and parse stdout — testable with mocked `SSHClientConnection`
- `RemoteMachine`: 516-line class with SSH connection, platform detection, SFTP — constructor is deep (requires real SSH). Not worth testing directly at unit level; defer to SSH testcontainer integration.

**`scheduler.py`** — 808-line orchestrator:
- `Scheduler`: depends on `Config`, `DB`, `CloudAPIManager`, `RemoteMachineRepository`
- Key testable methods: `create_new_task`, `allocate_task`, `clouds_get_capacity`, `consume_task`, `dealloocator_producer`
- Constructor (`__attrs_post_init__`) sets up 4 `UniqueQueue` instances from config limits
- `start()`/`stop()` are lifecycle methods — test `stop()` for cleanup, skip `start()` (infinite loop)

The `test-unit-core` change provides `FakeDB`. This change adds mock fixtures for the remaining dependencies.

## Goals / Non-Goals

**Goals:**
- Test `RemoteMachineMetadata` state transitions and time-based logic
- Test `RemoteMachineRepository.filter` with all parameter combinations
- Test `checks.py` OS detection with mocked SSH connections
- Test `Scheduler.create_new_task` input validation and metadata assembly
- Test `Scheduler.allocate_task` free-machine selection and cloud fallback
- Test `Scheduler.clouds_get_capacity` capacity arithmetic
- Provide mock fixtures for `RemoteMachine` and `CloudAPIManager`

**Non-Goals:**
- Testing `RemoteMachine.create()` (requires real SSH — future SSH testcontainer)
- Testing `Scheduler.start()` infinite loop
- Testing `consume_task` SFTP download logic (requires SSH mock setup that's complex; defer)
- Testing `upload_task_data` (SFTP-heavy, defer)

## Decisions

### D1: RemoteMachineMetadata tests use short timedeltas

`is_free_longer_than` compares `datetime.now() - delta > free_since`. Tests use `timedelta(seconds=0)` or patch `free_since` directly rather than sleeping. For "not free longer than" cases, set `busy=True` or set `free_since` to recent time.

### D2: RemoteMachineRepository filter tests create lightweight RemoteMachine mocks

Full `RemoteMachine` requires `SSHClientConnection`. Instead, use `unittest.mock.MagicMock(spec=RemoteMachine)` with `.meta`, `.platforms` attributes set. The `filter` method only reads these attributes.

### D3: OS check tests mock SSHClientConnection at conn.run level

Each check function calls `conn.run(cmd)` and checks `proc.returncode` and `proc.stdout`. Mock `conn.run` to return an object with these attributes:

```python
mock_conn = AsyncMock()
mock_conn.run = AsyncMock(return_value=MagicMock(returncode=0, stdout="Linux\n"))
```

Note: `checks.py` uses `@lru_cache` on some functions. Tests must clear the cache between calls or use fresh mock objects (different identity → different cache key).

### D4: Scheduler tests inject dependencies via constructor

`Scheduler.__attrs_post_init__` sets up queues from config. Construct `Scheduler` directly with mocked `db`, `clouds`, `remote_machines`, real `Config` (from inline INI), and a logger. Bypass `Scheduler.create()` factory entirely.

### D5: Mock CloudAPIManager with allocate/deallocate/mark_task_done stubs

`AsyncMock()` for `clouds.allocate`, `clouds.deallocate`, `clouds.get_capacity`, `clouds.mark_task_done`. For `get_capacity`, return `CloudCapacity`-compatible objects.

### D6: create_new_task tests verify DB calls and metadata

After calling `create_new_task`, assert on `db.add_task.call_args`, `db.update_task_meta.call_args`, `db.commit.call_count`. Verify metadata contains `engine` key and `remote_folder` key with expected pattern.

## Risks / Trade-offs

- **Scheduler is tightly coupled** — constructor takes many dependencies. Breaking changes to `Scheduler` attrs fields will break test fixtures. Acceptable: tests catch these changes.
- **lru_cache on check functions** — if mock objects have the same identity across tests, cached results leak. Mitigate by using `@pytest.fixture(autouse=True)` to clear caches or ensuring unique mock instances.
- **consume_task and upload_task_data deferred** — these are complex SFTP-heavy methods. Missing coverage on the download/upload paths. Will be covered by SSH testcontainer integration later.
