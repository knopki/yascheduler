# Platform Adapters

## Purpose

Provide platform-specific SSH adapters (Linux, Debian, etc.) relocated from
remote_machine/ to adapters/ssh/platform/ with backward-compatible re-exports.

## Requirements

### Requirement: Platform code relocated

The system SHALL move all platform-specific modules from remote_machine/
to adapters/ssh/platform/ preserving their functionality.

#### Scenario: Adapters accessible at new location
- **WHEN** the adapters module is imported from adapters.ssh.platform.adapters
- **THEN** the adapter registry is accessible

#### Scenario: Platform checks accessible
- **WHEN** check_is_linux is imported from adapters.ssh.platform.checks
- **THEN** the check function is accessible

#### Scenario: OS-specific methods accessible
- **WHEN** linux_setup_node is imported from adapters.ssh.platform.linux
- **THEN** the function is accessible

### Requirement: Old locations re-export

The system SHALL provide re-export modules at remote_machine/ locations
that import from adapters/ssh/platform/ for backward compatibility.

#### Scenario: Old import still works
- **WHEN** existing code imports RemoteMachineAdapter from yascheduler.remote_machine.adapters
- **THEN** the import succeeds, returning the class from adapters/ssh/platform/adapters

### Requirement: Platform detection used by gateway

The system SHALL use platform check functions to detect the remote OS during
SSHMachineGateway.connect() and select the appropriate adapter.

#### Scenario: Linux detection
- **WHEN** connect() runs platform checks on a Debian 12 host
- **THEN** the debian_12_adapter is selected for that machine
