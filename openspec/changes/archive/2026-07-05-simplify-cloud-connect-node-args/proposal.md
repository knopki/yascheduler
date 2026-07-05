# Proposal: simplify-cloud-connect-node-args

## Why

`MachineRepository.connect` takes `username` and `port` as separate parameters
even though both are already carried by its `node: Node` argument, and the cloud
allocation chain (`manager.py`) threads `ip_addr`/`tmp_node_id` scalars down two
private methods and builds a throwaway "ersatz" `Node` just to satisfy `connect`.
The code already carries six `# FIXME` markers flagging exactly this redundancy
(plus a seventh in `manager.py` above `_connect_to_vm` flagging the ersatz
`Node`); this change removes it so the `Node` is the single source of truth for its own
transport attributes.

## What Changes

- **BREAKING** (internal port): Drop `username: str` and `port: int = 22` from
  `MachineRepository.connect` (domain port) and `SSHMachineRepository.connect` /
  `_connect_impl` (impl). `connect` reads `node.username` and `node.port`
  internally instead. `client_keys`, `connect_timeout`, `data_dir`,
  `engines_dir`, `tasks_dir`, `jump_host`, `jump_username` are unchanged (they
  are per-connection config, not node identity).
- Update all four `connect` call sites to stop passing the now-removed
  `username`/`port` args: `orchestrator._connect_machine_consumer`,
  `check_status._display_remote_output`, `manage_node._add_node`, and
  `manager._connect_to_vm`.
- Cloud `manager.py`: change `_setup_vm(ip_addr, tmp_node_id, adapter, config)`
  and `_connect_to_vm(ip_addr, tmp_node_id, adapter, config)` to
  `_setup_vm(node, adapter, config)` / `_connect_to_vm(node, adapter, config)`.
  `allocate` constructs the `Node` exactly once (right after `adapter.create_node`
  yields the ip) and threads it down; `_connect_to_vm` passes it straight to
  `connect` (no ersatz `Node`); `_setup_vm` returns `replace(node, enabled=True,
  ncpus=ncpus)` instead of constructing a fresh `Node`. Three `Node`
  constructions collapse to one.
- Remove the six `# FIXME` markers that this change resolves (two in `ports.py`,
  four in `repository.py` `connect` + `_connect_impl`) plus the seventh
  `# FIXME: just use Node if you are already construct Node inside` above
  `_connect_to_vm` in `manager.py`.
- Update the two test doubles implementing the port
  (`StubMachineRepository.connect` in `test_domain_ports.py`,
  `FakeMachineRepository.connect` in `test_cloud_alloc_session_lifecycle.py`) and
  any tests asserting `username=`/`port=` kwargs on connect.
- Public contracts unchanged: `CloudProvisioner.allocate(provider, tmp_node_id)`
  signature, the tmp-node single-row UPDATE lifecycle, DB schema, CLI surface,
  and `connect`'s effective behavior (same host/user/port used on the wire).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `ssh-infrastructure`: `MachineRepository.connect` / `SSHMachineRepository.connect`
  method signature drops `username` and `port`; reads them from `node`. (The
  `domain-ports` capability is NOT listed here: its `MachineRepository` port
  requirement delegates the full method-signature spec to `ssh-infrastructure`
  and never names `username`/`port`, so its requirement text is unchanged.)
- `cloud`: `_setup_vm` / `_connect_to_vm` take `node: Node` (not `ip_addr` +
  `tmp_node_id`); ersatz-`Node` construction removed; `_setup_vm` returns
  `replace(node, enabled=True, ncpus)`.
- `cli`: `manage_node` add-flow and `yastatus` view-mode connect calls no longer
  pass `username`/`port` args (values still equal `node.username`/`node.port`,
  now read from the node inside `connect`).

## Impact

- **Code**: `yascheduler/domain/ports.py`, `yascheduler/infra/ssh/repository.py`,
  `yascheduler/infra/cloud/manager.py`, `yascheduler/application/orchestrator.py`,
  `yascheduler/entrypoints/cli/check_status.py`,
  `yascheduler/entrypoints/cli/manage_node.py`.
- **Tests**: `tests/unit/test_domain_ports.py`,
  `tests/unit/test_cloud_alloc_session_lifecycle.py`,
  `tests/unit/test_cloud_provisioner_impl.py`, `tests/unit/test_ssh_gateway*.py`,
  `tests/unit/test_allocate_task_failure_modes.py` (any that pass or assert
  `username`/`port` on connect).
- **APIs**: `MachineRepository.connect` is an internal domain port, not part of
  the documented public surface (CLI commands, `class Yascheduler`, INI, DB
  schema, AiiDA entrypoint). No public-interface break.
- **Dependencies**: none added.
- **GRACE**: `docs/knowledge-graph.xml` plus module contracts / `CHANGE_SUMMARY`
  for the six touched source files.
