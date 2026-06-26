## ADDED Requirements

### Requirement: CloudProvisionerImpl.stop closes machine_gateway connections

`CloudProvisionerImpl.stop` SHALL close every SSH connection held by its
`machine_gateway` by awaiting `machine_gateway.disconnect_all()`. This
replaces the prior no-op "compatibility hook" semantics.

Rationale: `_setup_vm` opens SSH connections via `machine_gateway.connect(ip)`
during cloud allocation, and `CloudProvisionerImpl.allocate` does not
disconnect them on success. Without `stop()` draining the gateway, those
connections leak for the process lifetime. When `make_daemon` shares a single
gateway between `CloudProvisionerImpl` and `Orchestrator` (per the
`dependency-injection` capability), `clouds.stop()` becomes the primary
shutdown drain; the orchestrator's subsequent `gateway.disconnect_all()` call
is an idempotent no-op on the same instance.

`disconnect_all` on `SSHMachineGateway` is idempotent (it iterates a snapshot
of `_machines` and pops each entry), so calling it from both `clouds.stop()`
and `Orchestrator.stop()` is safe regardless of whether the gateway is shared.

#### Scenario: stop drains all connections

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose
  `machine_gateway` holds one or more connected machines
- **THEN** `machine_gateway.disconnect_all()` SHALL be awaited exactly once,
  and every connection that was present at call time SHALL be closed

#### Scenario: stop with empty gateway is a safe no-op

- **WHEN** `await clouds.stop()` is called on a `CloudProvisionerImpl` whose
  `machine_gateway` holds zero connected machines
- **THEN** `machine_gateway.disconnect_all()` SHALL still be awaited (it
  returns without effect), and `stop()` SHALL NOT raise

#### Scenario: stop is idempotent under repeated calls

- **WHEN** `await clouds.stop()` is called twice in succession on the same
  `CloudProvisionerImpl`
- **THEN** both calls SHALL complete without raising, and the second call
  SHALL be a no-op (the gateway's `_machines` registry is already empty)

#### Scenario: stop with shared gateway does not interfere with orchestrator shutdown

- **WHEN** `clouds` and `Orchestrator` share the same `SSHMachineGateway`
  instance (per the `dependency-injection` capability), and
  `Orchestrator.stop()` awaits `clouds.stop()` followed by
  `gateway.disconnect_all()`
- **THEN** both calls SHALL complete without raising; the second
  `disconnect_all()` SHALL be an idempotent no-op on the now-empty registry
