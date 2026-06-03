## ADDED Requirements

### Requirement: CI unit test workflow
The project SHALL include a GitHub Actions workflow that runs on push and pull request events, executing unit tests via `pytest`, plus static checks (`ruff check`, `ruff format --check`, `zuban check`).

#### Scenario: Push triggers CI
- **WHEN** a commit is pushed to any branch
- **THEN** the CI workflow runs unit tests and static checks

#### Scenario: Pull request triggers CI
- **WHEN** a pull request is opened or updated
- **THEN** the CI workflow runs unit tests and static checks

#### Scenario: CI uses correct Python version
- **WHEN** the CI workflow runs
- **THEN** it uses Python 3.9 (the minimum supported version) to ensure compatibility

### Requirement: CI does not run integration or e2e tests
The CI workflow SHALL NOT execute integration or e2e tests. Only unit tests (via `testpaths`) are run.

#### Scenario: Integration tests excluded from CI
- **WHEN** the CI workflow runs
- **THEN** only tests under `tests/unit/` execute; `tests/integration/` and `tests/e2e/` are not discovered
