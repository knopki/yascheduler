## MODIFIED Requirements

### Requirement: Yascheduler client query method public contract

The `Yascheduler` class SHALL preserve its public query API across the
introduction of the `TaskId` domain value object. The class is defined in
`yascheduler/entrypoints/client.py` and re-exported via
`from yascheduler import Yascheduler` (package facade) and
`from yascheduler.client import Yascheduler` (compat shim); the public
contract is keyed on the resolvable symbol, not the file path.

- `Yascheduler()` zero-arg construction SHALL remain valid.
- `Yascheduler(config_path, logger)` positional callsites SHALL remain valid.
- `Yascheduler(config_path, logger, *, deps_factory=None)` SHALL add
  `deps_factory` as a keyword-only optional parameter (lazy default
  `make_cli_deps`), used as a test-injection seam.
- `queue_get_tasks(jobs, status)`, `queue_get_tasks_async(jobs, status)`,
  `queue_get_task(task_id)`, and `queue_get_task_async(task_id)` signatures
  SHALL NOT change; their public `task_id`/`jobs` parameters stay `int` /
  `list[int]`.
- Each query method SHALL return Mappings (a `Sequence[Mapping]` for the
  list variants `queue_get_tasks` / `queue_get_tasks_async`, an
  `Optional[Mapping]` for the single-task variants `queue_get_task` /
  `queue_get_task_async`) with EXACTLY the keys
  `{task_id, label, ip, status, metadata, cloud}`.
- The `task_id` value in each returned Mapping SHALL be a bare `int` (NOT a
  `TaskId`). The private `_task_to_dict(t: Task)` helper (`client.py:89`)
  is the sole extraction site: it builds the dict with
  `"task_id": t.task_id.value` so the public dict preserves the `int` shape.
  The `Yascheduler` facade is the **sole** `int`/`TaskId` marshalling boundary,
  in both directions: on input (`queue_get_task(task_id: int)` /
  `queue_get_tasks(jobs: list[int])`) it wraps `TaskId(task_id)` /
  `[TaskId(i) for i in jobs]` before calling the use cases / repository; on
  output it extracts `.value` via `_task_to_dict`.
- `queue_submit_task(...) -> int` SHALL stay `int`; it wraps `submit_task`
  (which now returns `TaskId`) and returns `(await submit_task(...)).value`.
- `status` SHALL be a `domain.TaskStatus` enum member (preserves `.name`
  access and cross-class IntEnum equality; NOT a plain `int`).
- `cloud` SHALL be `None` in the query method output (no facade path
  populates it).
- `ip` SHALL be `allocated_ip or ""` (empty string when the task has no
  allocated node).

The public contract is keyed on the resolvable symbol and applies
identically whether `Yascheduler` is imported via the package facade
(`from yascheduler import Yascheduler`), the entrypoints layer facade
(`from yascheduler.entrypoints import Yascheduler`), or the compat shim
(`from yascheduler.client import Yascheduler`).

#### Scenario: Zero-arg construction remains valid
- **WHEN** `Yascheduler()` is called with no arguments
- **THEN** the client is constructed successfully and `queue_get_tasks_async` is invokable

#### Scenario: deps_factory is keyword-only
- **WHEN** `Yascheduler(config_path, logger, my_factory)` is called with `deps_factory` positionally
- **THEN** a `TypeError` is raised

#### Scenario: Query returns six-key dict shape
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a non-empty result
- **THEN** each Mapping has exactly the keys `{task_id, label, ip, status, metadata, cloud}` and no others

#### Scenario: task_id in returned dict is a bare int
- **WHEN** a returned Mapping's `task_id` value is inspected
- **THEN** it is a bare `int` (NOT a `TaskId` instance); the facade extracted `.value` via `_task_to_dict` so the public `int`-typed contract is preserved

#### Scenario: Facade wraps int to TaskId on input
- **WHEN** `queue_get_task(42)` or `queue_get_tasks_async(jobs=[1, 2, 3])` is called
- **THEN** the facade internally wraps `TaskId(42)` / `[TaskId(1), TaskId(2), TaskId(3)]` before calling the use case / repository (the public `int` signature is unchanged)

#### Scenario: queue_submit_task returns int
- **WHEN** `queue_submit_task(...)` completes successfully
- **THEN** it returns a bare `int` (the `.value` of the `TaskId` returned by `submit_task`); the public `-> int` contract is preserved

#### Scenario: Status field is a domain.TaskStatus member
- **WHEN** a returned Mapping's `status` value is inspected
- **THEN** it is an instance of `yascheduler.domain.TaskStatus` (not a plain `int`), with `.name` and `.value` matching the underlying IntEnum values 0/1/2

#### Scenario: cloud is always None
- **WHEN** any query method returns a Mapping
- **THEN** the `cloud` key is present and its value is `None`

#### Scenario: ip is empty string when task unallocated
- **WHEN** a Task with `allocated_ip=None` is returned by a query method
- **THEN** the Mapping's `ip` value is `""` (empty string)

#### Scenario: Contract holds via each import path
- **WHEN** `Yascheduler` is imported via `from yascheduler import Yascheduler`, `from yascheduler.entrypoints import Yascheduler`, or `from yascheduler.client import Yascheduler`
- **THEN** all query-method scenarios above hold identically (the import path does not affect the public contract)