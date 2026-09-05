## Purpose

Define port interfaces for task storage, node storage, the
connected-machine collection, and cloud provisioning. Domain use cases
depend on these ports.

## Requirements

### Requirement: Repository and session ports

The system SHALL define port interfaces in the domain layer for:

- Task storage — CRUD keyed on task identity.
- Node storage — CRUD keyed on node identity. List-all SHALL return
  nodes ordered by identity ascending.
- Connected-machine collection and connected-machine handle — full
  contract lives in the `ssh-infrastructure` spec.
- Cloud provisioning — allocate, deallocate, select_provider, stop.

The ports SHALL depend only on domain types. Cross-cutting
configuration for clouds SHALL follow the `CloudConfig` structural
port; the authoritative field list and parsing rules live in the
`cloud` spec.

#### Scenario: use cases depend on ports, not on adapters

- **WHEN** a domain use case reads or writes tasks, nodes, machines, or clouds
- **THEN** it goes through the corresponding port interface

### Requirement: Repository insert attaches identity

A repository insert SHALL accept a pre-persistence record (no
identity) and return a post-persistence entity with the generated
identity and the DB-defaulted initial state. The conversion SHALL
happen in exactly one place per repository.

#### Scenario: insert attaches generated identity

- **WHEN** a pre-persistence record is inserted
- **THEN** the returned entity carries the generated identity and the DB-defaulted initial state; the input record is not mutated

### Requirement: Cloud provisioning contract

The cloud provisioning port SHALL:

- Allocate a tmp-node to a cloud provider. The returned node SHALL
  reuse the passed identity and SHALL set hostname and external_id to
  the cloud-provisioned address. All database state changes during
  provisioning SHALL be owned by the application layer.
- Deallocate a cloud node. The call SHALL be a no-op when the node's
  cloud is unset. Otherwise the adapter SHALL delete the VM identified
  by node.cloud and node.hostname.
- Select a provider. The call SHALL perform no I/O and SHALL return
  the provider name, or no value when no provider has capacity.

#### Scenario: allocate reuses passed identity and stamps the cloud address

- **WHEN** a tmp-node is allocated to a provider
- **THEN** the returned node reuses the passed node identity, sets hostname and external_id to the cloud-provisioned address, and is enabled

#### Scenario: deallocate is a no-op when cloud is unset

- **WHEN** deallocate is called on a node whose cloud is unset
- **THEN** no VM deletion is attempted; the call returns without error
