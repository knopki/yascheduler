## ADDED Requirements

### Requirement: RemoteMachineMetadata state transitions
Tests SHALL verify that setting `busy=True` sets `free_since=None`, setting `busy=False` sets `free_since` to current time, and initial state has `busy=None` and `free_since` set.

#### Scenario: Initial state
- **WHEN** `RemoteMachineMetadata()` is created
- **THEN** `busy` is `None` and `free_since` is set to a recent datetime

#### Scenario: Set busy then free
- **WHEN** `meta.busy = True` then `meta.busy = False`
- **THEN** after busy=True, `free_since` is None; after busy=False, `free_since` is a recent datetime

### Requirement: RemoteMachineMetadata.is_free_longer_than
Tests SHALL verify that `is_free_longer_than(delta)` returns True only when machine is not busy and has been free longer than the given delta.

#### Scenario: Free longer than delta
- **WHEN** `meta.busy = False` (sets free_since to now) and delta is `timedelta(seconds=0)`
- **THEN** `is_free_longer_than(timedelta(seconds=0))` returns True

#### Scenario: Not free because busy
- **WHEN** `meta.busy = True`
- **THEN** `is_free_longer_than(timedelta(seconds=0))` returns False

#### Scenario: Not free because not long enough
- **WHEN** `meta.busy = False` and delta is very large (e.g., `timedelta(days=365)`)
- **THEN** `is_free_longer_than(timedelta(days=365))` returns False

### Requirement: RemoteMachineRepository.filter by busy
Tests SHALL verify that `filter(busy=True)` returns only busy machines and `filter(busy=False)` returns only free machines.

#### Scenario: Filter busy=True
- **WHEN** repository has one busy and one free machine
- **THEN** `filter(busy=True)` returns only the busy machine

#### Scenario: Filter busy=False
- **WHEN** repository has one busy and one free machine
- **THEN** `filter(busy=False)` returns only the free machine

### Requirement: RemoteMachineRepository.filter by platforms
Tests SHALL verify that `filter(platforms=["debian"])` returns machines whose platform list intersects.

#### Scenario: Platform match
- **WHEN** a machine has platforms=["linux", "debian"] and filter is `platforms=["debian"]`
- **THEN** the machine is included

#### Scenario: No platform match
- **WHEN** a machine has platforms=["linux"] and filter is `platforms=["windows"]`
- **THEN** the machine is excluded

### Requirement: RemoteMachineRepository.filter by free_since_gt
Tests SHALL verify that `filter(free_since_gt=timedelta(...))` returns machines free longer than the given duration.

#### Scenario: Free long enough
- **WHEN** a machine has been free for 5 minutes and filter is `free_since_gt=timedelta(minutes=3)`
- **THEN** the machine is included

### Requirement: RemoteMachineRepository.filter reverse_sort
Tests SHALL verify that `filter(reverse_sort=True)` sorts machines by `free_since` descending (most recently freed first).

#### Scenario: Reverse sort order
- **WHEN** two machines exist with different free_since times and `reverse_sort=True`
- **THEN** the machine freed more recently appears first

### Requirement: RemoteMachineRepository.filter returns evolved copy
Tests SHALL verify that filter returns a new `RemoteMachineRepository` instance without modifying the original.

#### Scenario: Original unchanged
- **WHEN** `filter(busy=False)` is called on a repository with 2 machines (1 busy, 1 free)
- **THEN** the original still has 2 machines

### Requirement: OS check functions with mocked SSH
Tests SHALL verify `check_is_linux`, `check_is_debian`, `check_is_debian_like`, `check_is_windows` return correct booleans based on mocked SSH command output.

#### Scenario: check_is_linux with "Linux" output
- **WHEN** `conn.run("uname")` returns `stdout="Linux\n"`, `returncode=0`
- **THEN** `check_is_linux(conn)` returns True

#### Scenario: check_is_linux with "Darwin" output
- **WHEN** `conn.run("uname")` returns `stdout="Darwin\n"`, `returncode=0`
- **THEN** `check_is_linux(conn)` returns False

#### Scenario: check_is_debian_like with correct os-release
- **WHEN** `_get_os_release(conn)` returns `("debian", "debian-like", "11")`
- **THEN** `check_is_debian_like(conn)` returns True

#### Scenario: check_is_debian with correct os-release
- **WHEN** `_get_os_release(conn)` returns `("ubuntu", "debian", "22.04")`
- **THEN** `check_is_debian(conn)` returns False (ID is "ubuntu", not "debian")

### Requirement: RemoteMachineAdapter structure
Tests SHALL verify that adapter instances (`linux_adapter`, `debian_adapter`, etc.) have correct platform names and non-None callables for all required fields.

#### Scenario: linux_adapter has correct platform
- **WHEN** `linux_adapter.platform` is checked
- **THEN** it equals `"linux"` and all callable fields are not None

#### Scenario: Adapter chain inheritance
- **WHEN** `debian_adapter` is compared to `debian_like_adapter`
- **THEN** `debian_adapter.checks` is a superset of `debian_like_adapter.checks`
