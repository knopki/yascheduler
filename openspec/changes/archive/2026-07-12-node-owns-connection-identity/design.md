## Context

Today the SSH connection identity is split: `Node.hostname` / `username` / `port` are authoritative (read inside `connect`), but the jump leg (`jump_host` / `jump_port` / `jump_username`) is re-resolved at every connect call from `[remote]` defaults with `[cloud.*]` overrides. `Node` already persists `jump_*` columns (migration `012`) as placeholders that no production code reads. Three sites duplicate the same resolution logic (orchestrator `_connect_machine_consumer`, `yastatus -v` `_resolve_conn_params`, `CloudProvisionerImpl._setup_vm`'s `config.jump_host or None` pass-through). `_resolve_tunnel` formats a `user@host` string, which silently drops `jump_port` and applies auth/timeout options only to the destination leg.

The codebase already has the precedent for the proposed shift: change `2026-07-05-simplify-cloud-connect-node-args` collapsed `username`/`port` from `connect` arguments onto `Node`. This change extends the same principle to the jump leg and is the second half of that earlier decision (whose explore-brief explicitly rejected folding jump onto Node as YAGNI at the time — that rejection is now superseded by the operator pain of the static-node asymmetry it left behind).

Constraints inherited from the project:

- Public surface stability (CLI command syntax, INI format, DB schema, `class Yascheduler` API) is preserved.
- DB columns already exist; no schema change, no migration.
- `[remote]` and `[engine.*]` INI keys remain — they become defaults for newly-created nodes rather than runtime-resolved values.

## Goals / Non-Goals

**Goals:**

- `Node.jump_host` / `jump_port` / `jump_username` become the single source of truth for the jump leg; populated once at creation, never re-resolved.
- `MachineRepository.connect` reads all connection identity (including jump) from `Node`; the Protocol loses `jump_host` / `jump_username` parameters.
- The tunnel leg honors `jump_port` and reuses auth/timeout options from the destination leg.
- Static nodes (`yasetnode`) acquire the configured jump host at insert time, closing the asymmetry where they previously failed behind a bastion.
- The three duplicated resolution sites collapse to zero.

**Non-Goals:**

- `ConnectedMachine.hostname` / `ncpus` removal — separate proposal.
- `MachineBusyError.hostname` removal — separate proposal (follows from ConnectedMachine diet).
- Static-Node `ncpus` persistence asymmetry — separate proposal.
- Backfill migration for existing rows — explicitly skipped (functionality was unused; `jump_host = NULL` continues to mean "direct connection").
- Cloud adapter expansion to return `port` / `username` / jump directly from `create_node` — future work; the provisioner continues to resolve from `CloudConfig` after hostname discovery.
- `yasetnode --reresolve-jump` or any CLI tooling for post-creation jump updates — YAGNI.
- Removing `[remote]` / `[engine.*]` jump INI keys — they remain as defaults source for new nodes.

## Decisions

### D1: Resolution timing — at creation, not at connect

| Path | When jump is stamped | Source |
|---|---|---|
| Static node (`yasetnode` add) | At `NewNode` construction, before `insert` | `[remote].jump_host` / `jump_user` from `config.remote` |
| Cloud node (allocator) | After `adapter.create_node` returns the hostname, before `replace(node, enabled=True, ...)` | Matching `CloudConfig` (`prefix == node.cloud`) if it sets both `jump_host` + `jump_username`; else `[remote]` fallback |

**Why at creation, not at connect:** the existing principle (hostname/username/port) is "Node is the identity; `connect` is a pure transport call." Re-resolving at connect re-introduces the duplication this change removes. Cloud-stamped values may differ from `[remote]` (per-provider bastion topologies) and must be captured at the moment the cloud selects the topology.

**Alternative considered:** resolve lazily on first `connect` and persist back to the row. Rejected: violates "Node is frozen identity" and introduces a write-on-read path through the SSH layer (which does not own persistence).

### D2: `connect` signature — drop both jump kwargs

```python
async def connect(
    self,
    node: Node,
    client_keys: Sequence[PurePath] | None,
    *,
    connect_timeout: int | None = None,
    data_dir: PurePath | None = None,
    engines_dir: PurePath | None = None,
    tasks_dir: PurePath | None = None,
) -> MachineSession
```

`_open_connection` similarly drops `jump_host` / `jump_username` and reads them from `node`.

**Why both kwargs and not just one:** partial removal leaves the duplication half-alive and the Protocol signature inconsistent with the "Node owns identity" principle.

### D3: `_resolve_tunnel` builds `SSHClientConnectionOptions`, not a string

Current (string, loses port + per-leg options):
```python
def _resolve_tunnel(jump_host, jump_username) -> str | None:
    return jump_host and jump_username and f"{jump_username}@{jump_host}"
```

Proposed (full options object):
```python
def _build_tunnel_options(
    node: Node,
    client_keys: Sequence[PurePath] | None,
    connect_timeout: int | None,
) -> SSHClientConnectionOptions | None:
    if not node.jump_host:
        return None
    return SSHClientConnectionOptions(
        options=DEFAULT_CONN_OPTS,           # keepalive, compression, agent_path, etc.
        host=node.jump_host,
        port=node.jump_port,
        username=node.jump_username,
        client_keys=client_keys or (),
        known_hosts=None,
        connect_timeout=connect_timeout,
    )
```

The resulting options object is passed as asyncssh's `tunnel=` argument. asyncssh accepts an `SSHClientConnectionOptions` (or comma-separated list for chained tunnels — future-proofing) and applies its fields when opening the tunnel leg.

**Why options object over string:** the string form `"user@host[:port]"` is parsed by asyncssh but its documented caveat is "any config options in the call will apply only when opening a connection to the final destination host and port." That means `client_keys` / `known_hosts` / `connect_timeout` set on the destination call would NOT apply to the bastion leg — silently breaking matched-key bastions or non-standard bastion ports. Options object avoids the caveat entirely.

**Why not pre-open the tunnel connection explicitly:** adds a coroutine to manage (open + close) for no gain — asyncssh internally does the same when handed an options object.

**Why default `jump_username="root"` still flows through:** when `node.jump_host` is set but `jump_username` was never explicitly given, the existing schema default `NOT NULL DEFAULT 'root'` carries a usable value. `node.jump_host is None` remains the "no tunnel" sentinel.

### D4: Static node jump source — `[remote]` only

`yasetnode` add-path resolves jump from `config.remote.jump_host` / `config.remote.jump_username` / `jump_port` (default 22). Static nodes have no cloud association, so there is no `CloudConfig` to consult.

**Alternative considered:** add a `--jump-host` flag to `yasetnode`. Rejected as YAGNI — operators with non-`[remote]` bastions can re-set `[remote]` before adding, or update the row directly. Captured as a non-goal.

### D5: Cloud node jump source — `CloudConfig` then `[remote]`, stamped BEFORE the setup connect

The allocator mirrors the logic currently inlined at orchestrator:275-280 and check_status:224-228:

```python
jump_host = config.remote.jump_host
jump_username = config.remote.jump_username
jump_port = 22
for cloud in config.clouds:
    if cloud.prefix == node.cloud:
        if cloud.jump_host and cloud.jump_username:
            jump_host = cloud.jump_host
            jump_username = cloud.jump_username
            # jump_port: not on CloudConfig today — keep schema default 22
        break
```

**Ordering constraint (critical):** jump MUST be stamped onto the `Node` BEFORE `_setup_vm` calls `_connect_to_vm` (manager.py:352). The setup SSH session (cloud-init wait, `setup_node`, `get_cpu_cores`) needs the bastion leg for any cloud VM behind a jump host. The current code threads jump via `_connect_to_vm`'s kwargs (`config.jump_host or None` at manager.py:454-455); once D2 removes those kwargs, the only path for the setup session to reach the bastion is through `node.jump_*`.

Two valid implementation sites (the tasks phase picks one):

| Site | Code location | Trade-off |
|---|---|---|
| (a) Top of `_setup_vm`, via dedicated `replace` before `_connect_to_vm` | new lines before manager.py:352 | Localized to `_setup_vm`; the final `replace(node, enabled=True, ncpus=...)` at line 412 then carries `jump_*` forward automatically (frozen dataclass — `replace` preserves them) |
| (b) In `allocate`, via the existing hostname/cloud/username `replace` at manager.py:186-192 | extends the identity-establishing replace | Cleaner conceptually (all identity stamped once in `allocate`); but `allocate` currently does not take `config` — would need a signature widening or a resolved-jump tuple threaded in |

Site (a) is recommended: smaller diff, no signature change, `_setup_vm` already receives `config`. The final `replace(node, enabled=True, ncpus=ncpus)` at line 412 does NOT need to re-stamp jump — the frozen dataclass preserves the earlier stamp.

**Why `jump_port` stays 22 for cloud:** `CloudConfig` DTOs do not currently carry `jump_port`. Adding it would expand the config DTO surface, the parser, and the `[engine.*]` INI keys for a value that has never been used. Deferred.

### D6: Removed resolution sites

| Site | Today | After |
|---|---|---|
| `orchestrator._connect_machine_consumer:275-280` | Inline cloud-prefix loop + `[remote]` fallback, passes `jump_host` / `jump_username` into `connect` | Loop deleted; `connect` call drops both kwargs |
| `check_status._resolve_conn_params` + `_ConnParams` | Whole helper resolves the 4 params; `_display_remote_output` and the default-path `_render_view` consume it | Helper deleted; both connect sites call `repository.connect(node=node, client_keys=...)` directly |
| `CloudProvisionerImpl._connect_to_vm:454-455` | `config.jump_host or None` / `config.jump_username or None` pass-through into `connect` (NOTE: this is in `_connect_to_vm`, NOT in `_setup_vm` — `_setup_vm` ends at line 412 and delegates the SSH open to `_connect_to_vm` at line 352) | Jump is stamped on `Node` per D5 before `_connect_to_vm` runs; the `connect` call inside `_connect_to_vm` drops both kwargs |

GRACE-lite bookkeeping note: the existing `START_CONTRACT: SSHMachineRepository.connect` INPUTS list (repository.py:146) still names `jump_host` / `jump_username`, and `MODULE_MAP` references `_resolve_tunnel`. Task 1.5 covers the contract/block/CHANGE_SUMMARY updates; `grace_check.py` will fail until they land.

### D7: Behavior on `Node.jump_host = None` after this change

`jump_host is None` means "no tunnel" — `_build_tunnel_options` returns `None`, asyncssh gets `tunnel=None`, connects direct. The `jump_username` (schema default `"root"`) and `jump_port` (schema default `22`) are simply ignored when `jump_host is None`; they are NOT evidence that a tunnel is configured. This matches every existing row — `jump_host` was added nullable in migration `012`, so every pre-existing row has `jump_host = NULL` regardless of `jump_username` / `jump_port` defaults.

## Risks / Trade-offs

**[Risk] INI jump changes no longer propagate to registered nodes** → Documented in the proposal's "Operational behavior" paragraph. Accepted trade for predictability: the value in DB is the value used. Operators with rare jump-topology changes re-add affected nodes or issue direct UPDATE.

**[Risk] Static-node tmp phase runs without jump if `yasetnode` defers stamping** → Mitigated by D1: jump is stamped at `NewNode` construction, before `insert`, so the tmp row used for the connect-setup verification already carries it.

**[Risk] Cloud-node stamping races with parallel connect attempts** → None: `_setup_vm` is the only site that flips `enabled=True`, and the orchestrator's connect-machine loop only yields `enabled=True` nodes. The row is invisible to the orchestrator until the stamping `update` commits.

**[Risk] Cloud-first setup connect loses bastion if stamping happens too late** → The ordering constraint in D5 is the mitigation: jump MUST be stamped before `_connect_to_vm` opens the setup SSH session (cloud-init wait, `setup_node`, `get_cpu_cores`). An implementer who stamps only at the final `replace(node, enabled=True, ...)` (manager.py:412) will silently regress every cloud node behind a bastion — the setup session connects direct, fails, and `allocate` raises `CloudSetupError`. Task 5.1-5.4 encode the constraint explicitly; the cloud spec already encodes it ("BEFORE the connect-setup SSH session is opened").

**[Risk] Existing tests construct `MachineRepository` mocks with `jump_host` / `jump_username` kwargs** → Mechanical test update; the breaking-change flag is in the proposal. Affects `test_cli_check_status.py`, `test_connect_machine_consumer.py`, `test_cloud_alloc_session_lifecycle.py`, `test_cloud_provisioner_impl.py`, `test_ssh_gateway.py`, AND `test_domain_ports.py` (the `StubMachineRepository.connect` stub at lines 240-253 carries the kwargs — must be updated even though `@runtime_checkable` would not flag it). The tasks phase enumerates them.

**[Risk] `SSHClientConnectionOptions` API differs across asyncssh versions** → The project already pins asyncssh and uses `SSHClientConnectionOptions(...)` extensively in `_open_connection` (repository.py:118). No new dependency surface.

**[Trade-off] `jump_port` for cloud nodes stays 22** → Limitation accepted; expanding `CloudConfig` is YAGNI until a cloud actually needs a non-22 bastion port. The `Node.jump_port` column already supports it; only the cloud-stamp path uses the default.

## Migration Plan

No DB migration. Code deployment steps:

1. Ship the code change. New static nodes (added via `yasetnode`) get jump stamped from `[remote]`. New cloud nodes get jump stamped from the matching `CloudConfig` (or `[remote]` fallback).
2. Existing rows keep their `jump_host = NULL` — they continue to connect directly. If an operator had an active `[remote].jump_host` configuration that was being applied at runtime, those existing nodes will silently switch to direct connection on next daemon restart. **This is the one operator-visible regression** and is documented in the proposal.
3. Mitigation for affected operators: re-add the node via `yasetnode`, or `UPDATE yascheduler_nodes SET jump_host=..., jump_username=... WHERE node_id=...`.

Rollback: revert the code change; existing resolution sites are restored. No data was migrated, so nothing to migrate back.

## Open Questions

None material. `jump_port` default for cloud nodes (22 vs. inheriting from `CloudConfig`) is deferred per D5 and does not block this change.
