## MODIFIED Requirements

### Requirement: CloudProvisioner port

The system SHALL define a `CloudProvisioner` Protocol with methods:
`allocate(provider: str) -> Node` (async),
`deallocate(cloud: str, ip: str) -> None` (async),
`select_provider(platforms: list[str], current_counts: dict[str, int]) -> ProviderSelection | None` (sync).

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is explicit: the caller calls
`select_provider` first, gets a `ProviderSelection` (or `None`), then
calls `allocate(selection.name)`.

`deallocate` takes `cloud` explicitly because the adapter no longer reads
the database to resolve the provider from `ip`. The caller (use case) has
the `Node` and passes `node.cloud`.

`select_provider` is sync — it does no I/O. It returns `None` when no
provider has capacity OR when the selected provider's op semaphore is
locked (throttle). The caller's `selection is None` branch handles
cleanup.

`capacity()` is removed — capacity counting is a use case / orchestrator
responsibility, not a cloud adapter concern.

The system SHALL define a `ProviderSelection` value object in
`yascheduler.domain.model` with fields `name: str` and `username: str`.
It is primitive-only — no adapter types (`CloudAdapter`, `ConfigCloud`)
cross the port boundary.

#### Scenario: Allocate cloud node
- **WHEN** `allocate("aws")` is called with a valid provider name
- **THEN** returns a Node with the provisioned IP (no DB write inside the adapter)

#### Scenario: Deallocate cloud node with explicit cloud
- **WHEN** `deallocate(cloud="aws", ip="10.0.0.1")` is called
- **THEN** the VM at the given IP is deleted via the named provider's SDK

#### Scenario: Select provider returns ProviderSelection
- **WHEN** `select_provider(["linux"], {"aws": 0})` is called and aws has capacity and supports linux
- **THEN** returns a `ProviderSelection(name="aws", username="root")` (or configured username)

#### Scenario: Select provider returns None on no capacity
- **WHEN** `select_provider(["linux"], {"aws": 10})` is called and aws max_nodes is 10
- **THEN** returns `None`

#### Scenario: Select provider returns None on throttle
- **WHEN** the selected provider's op semaphore is locked
- **THEN** `select_provider` returns `None` (does not raise)
