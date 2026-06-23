## MODIFIED Requirements

### Requirement: Public API stability

The system SHALL preserve the existing public API surface of the
`yascheduler` package across changes. Public API is defined as: exported
symbols, constructor and method signatures (parameter positions and names,
return shapes), and documented behavior. Backward-compatible extensions
(adding keyword-only optional parameters, refining internal
implementation, adding new public symbols) are permitted; breaking
changes (removing or repositioning parameters, changing return shapes,
removing exported symbols) SHALL be treated as a new capability requiring
explicit spec coverage.

- `yascheduler/__init__.py` exports (`Yascheduler`, `CONFIG_FILE`,
  `LOG_FILE`, `PID_FILE`, `__version__`) SHALL remain resolvable.
- `yascheduler.aiida_plugin` (AiiDA scheduler entrypoint) SHALL remain
  loadable with identical behavior.
- `yascheduler.client` SHALL preserve its public constructor and method
  signatures: zero-arg and positional callsites remain valid; keyword-only
  optional parameters may be added (e.g., for test injection); internal
  implementation may change without notice.
- `yascheduler.compat` SHALL remain internal (not public surface).

#### Scenario: Yascheduler symbol resolves with backward-compatible signature
- **WHEN** a downstream consumer imports `from yascheduler import Yascheduler`
- **THEN** the symbol resolves and the zero-arg constructor `Yascheduler()` and the positional constructors `Yascheduler(config_path)` / `Yascheduler(config_path, logger)` remain valid

#### Scenario: Backward-compatible constructor extension permitted
- **WHEN** a change adds a keyword-only optional parameter to `Yascheduler.__init__` (e.g., `deps_factory` for test injection)
- **THEN** existing callsites `Yascheduler()`, `Yascheduler(config_path)`, `Yascheduler(config_path, logger)` remain valid without modification

#### Scenario: AiiDA plugin still loads
- **WHEN** the AiiDA scheduler plugin entrypoint is loaded
- **THEN** it loads and behaves identically to before the change

#### Scenario: compat.py remains internal
- **WHEN** `yascheduler/compat.py` is inspected
- **THEN** it is not added to any facade's public re-exports

## ADDED Requirements

### Requirement: Yascheduler client query method public contract

The `Yascheduler` class in `yascheduler/client.py` SHALL preserve its
public query API across the UoW migration:

- `Yascheduler()` zero-arg construction SHALL remain valid.
- `Yascheduler(config_path, logger)` positional callsites SHALL remain valid.
- `Yascheduler(config_path, logger, *, deps_factory=None)` SHALL add
  `deps_factory` as a keyword-only optional parameter (lazy default
  `make_cli_deps`), used as a test-injection seam.
- `queue_get_tasks(jobs, status)`, `queue_get_tasks_async(jobs, status)`,
  `queue_get_task(task_id)`, and `queue_get_task_async(task_id)` signatures
  SHALL NOT change.
- Each query method SHALL return Mappings (a `Sequence[Mapping]` for the
  list variants `queue_get_tasks` / `queue_get_tasks_async`, an
  `Optional[Mapping]` for the single-task variants `queue_get_task` /
  `queue_get_task_async`) with EXACTLY the keys
  `{task_id, label, ip, status, metadata, cloud}`.
- `status` SHALL be a `domain.TaskStatus` enum member (preserves `.name`
  access and cross-class IntEnum equality; NOT a plain `int`).
- `cloud` SHALL be `None` in the query method output (no facade path
  populates it).
- `ip` SHALL be `allocated_ip or ""` (empty string when the task has no
  allocated node).

#### Scenario: Zero-arg construction remains valid
- **WHEN** `Yascheduler()` is called with no arguments
- **THEN** the client is constructed successfully and `queue_get_tasks_async` is invokable

#### Scenario: deps_factory is keyword-only
- **WHEN** `Yascheduler(config_path, logger, my_factory)` is called with `deps_factory` positionally
- **THEN** a `TypeError` is raised

#### Scenario: Query returns six-key dict shape
- **WHEN** `queue_get_tasks_async(jobs=[1])` returns a non-empty result
- **THEN** each Mapping has exactly the keys `{task_id, label, ip, status, metadata, cloud}` and no others

#### Scenario: Status field is a domain.TaskStatus member
- **WHEN** a returned Mapping's `status` value is inspected
- **THEN** it is an instance of `yascheduler.domain.TaskStatus` (not a plain `int`), with `.name` and `.value` matching the underlying IntEnum values 0/1/2

#### Scenario: cloud is always None
- **WHEN** any query method returns a Mapping
- **THEN** the `cloud` key is present and its value is `None`

#### Scenario: ip is empty string when task unallocated
- **WHEN** a Task with `allocated_ip=None` is returned by a query method
- **THEN** the Mapping's `ip` value is `""` (empty string)
