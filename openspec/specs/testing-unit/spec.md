## Purpose

Define the unit test tier: its boundary, its coverage contract, and
the logging-discipline guard. Unit tests verify behavior in isolation,
without external resources.

## Requirements

### Requirement: Unit test tier is hermetic

The unit test tier SHALL run without external resources. No real
database, no SSH server, no cloud credentials, and no filesystem
state SHALL be required. The unit tier SHALL cover the domain layer,
the application layer, and the CLI layer.

#### Scenario: unit tests run with no external resources

- **WHEN** the unit test tier runs
- **THEN** every test passes without a database, an SSH server, cloud credentials, or filesystem state

### Requirement: Coverage of specified behavior

The unit test tier SHALL cover every behavior specified in the
domain, application, and CLI specs with at least one happy-path test
and at least one failure-path test.

#### Scenario: happy path and failure path coverage

- **WHEN** a behavior is specified in a domain, application, or CLI spec
- **THEN** the unit test tier contains at least one happy-path test and at least one failure-path test for that behavior

### Requirement: Logging-discipline guard tests

The project SHALL provide guard tests that statically enforce the
logging contract. The guard tests SHALL verify two rules: no
collaborator class accepts a logger in its constructor, and no
structured-log call site uses a key that collides with a native log
record attribute. The exhaustive collaborator list and the exhaustive
log record attribute set live in code; the spec keeps only the
behavioral rule.

#### Scenario: guard tests enforce the logging contract

- **WHEN** the guard tests run as part of the unit tier
- **THEN** both rules hold: no collaborator accepts a logger in its constructor, and no structured-log call site uses a key that collides with a native log record attribute
