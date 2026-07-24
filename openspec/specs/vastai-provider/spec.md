# vastai-provider Specification

## Purpose
TBD - created by archiving change vastai-provider. Update Purpose after archive.
## Requirements
### Requirement: VastAI provider module contract

The system SHALL provide a VastAI provider module implementing the
`CreateNodeCallable` and `DeleteNodeCallable` protocols with
`vastai_create_node` and `vastai_delete_node`, plus a VastAI-specific exception
hierarchy. The module SHALL also expose `vastai_list_instances` for e2e test
cleanup (listing instances by label). Dependencies SHALL be `aiohttp` (HTTP
client) and `backoff` (fibonacci retry on rate-limit 429 responses).

`vastai_create_node(cfg: ConfigCloudVastAI, key: SSHKey,
cloud_config: CloudInitConfig | None = None) -> CloudCreateNodeDTO` SHALL
implement the use case: ensure the SSH key is registered on the account →
search offers matching the configured criteria → select a random offer from the
top-5 cheapest compatible offers (avoids repeated allocation to the same broken
provider) → create an instance from that offer → wait until the instance is
ready → return a `CloudCreateNodeDTO` carrying the instance id as
`external_id`, the instance SSH host as `hostname`, and the instance SSH port
as `port`. `vastai_delete_node(cfg: ConfigCloudVastAI, external_id: str) -> None`
SHALL delete the instance identified by `external_id` and be idempotent.

The module SHALL expose a single async HTTP client surface used by all
provider operations; blocking calls SHALL NOT be offloaded to a thread pool
(the provider is fully async).

#### Scenario: create_node use case

- **WHEN** `vastai_create_node(cfg, key)` is called
- **THEN** it ensures the public key is registered on the VastAI account, searches offers matching `cfg`, selects the cheapest compatible offer, creates an instance, waits until the instance is ready, and returns a `CloudCreateNodeDTO`

#### Scenario: delete_node use case

- **WHEN** `vastai_delete_node(cfg, external_id)` is called
- **THEN** the instance identified by `external_id` is deleted and billing stops

#### Scenario: delete_node is idempotent

- **WHEN** `vastai_delete_node(cfg, external_id)` is called for an instance that no longer exists
- **THEN** the call returns without raising

### Requirement: VastAI SSH key registration

`vastai_create_node` SHALL ensure the provided public key is registered on the
VastAI account before creating an instance. Registration SHALL be account-level
(applies to all FUTURE instances created after registration, not to already
running instances). The provider SHALL avoid re-registering a key that is
already present on the account (presence check before registration). The check
and registration are part of the `vastai_create_node` call path and SHALL NOT
be a separate public function the caller must invoke.

#### Scenario: key registered before instance creation

- **WHEN** `vastai_create_node(cfg, key)` runs to completion
- **THEN** the public key was present on the account before the instance was created, either by finding it already registered or by registering it

#### Scenario: no duplicate registration

- **WHEN** the provided public key is already registered on the account
- **THEN** `vastai_create_node` does not register a duplicate copy

### Requirement: VastAI offer search and selection

`vastai_create_node` SHALL search offers matching the configured criteria
(`min_vram_mb`, `num_gpus`, `max_price_per_hr`, `disk_gb`, `reliability`,
`duration`, and the on-demand type) and SHALL select a random offer from the
top-5 cheapest compatible offers. This random selection avoids repeated
allocation to the same broken provider. When no offer satisfies the configured
constraints, `vastai_create_node` SHALL raise a dedicated "no offers found"
exception; it SHALL NOT silently pick a more expensive offer or an offer
violating a constraint. When a returned offer fails validation (e.g. price
violating a constraint after the response), `vastai_create_node` SHALL raise a
dedicated "invalid offer" exception. Retry against a different offer within a
single `create_node` call is a non-goal: a failed search surfaces as the "no
offers found" exception and the next scheduler allocation cycle retries with a
fresh search.

#### Scenario: random offer from top-5 cheapest selected

- **WHEN** multiple offers satisfy all configured constraints
- **THEN** a random offer from the top-5 cheapest (by per-hour price) is used to create the instance

#### Scenario: no compatible offer raises

- **WHEN** no offer satisfies all configured constraints
- **THEN** `vastai_create_node` raises the VastAI "no offers found" exception

#### Scenario: invalid offer raises

- **WHEN** a returned offer's price exceeds the configured `max_price_per_hr`
- **THEN** `vastai_create_node` raises the VastAI "invalid offer" exception

### Requirement: VastAI KVM and Docker launch modes

`vastai_create_node` SHALL support both Docker and KVM/VM launch modes and
SHALL auto-detect the mode from the configured `image`. Both modes SHALL
result in an SSH-accessible instance whose SSH host and port are returned in
the `CloudCreateNodeDTO`.

#### Scenario: mode auto-detected from image

- **WHEN** `vastai_create_node` is called with an image
- **THEN** the launch mode (Docker or KVM/VM) is determined from the image name without an explicit config flag

### Requirement: VastAI cloud-init to onstart translation

