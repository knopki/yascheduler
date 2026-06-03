## Context

Phase 4 created `adapters/ssh/` and `adapters/cloud/` as new adapter packages,
rewrote use cases to use UoW + domain types, and refactored `RemoteMachine` and
`CloudAPIManager` into wrappers that delegate to the new adapters. However,
the old packages (`remote_machine/`, `clouds/`) were never removed because:

1. `SSHMachineGateway` imports shared helpers from `remote_machine/remote_machine.py`
2. Use cases still import `RemoteMachine`, `RemoteMachineRepository`, and retry
   exception types from `remote_machine/`
3. `CloudAPI` (265 LOC) contains real logic and imports `RemoteMachine` directly
4. `di.py` imports `_resolve_adapter` from `clouds/cloud_api_manager.py` and
   creates a `RemoteMachineRepository`

## Goals / Non-Goals

**Goals:**

- Make `adapters/ssh/` self-contained — own all SSH infrastructure (helpers,
  constants, client factory, platform detection)
- Replace all `remote_machine/` imports in `application/` with `MachineGateway`
  port or `adapters/ssh/` types
- Absorb `CloudAPI` logic into `adapters/cloud/`
- Delete `remote_machine/` and `clouds/` packages entirely
- Update `di.py` to wire `SSHMachineGateway` directly without `RemoteMachineRepository`

**Non-Goals:**

- Changing `MachineGateway` or `CloudProvisioner` Protocol signatures
- Adding new ports or domain entities
- CLI decoupling (Phase 5)
- Domain events (Phase 3.5)
- Config attrs → dataclasses migration (Phase 5.6)
- Connection pooling (Phase 5.5)

## Decisions

### D1: Shared helpers move to `adapters/ssh/helpers.py`

`ADAPTERS`, `DEFAULT_CONN_OPTS`, `MySSHClient`, `MAX_SESSIONS`,
`my_backoff_exc`, `_detect_platform`, `_init_paths`, `_resolve_tunnel` move from
`remote_machine/remote_machine.py` to a new `adapters/ssh/helpers.py`.

Rationale: `gateway.py` is already 569 LOC. Adding 80 LOC of helpers would push
it closer to the 1000-line hard limit. A dedicated module keeps responsibilities
clear: `helpers.py` owns infrastructure, `gateway.py` owns the MachineGateway
implementation.

Alternative considered: inline into `gateway.py` — rejected for size reasons.

### D2: Retry exception types move to `adapters/ssh/exceptions.py`

`SSHRetryExc`, `SFTPRetryExc`, `AllSSHRetryExc` are currently imported from
`remote_machine/protocol.py`. They move to `adapters/ssh/exceptions.py` so the
gateway package owns its own exception taxonomy.

The `remote_machine/protocol.py` broader set of protocol types (PEngine,
PEngineRepository, QuoteCallable, RunCallable, etc.) is NOT moved — these are
only used by the old `remote_machine/` platform adapters and have no consumers
in the new adapter tree.

### D3: Use cases receive `SSHMachineGateway` typed as `MachineGateway`

The use case signatures already reference `MachineGateway` port conceptually.
The `RemoteMachine` parameter in `consume_task` is replaced with the
`MachineGateway` port (via the concrete `SSHMachineGateway`). Similarly,
`RemoteMachineRepository` parameters become `SSHMachineGateway` for connect/
disconnect/filter operations.

For `allocate_task`: `RemoteMachineRepository` + `RemoteMachine` references
replaced by `SSHMachineGateway` (the gateway already maintains the machine
registry).

For `consume_task`: `RemoteMachine` parameter replaced by `MachineGateway` +
`ip: str` (or the `ConnectedMachine` from domain).

For `deallocate_nodes`: `RemoteMachineRepository` parameter replaced by
`SSHMachineGateway`.

For `orchestrator`: `RemoteMachineRepository` field replaced by
`SSHMachineGateway`. The gateway already tracks connected machines, can list
free, disconnect, etc.

### D4: `CloudAPI` logic absorbed into `CloudProvisionerImpl`

`CloudAPI`'s responsibilities are:
- Cloud-init rendering (`CloudConfig` class) → already exists in
  `adapters/cloud/cloud_config.py` as `CloudConfig` dataclass
- SSH key management (generate, load, name extraction) → new
  `adapters/cloud/ssh_keys.py`
- Node creation orchestration (create VM, wait for SSH, setup) → already in
  `CloudProvisionerImpl`
- Node deletion → already in `CloudProvisionerImpl`

After this absorption, `CloudAPI` has no remaining unique logic and is deleted.

### D5: `_resolve_adapter` moves to `adapters/cloud/adapters.py`

The `_resolve_adapter` helper currently lives in `clouds/cloud_api_manager.py`
but is a pure function over `CloudAdapter` and `ConfigCloud`. It moves to
`adapters/cloud/adapters.py` alongside the existing adapter factory functions.

### D6: `RemoteMachineMetadata` removed

`RemoteMachineMetadata` tracks `busy`/`free_since` at the wrapper level. In the
new architecture, machine state is tracked in the `ConnectedMachine` domain
entity (via `MachineState` enum) inside `SSHMachineGateway`'s internal
`_MachineState`. The metadata class becomes unnecessary.

Callers that accessed `machine.meta.busy` or `machine.meta.free_since` will use
`gateway.get_machine_state(ip).machine.state` or the gateway's `list_free()`
method.

## Risks / Trade-offs

**[Size of change]** → 15+ files modified, 2 packages deleted. Mitigate by
implementing in strict sequence: helpers → gateway self-contained → use cases
→ cloud → di → delete old packages. Each step is independently verifiable.

**[CloudAPI is 265 LOC with subtlety]** → SSH key generation, cloud-init
rendering, and backoff-retry node setup have provider-agnostic logic that must
be preserved exactly. Mitigate by keeping tests for `CloudProvisionerImpl` and
extending them to cover the absorbed CloudAPI scenarios.

**[E2e and integration tests may break]** → Tests importing from
`remote_machine/` or `clouds/` must be updated. The change includes test
migration as an explicit task.

**[RemoteMachineRepository.filter() semantics]** → `filter()` supports
`busy`, `platforms`, `free_since_gt`, `reverse_sort` predicates.
`SSHMachineGateway.list_free()` only returns FREE machines by platform. Callers
using `filter(busy=True)` or `reverse_sort` need equivalent gateway methods or
the queries must be restructured. The orchestrator's current usage only needs
`list_free(platforms)` and `disconnect` — no complex filter predicates.

## Open Questions

None — all blockers identified, all decisions made.
