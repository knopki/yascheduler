## Why

SSH connection identity (`jump_host`, `jump_port`, `jump_username`) is re-resolved at every connect call from cloud/remote config, while `Node` already carries these fields as persisted placeholders that nothing reads. This produces three duplicated resolution sites (orchestrator, `yastatus -v`, cloud provisioner), a behavioral asymmetry where static nodes added via `yasetnode` never receive the configured jump host even when `[remote]` defines one, and `Node.jump_*` dead weight spec'd as "placeholder fields not consumed by code yet." The connection identity should be frozen once at node creation and read solely from `Node` thereafter — the same principle already applied to `hostname`/`username`/`port`.

A secondary symptom: the tunnel leg today is built as a `user@host` string, which silently drops `jump_port` and ignores auth/timeout options on the bastion leg — a latent failure behind non-standard bastion ports or matched-key bastions. Stamping full identity on `Node` forces the tunnel to be built from the same shape as the destination.

## What Changes

- `Node.jump_host` / `jump_port` / `jump_username` become authoritative, not placeholders: populated once at creation, read at every connect.
- Static nodes (`yasetnode`): jump fields are resolved from `[remote]` defaults at insert time (covers the tmp-node connect-setup path that currently fails behind a bastion).
- Cloud nodes: jump fields are resolved from the matching `CloudConfig` (prefix == `node.cloud`) with `[remote]` fallback, applied after the adapter returns the hostname and before the node is persisted as enabled.
- **BREAKING** (Protocol): `MachineRepository.connect` loses its `jump_host` and `jump_username` keyword arguments. The transport reads `node.jump_host` / `node.jump_username` / `node.jump_port` directly.
- `_resolve_tunnel` builds the tunnel leg from the same connection-options shape as the destination, so `client_keys` / `known_hosts` / `connect_timeout` apply to both legs. `jump_port` is honored (it was previously dropped — the string form had no port slot).
- Remove the three duplicated resolution sites: `_resolve_conn_params` in `check_status.py` (whole helper), the inline cloud-prefix loop in `orchestrator._connect_machine_consumer`, and the `config.jump_host or None` pass-through in `CloudProvisionerImpl._setup_vm`.
- **Non-goal**: retroactively populate `jump_*` on existing rows — the functionality was effectively unused (most rows have `jump_host = NULL`), so operators either re-add affected static nodes or manually update them; no migration is shipped.
- No DB migration: columns already exist (migration `012`); existing rows keep `jump_host = NULL`, which means "no tunnel."

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `ssh-infrastructure`: `MachineRepository.connect` signature drops `jump_host` / `jump_username`; `_resolve_tunnel` consumes `Node.jump_*` and emits `SSHClientConnectionOptions` honoring `jump_port`.
- `domain-entities`: `Node.jump_host` / `jump_port` / `jump_username` re-spec'd as authoritative connection-identity fields (no longer "placeholder fields not consumed by code yet"); creation-time population contract.
- `cli`: `yastatus -v` resolves connection parameters solely from `Node`; `_resolve_conn_params` and its cloud-prefix fallback logic are removed. `yasetnode` populates `Node.jump_*` from `[remote]` at insert.
- `orchestrator`: `_connect_machine_consumer` no longer resolves jump inline; connect call uses `Node` identity directly.
- `cloud`: `CloudProvisionerImpl._connect_to_vm` no longer passes `jump_host` / `jump_username` to `connect`; the provisioner stamps `Node.jump_*` from the matching `CloudConfig` (or `[remote]` fallback) BEFORE the setup SSH session is opened (so cloud-init/setup also routes through the bastion), then carries the stamped values forward through the final `enabled=True` / `ncpus` replace.

## Impact

- **Code**:
  - `yascheduler/infra/ssh/repository.py` — `connect` / `_open_connection` signatures, `_resolve_tunnel` rewrite.
  - `yascheduler/application/orchestrator.py` — `_connect_machine_consumer` simplification (lines ~275-291 today).
  - `yascheduler/entrypoints/cli/check_status.py` — remove `_resolve_conn_params`, `_ConnParams` slims, both connect sites read `Node`.
  - `yascheduler/infra/cloud/manager.py` — `_setup_vm` stamps `Node.jump_*`; connect call drops jump kwargs.
  - `yascheduler/entrypoints/cli/manage_node.py` — `_add_node` resolves `[remote]` jump onto the tmp `NewNode` at insert.
- **APIs / Public Surface**: `MachineRepository.connect` Protocol signature change (BREAKING for any external implementor). The break is contained: `MachineRepository` is consumed only by the daemon, the cloud provisioner, and the `yastatus`/`yasetnode` CLIs — all in-tree. `class Yascheduler` public API, CLI command syntax, INI format, DB schema — unchanged.
- **DB**: no schema change, no migration. Existing rows with `jump_host = NULL` continue to mean "direct connection."
- **Config**: `[remote]` and `[engine.*]` INI keys for jump remain unchanged; they now serve only as defaults for newly-created nodes rather than as runtime-resolved values.
- **Operational behavior**: changing `[remote].jump_host` in INI no longer affects already-registered nodes on reconnect — operators must re-add or manually update affected nodes. This is the intended trade for predictability (the value in DB is the value used).
