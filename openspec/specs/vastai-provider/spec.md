## Purpose

Define the VastAI cloud provider adapter: provisioning and deallocation of
VastAI marketplace VMs, SSH-key handling, offer selection, startup-script
generation, readiness polling, and the failure model. The adapter implements
the cloud provisioning contract from the `domain-ports` spec under the
`vastai` cloud name.

## Requirements

### Requirement: VastAI provisioning and deallocation

The system SHALL provide a VastAI cloud adapter that creates and deletes VM
instances on the VastAI marketplace under the `vastai` cloud name. Creation
provisions an SSH-accessible instance and returns its SSH host, SSH port, and
instance id. Deletion releases the VM and stops billing. All operations go
through one HTTP client; blocking calls are never offloaded to a thread pool.

#### Scenario: create provisions an instance; delete releases it

- **WHEN** the adapter creates a node and later deletes it
- **THEN** an SSH-accessible instance is provisioned; its SSH host, SSH port, and instance id are returned on creation; and the VM is deleted on deletion with billing stopped

#### Scenario: delete is idempotent on an already-deleted instance

- **WHEN** the adapter deletes an instance that no longer exists
- **THEN** the call returns without raising

### Requirement: VastAI SSH key handling

The adapter SHALL ensure the configured SSH public key is registered on the
VastAI account before an instance is created. Registration is account-level:
it applies to instances created after registration. The adapter SHALL NOT
register a key that is already present on the account. Key handling is part
of the provisioning call path; it is not a separate public entry point.

#### Scenario: SSH key ensured present before instance creation

- **WHEN** the adapter creates a node
- **THEN** the configured public key was present on the account before the instance was created — found or registered — with no duplicate registration

### Requirement: VastAI offer selection

The adapter SHALL search VastAI offers matching the configured constraints
(GPU count, VRAM, hourly price, disk, reliability, duration, and on-demand
type) and SHALL select the cheapest compatible offer. When no offer
satisfies the constraints, or when a returned offer fails validation, the
adapter SHALL raise without falling back to a more expensive or
non-compliant offer. A failed search does not retry against a different
offer within the same call; the next allocation cycle retries with a fresh
search.

#### Scenario: cheapest compatible offer selected; no match or invalid offer raises

- **WHEN** the adapter searches offers
- **THEN** the cheapest offer satisfying all configured constraints is used; no compatible offer or an invalid offer raises the corresponding VastAI error

### Requirement: VastAI launch mode

The adapter SHALL support both Docker and KVM/VM launch modes. The mode
SHALL be auto-detected from the configured image; no explicit flag is
required. Both modes SHALL produce an SSH-accessible instance.

#### Scenario: launch mode auto-detected from the configured image

- **WHEN** the adapter creates a node with a configured image
- **THEN** the launch mode (Docker or KVM/VM) is determined from the image without an explicit flag, and the resulting instance is SSH-accessible

### Requirement: VastAI startup-script generation

VastAI has no cloud-init support. The adapter SHALL translate the cloud-init
configuration it receives into the instance startup script. Translation maps
package upgrade, package install, and boot commands to the equivalent
startup-script steps; the package manager is detected from the configured
image. When the operator supplies a custom startup script, it SHALL be used
verbatim and cloud-init translation SHALL be skipped.

#### Scenario: cloud-init translated to a startup script, or custom script used verbatim

- **WHEN** the adapter builds the instance startup script
- **THEN** cloud-init (package upgrade, package install, boot commands) is translated using the package manager detected from the image, unless a custom startup script is supplied, in which case the custom script is used verbatim

### Requirement: VastAI readiness polling

The adapter SHALL poll the instance until it reaches the ready state before
returning the SSH address. Polling SHALL be bounded by the configured
connect grace period. On timeout, or on the instance entering a terminal
non-ready state, the adapter SHALL best-effort delete the known instance id
to prevent orphans and SHALL raise; it SHALL NOT retry against a different
offer within the same call.

#### Scenario: instance polled until ready; timeout or terminal status cleans up and raises

- **WHEN** the adapter waits for the instance to become ready
- **THEN** the SSH address is returned once the ready state is reached within the connect grace period; otherwise the known instance is best-effort deleted and the adapter raises

### Requirement: VastAI failure model

VastAI failures SHALL raise exceptions distinct by failure mode. Each
exception SHALL carry a free-form message and an optional HTTP status code
for failures that originate from an HTTP response.

#### Scenario: distinct exception per failure mode, each carrying a message and optional status

- **WHEN** a VastAI operation fails
- **THEN** the adapter raises the exception corresponding to the failure mode, carrying a free-form message and, when the failure originated from an HTTP response, the HTTP status code
