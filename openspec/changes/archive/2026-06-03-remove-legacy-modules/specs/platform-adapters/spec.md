## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Old locations re-export
**Reason**: The `remote_machine/` package is deleted. All platform code lives in `adapters/ssh/platform/`.
**Migration**: Import from `adapters/ssh/platform/` instead of `remote_machine/`.

### Requirement: Platform detection used by gateway
The system SHALL use platform check functions to detect the remote OS during
SSHMachineGateway.connect() and select the appropriate adapter.

#### Scenario: Linux detection
- **WHEN** connect() runs platform checks on a Debian 12 host
- **THEN** the debian_12_adapter is selected for that machine
