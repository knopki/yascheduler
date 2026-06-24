## MODIFIED Requirements

### Requirement: Provider selection by priority and capacity

The system SHALL select the best available cloud provider based on
configurable priority and current capacity. Provider selection SHALL be
exposed via the sync port method `select_provider(platforms,
current_counts) -> str | None` on `CloudProvisioner`. The implementation
SHALL call the adapter-internal pure function `select_provider_pure(adapters,
configs, platforms, current_counts, log)` and return the selected
adapter's `name` as a bare `str` (or `None`). The application layer SHALL
NOT call `select_provider_pure` directly or reference
`CloudAdapter`/`ConfigCloud` types.

If the selected provider's op semaphore is locked (concurrent op limit
reached), the port method SHALL return `None` (not raise). This matches
current caller-visible semantics where `allocate_with_tracking` returned
`None` on throttle.

The returned `str` is the selected provider's identity, passed back
unchanged by the caller to `allocate(provider)` and `deallocate(cloud, ip)`.
No `ProviderSelection` value object is constructed or returned.

#### Scenario: Higher priority wins
- **WHEN** provider A has priority=100 and provider B has priority=50, both with capacity
- **THEN** `select_provider(platforms, counts)` returns the string `provider_a.name`

#### Scenario: Full provider skipped
- **WHEN** a provider has reached max_nodes (current_counts[name] >= configs[name].max_nodes)
- **THEN** it is excluded from selection

#### Scenario: No platform support
- **WHEN** no provider supports any of the requested platforms
- **THEN** `select_provider` returns `None`

#### Scenario: Provider op-limit returns None
- **WHEN** the highest-priority provider with capacity has its op semaphore locked
- **THEN** `select_provider` returns `None` (does not raise); the caller's `selection is None` branch handles cleanup