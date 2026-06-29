## MODIFIED Requirements

### Requirement: CloudProvisionerImpl.stop closes machine_gateway connections

`CloudProvisionerImpl.stop` SHALL close every SSH connection held by its
`machine_repository` by awaiting `machine_repository.disconnect_all()`. This
replaces the prior no-op "compatibility hook" semantics. (The
`machine_gateway` attribute is renamed `machine_repository` after the
`decompose-ssh-gateway` split; `CloudProvisionerImpl` holds the collection
port, not the dissolved god-class.)

Rationale: `_setup_vm` opens SSH connections via
`machine_repository.connect(ip)` during cloud allocation, and
`CloudProvisionerImpl.allocate` does not disconnect them on success. Without
`stop()` draining the repository, those connections leak for the process
lifetime. When `make_daemon` shares a single repository between
`CloudProvisionerImpl` and `Orchestrator` (per the `dependency-injection`
capability), `clouds.stop()` becomes the primary shutdown drain; the
orchestrator's subsequent `repository.disconnect_all()` call is an idempotent
no-op on the same instance.

`disconnect_all` on `SSHMachineRepository` is idempotent (it iterates a
snapshot of `_sessions` and pops each entry), so calling it from both
`clouds.stop()` and `Orchestrator.stop()` is safe regardless of whether the
repository is shared.

#### Scenario: stop drains all connections

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose `machine_repository` holds one or more connected sessions
- **THEN** `machine_repository.disconnect_all()` SHALL be awaited exactly once, and every connection that was present at call time SHALL be closed

#### Scenario: stop with empty repository is a safe no-op

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose `machine_repository` holds zero connected sessions
- **THEN** `machine_repository.disconnect_all()` SHALL still be awaited (it returns without effect), and `stop()` SHALL NOT raise

#### Scenario: stop is idempotent under repeated calls

- **WHEN** `await clouds.stop()` is called twice in succession on the same `CloudProvisionerImpl`
- **THEN** both calls SHALL complete without raising, and the second call SHALL be a no-op (the repository's `_sessions` dict is already empty)

#### Scenario: stop with shared repository does not interfere with orchestrator shutdown

- **WHEN** `clouds` and `Orchestrator` share the same `SSHMachineRepository` instance (per the `dependency-injection` capability), and `Orchestrator.stop()` awaits `clouds.stop()` followed by `repository.disconnect_all()`
- **THEN** both calls SHALL complete without raising; the second `disconnect_all()` SHALL be an idempotent no-op on the now-empty `_sessions` dict