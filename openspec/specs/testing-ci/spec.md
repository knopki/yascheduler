## Purpose

Defines the CI workflow for running unit tests and static checks on every push and pull request.

## Requirements

### Requirement: CI unit test workflow
The project SHALL include a GitHub Actions workflow that runs on push and pull request events, executing unit tests via `pytest`.

#### Scenario: Push triggers CI
- **WHEN** a commit is pushed to any branch
- **THEN** the CI workflow runs unit tests

#### Scenario: Pull request triggers CI
- **WHEN** a pull request is opened or updated
- **THEN** the CI workflow runs unit tests

### Requirement: CI does not run integration or e2e tests
The CI workflow SHALL NOT execute integration or e2e tests. Only unit tests (via `testpaths`) are run.

#### Scenario: Integration tests excluded from CI
- **WHEN** the CI workflow runs
- **THEN** only tests under `tests/unit/` execute; `tests/integration/` and `tests/e2e/` are not discovered