Because VastAI has no cloud-init support, `vastai_create_node` SHALL translate
the `CloudInitConfig` it receives into the instance's startup script, unless
the operator has supplied a custom startup script in config
(`onstart_script`).

The translation SHALL map: `package_upgrade` to a package-manager upgrade;
`packages` to a package-manager install of the listed packages; `bootcmd` to
the listed commands appended to the startup script. The package manager SHALL
be detected from the configured image.

When `onstart_script` is configured (non-empty), it SHALL be used verbatim as
the startup script and the `CloudInitConfig` translation SHALL be skipped.

#### Scenario: onstart generated from cloud-init when no custom script

- **WHEN** `cfg.onstart_script` is empty and `cloud_config` carries `package_upgrade=True`, `packages=["foo"]`, and `bootcmd=(["echo hi"],)`
- **THEN** the generated startup script performs a package-manager upgrade, installs `foo`, and runs `echo hi`

#### Scenario: custom onstart overrides cloud-init translation

- **WHEN** `cfg.onstart_script` is non-empty
- **THEN** it is used verbatim as the startup script and `cloud_config` is not translated

#### Scenario: package manager detected from image

- **WHEN** the startup script is generated from `cloud_config`
- **THEN** the package manager is selected based on the configured image's distribution family

### Requirement: VastAI readiness polling

`vastai_create_node` SHALL poll the instance until it reaches the ready state
before returning the `CloudCreateNodeDTO`. Polling SHALL be bounded by the
adapter's `connect_grace` (sourced from `ConfigCloudVastAI`), after which
a dedicated timeout exception is raised. If the instance enters a terminal
non-ready state (`stopped`, `frozen`, `exited`, `unknown`, or `offline` — a
state from which the ready state will never be reached), `vastai_create_node`
SHALL raise a dedicated terminal-status exception; it SHALL NOT retry against
a different offer within the same call (non-goal — the next allocation cycle
retries). On timeout or terminal status, the provider SHALL best-effort DELETE
the known instance id to prevent orphans before raising.

#### Scenario: ready instance returns DTO

- **WHEN** the instance reaches the ready state within the timeout
- **THEN** `vastai_create_node` returns the `CloudCreateNodeDTO`

#### Scenario: timeout raises with orphan cleanup

- **WHEN** the instance does not reach the ready state within `connect_grace`
- **THEN** `vastai_create_node` best-effort DELETEs the instance and raises the VastAI timeout exception

#### Scenario: terminal status raises with orphan cleanup

- **WHEN** the instance enters a terminal non-ready state (stopped, frozen, exited, unknown, or offline)
- **THEN** `vastai_create_node` best-effort DELETEs the instance and raises the VastAI terminal-status exception (no in-call retry)

### Requirement: VastAI exception hierarchy

The system SHALL define a VastAI exception hierarchy with a common VastAI
exception root and distinct types for: a general API/transport error (covering
authentication failure, HTTP transport failure, unexpected response shape, and
SSH key registration failure), a delete error, a no-offers error, an invalid
offer error, and an instance create error (covering instance creation failure,
polling timeout, and terminal instance status). Each exception SHALL carry a
free-form message. The root `VastAIError` SHALL also carry an optional
`status: int | None` field for HTTP status code context. The hierarchy SHALL be
importable from the provider module.

#### Scenario: distinct exception types per failure mode

- **WHEN** the VastAI exception types are inspected
- **THEN** the general API error, delete error, no-offers error, invalid offer error, and instance create error are each a distinct class subclassing a common VastAI root

#### Scenario: general API error covers auth, transport, and ssh-key failures

- **WHEN** an authentication, HTTP transport, unexpected-response, or SSH-key-registration failure occurs
- **THEN** the VastAI general API error is raised

#### Scenario: instance create error covers create, timeout, and terminal status

- **WHEN** instance creation fails, polling times out, or the instance enters a terminal non-ready state
- **THEN** the VastAI instance create error is raised

#### Scenario: exceptions carry a free-form message and optional status

- **WHEN** a VastAI exception is constructed with a message and optionally a status code
- **THEN** `str(e)` equals that message, and `e.status` carries the HTTP status code when provided

### Requirement: VastAI structured log tracing

The VastAI provider SHALL emit structured block-boundary log records at every
significant branch: SSH key presence check, key registration, offer search,
offer selection, instance creation, each readiness poll, readiness reached, and
deletion. Structured fields SHALL be flat (no nesting), redact secrets (API
key), and include identifiers (instance id, offer id, status). Records SHALL
be assertable by tests via the project's log-assertion helpers.

#### Scenario: create_node emits block markers

- **WHEN** `vastai_create_node` runs to completion
- **THEN** block-boundary log records are emitted for key handling, offer search, offer selection, instance creation, polling, and readiness

#### Scenario: delete_node emits block marker

- **WHEN** `vastai_delete_node` runs
- **THEN** a block-boundary log record is emitted for the deletion

#### Scenario: secrets redacted in log fields

- **WHEN** any VastAI log record is inspected
- **THEN** the API key does not appear in any structured field

