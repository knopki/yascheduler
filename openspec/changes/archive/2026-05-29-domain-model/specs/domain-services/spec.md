## ADDED Requirements

### Requirement: match_task_to_node domain service

The system SHALL provide a `match_task_to_node` pure function that selects
the best free machine for a task from a list of candidates.

#### Scenario: Match found
- **WHEN** `match_task_to_node(task, engine, free_machines)` is called with
  at least one machine compatible with `engine.platforms`
- **THEN** returns the first compatible `ConnectedMachine`

#### Scenario: No compatible machine
- **WHEN** `match_task_to_node(task, engine, free_machines)` is called with
  zero machines matching `engine.platforms`
- **THEN** returns `None`

#### Scenario: Only busy machines available
- **WHEN** all machines have `state=BUSY`
- **THEN** returns `None` (busy machines are not candidates)

#### Scenario: Multiple compatible machines
- **WHEN** two FREE machines both match the engine's platforms
- **THEN** returns one of them (preference order defined by caller's list order)

### Requirement: Service is importable from domain

The system SHALL expose `match_task_to_node` from `yascheduler.domain.services`.

#### Scenario: Import service
- **WHEN** `from yascheduler.domain.services import match_task_to_node` is executed
- **THEN** the function is available

### Requirement: Service is pure and synchronous

The system SHALL implement `match_task_to_node` as a synchronous, pure
function with no I/O and no side effects.

#### Scenario: Service has no side effects
- **WHEN** `match_task_to_node` is called
- **THEN** no external state is modified; the return value depends only on inputs
