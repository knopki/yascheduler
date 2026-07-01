## ADDED Requirements

### Requirement: Free-machine selection gated on DB-enabled nodes

The `allocate_task` use case SHALL only consider a machine allocatable
when its IP is enabled in `yascheduler_nodes`. The `_find_free_machines`
helper SHALL read `uow.nodes.list_enabled()` in the same Unit of Work it
opens for `uow.tasks.list_by_status({RUNNING})`, build
`enabled_ips = {n.ip for n in enabled_nodes}`, and filter
`MachineRepository.list_free(platforms)` down to sessions whose
`machine.ip` is in `enabled_ips` AND not in the busy-node IPs derived from
RUNNING tasks.

This restores the invariant that a machine is allocatable ONLY after its
DB row is `enabled=TRUE`. The DB row is flipped from `enabled=FALSE`
(the tmp-node inserted by `add_tmp` during provider selection) to
`enabled=TRUE` by `_persist_node_with_cleanup` after `clouds.allocate`
returns successfully — i.e. only after `_setup_vm` has completed
cloud-init, engine setup, and CPU detection.

The gate SHALL live in the use case, not in `MachineRepository`. The
`MachineRepository` Protocol (an infrastructure-layer SSH collection port)
SHALL NOT be coupled to `NodeRepository` (a persistence port). Joining the
two data sources is the use case's responsibility.

A side effect of this gate: a node that was disabled in DB but not yet
disconnected (the window between `deallocate_nodes.disable` and
`repository.disconnect`) also has a `FREE` session in the repository. The
previous filter (RUNNING tasks only) would let it through; the new gate
excludes it because its IP is no longer in `enabled_ips`. This closes a
second, latent registry-vs-DB desync window.

#### Scenario: Setup-in-flight tmp-node is invisible to the allocator

- **WHEN** `CloudProvisionerImpl._setup_vm` has called `machine_repository.connect(ip)` registering a `FREE` session, but `clouds.allocate` has not yet returned and `_persist_node_with_cleanup` has not yet set the DB row to `enabled=TRUE`
- **THEN** `_find_free_machines` excludes that session because `ip not in enabled_ips`, so no task is dispatched to the not-yet-setup node

#### Scenario: Multiple allocator workers do not pile onto the same setup-in-flight node

- **WHEN** two allocator workers run `_find_free_machines` concurrently while one setup-in-flight session is registered (DB row `enabled=FALSE`)
- **THEN** both workers exclude that session from `free_sessions`, neither attempts `_try_start_on_machine` on it, and no `MachineBusyError` pile-on occurs

#### Scenario: Enabled node is allocatable after setup completes

- **WHEN** `clouds.allocate` returned successfully and `_persist_node_with_cleanup` flipped the DB row to `enabled=TRUE`
- **THEN** on the next allocator tick `_find_free_machines` includes the session in `free_sessions` because its IP is now in `enabled_ips`

#### Scenario: Disabled-but-not-disconnected node is excluded

- **WHEN** a node's DB row was set to `enabled=FALSE` by `deallocate_nodes` but its SSH session has not yet been removed from `MachineRepository._sessions` (still `FREE`)
- **THEN** `_find_free_machines` excludes that session because its IP is no longer in `enabled_ips`, so no task is dispatched to a node being deallocated

#### Scenario: Gate lives in the use case, not the repository

- **WHEN** `MachineRepository.list_free` is inspected for any reference to `NodeRepository`, `list_enabled`, or persistence imports
- **THEN** none are present; the repository returns FREE sessions filtered only by platform, and the enabled-IP intersection is applied by `_find_free_machines` in the application layer

### Requirement: Free-machine loop isolates per-session failures

The `_allocate_free_machine` helper SHALL wrap each `_try_start_on_machine`
invocation in a `try/except Exception` so that a single stale or
transiently-unreachable session's exception is logged and the loop
continues to the next free session. If no free session succeeds, the
helper SHALL return `False` so the caller (`allocate_task`) proceeds to
the cloud-provisioning branch.

The `except` block SHALL log at `error` level with the task id, the
session ip, and the exception, and SHALL `continue` to the next session.
The `except` block SHALL NOT call `repository.disconnect` — a transient
SSH failure does not imply the session is dead, and the session's monitor
task manages its lifecycle. Stale sessions left by failed setup are
prevented at the source by the setup-failure disconnect in the
`cloud-provisioner` capability.

This is defense-in-depth: it ensures the cloud-provisioning branch is
reachable even if a free-machine iteration raises, so a task never spins
in TO_DO because one bad session aborted the whole loop.

#### Scenario: Stale session failure does not abort the loop

- **WHEN** `free_sessions` contains two sessions and the first raises `asyncssh.misc.ChannelOpenError` during `_try_start_on_machine` (e.g. a stale session pointing at a deleted VM)
- **THEN** the exception is caught, logged at `error` with task_id and ip, the loop continues to the second session, and the allocator does not propagate the exception out of `_allocate_free_machine`

#### Scenario: Cloud branch reached when all free sessions fail

- **WHEN** every session in `free_sessions` raises during `_try_start_on_machine` and none returns `True`
- **THEN** `_allocate_free_machine` returns `False`, `allocate_task` proceeds to the cloud-provisioning branch (the `if not engine.platforms` short-circuit then the `CLOUD_CRITICAL_SECTION`), and a new node may be provisioned for the task

#### Scenario: Per-session except does not disconnect

- **WHEN** `_try_start_on_machine` raises a transient SSH error for a legitimately-connected node
- **THEN** the `except` block logs and continues WITHOUT calling `repository.disconnect(session.ip)`; the session remains registered and its monitor task continues to manage its state