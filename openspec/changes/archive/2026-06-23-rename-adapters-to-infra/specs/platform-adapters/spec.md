## MODIFIED Requirements

### Requirement: Platform code relocated

The system SHALL provide all platform-specific modules in
`infra/ssh/platform/` as the sole location. The `remote_machine/` package
SHALL NOT exist.

#### Scenario: Adapters accessible at new location
- **WHEN** the adapters module is imported from infra.ssh.platform.adapters
- **THEN** the adapter registry is accessible

#### Scenario: Platform checks accessible
- **WHEN** check_is_linux is imported from infra.ssh.platform.checks
- **THEN** the check function is accessible

#### Scenario: OS-specific methods accessible
- **WHEN** linux_setup_node is imported from infra.ssh.platform.linux
- **THEN** the function is accessible
