# Platform Adapters

## Purpose

Provide platform-specific SSH adapters (Linux, Debian, etc.) relocated from
remote_machine/ to adapters/ssh/platform/ with backward-compatible re-exports.

## Requirements

### Requirement: Platform code relocated

The system SHALL provide all platform-specific modules in
`adapters/ssh/platform/` as the sole location. The `remote_machine/` package
SHALL NOT exist.

#### Scenario: Adapters accessible at new location
- **WHEN** the adapters module is imported from adapters.ssh.platform.adapters
- **THEN** the adapter registry is accessible

#### Scenario: Platform checks accessible
- **WHEN** check_is_linux is imported from adapters.ssh.platform.checks
- **THEN** the check function is accessible

#### Scenario: OS-specific methods accessible
- **WHEN** linux_setup_node is imported from adapters.ssh.platform.linux
- **THEN** the function is accessible
