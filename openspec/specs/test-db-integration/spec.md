## Purpose

Define the database integration test tier: its boundary and the
persistence round-trip contract. The tier verifies the repository
adapters against a real PostgreSQL instance, not a mock.

## Requirements

### Requirement: Database integration tier is real and isolated

The database integration tier SHALL run against a real PostgreSQL
instance with the full schema applied. No persistence collaborator
SHALL be mocked. Each test SHALL start from a clean state, so a test
does not observe rows left by any other test.

#### Scenario: real database and no shared state

- **WHEN** the database integration tier runs
- **THEN** every test passes against a real PostgreSQL instance with the schema applied, and a test that runs after another test observes none of that other test's rows

### Requirement: Repository round-trip

A repository insert SHALL return the materialized entity with the
generated identity and the database-defaulted initial state. Reads
SHALL return the matching entities. Updates SHALL persist. The full
column set SHALL round-trip through an insert and a read without loss:
the typed columns and the JSONB metadata column SHALL keep their
values and shape.

#### Scenario: node round-trip

- **WHEN** two nodes are inserted with different enabled states, one node's enabled flag is then changed, and both are read back by identity and by enabled filter
- **THEN** each read by identity returns the node with its current fields, and the enabled and disabled filters each return the subset that matches the changed state

#### Scenario: task column set round-trips

- **WHEN** a task is inserted with every typed column set and a non-empty JSONB metadata payload and then read back
- **THEN** the read task carries the same typed-column values and the same JSONB metadata, with no key lost or re-shaped

### Requirement: Task lifecycle round-trips through the database

A task SHALL round-trip through every status transition. Each
transition SHALL persist, and a later read SHALL reflect the new
status and the typed fields that the transition changes. The error
field SHALL carry the failure reason on a failed or rejected task and
SHALL be empty on a successful task.

#### Scenario: full lifecycle and error field persist

- **WHEN** a task is inserted, driven through every status transition, and read back at each step
- **THEN** each read reflects the persisted status and the changed typed fields, and the error field is set on failure and empty on success
