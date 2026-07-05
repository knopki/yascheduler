# Explore Brief: simplify-cloud-connect-node-args

Half-page design checklist for the propose stage. Two separable but bundled
simplifications (user requested "A+B").

## Problem

The `MachineRepository.connect` port and the cloud `_connect_to_vm`/`_setup_vm`
chain carry redundant scalar args that are already present on the `Node`:

- **(A)** `connect(node, username, *, port, ...)` — `username` duplicates
  `node.username`, `port` duplicates `node.port`. All 4 call sites pass values
  derivable from the `node` they already pass. 4 existing `# FIXME` markers
  already flag this (ports.py ×1, repository.py connect + _connect_impl ×2... =
  actually ports.py:277/281, repository.py:152/156 + 202/206).
- **(B)** cloud `manager.py` threads `ip_addr: str` + `tmp_node_id: NodeId`
  through `_setup_vm` and `_connect_to_vm`, then builds an **ersatz** throwaway
  `Node(...enabled=False, ncpus=0)` inside `_connect_to_vm` just to call
  `connect`, plus a **second** real `Node` inside `_setup_vm`. `# FIXME: just
  use Node if you are already construct Node inside` sits above `_connect_to_vm`.

## Rejected Alternatives

- **Thread a pre-existing "real Node" from the top of the call chain** —
  rejected: no fully-formed Node exists upstream. The tmp Node from
  `_select_and_insert_tmp`'s `insert()` has `ip=""`, `username="root"` (wrong for
  connect). The correct `ip`/`username`/`cloud` only converge *inside*
  `manager.allocate` right after `adapter.create_node()` returns `ip_addr`. So
  the Node must be constructed once in `allocate`, not passed from `allocate_task`.
- **Also fold `jump_host`/`jump_username` onto Node** — rejected (YAGNI + wrong):
  those are per-connection config (cloud config / remote defaults), NOT node
  identity attributes. `connect` keeps them.
- **Make `_select_and_insert_tmp` return the tmp Node and `replace()` onto it** —
  rejected (YAGNI): couples cloud module to tmp-Node shape for no clarity gain.
- **Do only B (cloud-internal), defer A** — considered; rejected per user's
  explicit "A+B" instruction. Both done in one change, sequenced A-then-B in tasks.

## Final Approach — the two edits

### (A) Drop `username` and `port` from `connect`

`MachineRepository.connect` signature becomes:
`connect(node, client_keys, *, connect_timeout, data_dir, engines_dir, tasks_dir, jump_host, jump_username) -> MachineSession`

Inside `connect`/`_connect_impl`: use `node.username` (was param `username`) and
`node.port` (was param `port`) — passed into `_open_connection`.

`jump_host`/`jump_username`/`client_keys`/timeouts/dirs all STAY (not on Node).

### (B) Collapse 3 Node constructions → 1 in `manager.py`

New private signatures (drop `ip_addr`, `tmp_node_id`; add `node: Node`):
- `_setup_vm(node: Node, adapter, config) -> Node`
- `_connect_to_vm(node: Node, adapter, config) -> MachineSession`

`allocate` builds the Node ONCE, after `create_node`:
```
ip_addr = await adapter.create_node(...)
node = Node(node_id=tmp_node_id, ip=ip_addr, ncpus=0, enabled=False,
            cloud=adapter.name, username=config.username, port=22)
ready_node = await self._setup_vm(node, adapter, config)
```
`_connect_to_vm` calls `machine_repository.connect(node=node, client_keys=keys, ...)`
— NO ersatz construction.
`_setup_vm` returns `replace(node, enabled=True, ncpus=ncpus)` (not a fresh
`Node(...)`), honest that it's the same node transitioning enabled.

`allocate`'s two setup-failure `except` blocks still `disconnect(tmp_node_id)`
(now `disconnect(node.node_id)`) BEFORE `delete_node`. Unchanged semantics.

## Cross-module Data Flow (who calls who, params)

```
allocate_task._allocate_cloud_node
  -> clouds.allocate(provider, tmp_node_id: NodeId)         [UNCHANGED public sig]
     -> manager.allocate builds node ONCE
        -> _setup_vm(node, adapter, config)
           -> _connect_to_vm(node, adapter, config)
              -> machine_repository.connect(node=node, client_keys, *, timeouts, dirs, jump_*)   [A: no username/port]
        -> returns replace(node, enabled=True, ncpus)
```
Other 3 `connect` callers, arg change (all already pass node):
| caller | drops |
| --- | --- |
| orchestrator._connect_machine_consumer (orchestrator.py:285) | `username=node.username`, `port=node.port` |
| check_status._display_remote_output (check_status.py:323) | `username=conn_params.username`, `port=conn_params.port` |
| manage_node._add_node (manage_node.py:321) | `username=username`, `port=spec.port` |

Note: `_resolve_conn_params`/`_ConnParams` in check_status still resolve
username/port for display but no longer feed them to connect; keep `_ConnParams`
fields (used elsewhere for display) — verify before trimming. Actually username/port
in `_ConnParams` become connect-unused → evaluate removing from DTO.

## Affected specs (Modified Capabilities)

- `ssh-infrastructure` — `connect(...)` method signature line (spec §Collection
  lifecycle + §two-method pattern) drops `username`/`port`.
- `domain-ports` — MachineRepository port assertion (full sig delegated to
  ssh-infrastructure; update prose if it names username/port).
- `cloud` — `_setup_vm(ip_addr, tmp_node_id, adapter, config)` /
  `_connect_to_vm(...)` requirement text → `(node, adapter, config)`; ersatz Node
  language removed; `_setup_vm` returns `replace(node, enabled=True, ncpus)`.
- `cli` — manage_node add-flow step 2 (`repository.connect(node=T, username=...,
  port=...)` → drop those args); yastatus `_display_remote_output` connect;
  scenarios "yastatus -v uses node.username" / "passes node.port" reworded:
  effective username/port still equal node.username/node.port (read from node),
  just no longer passed as explicit args.

## Open Questions

1. Should `check_status._ConnParams` keep `username`/`port` fields (still used for
   display/`_render_json`?) or drop them? → Decide in design; default KEEP if any
   non-connect reader exists (grep showed `_render_json` reads node.port directly,
   so `_ConnParams.username/port` may be connect-only → candidate removal, but
   low-risk to keep). Lean: KEEP DTO fields to minimize blast radius; only stop
   passing them to connect.
2. Keep the 4 `# FIXME` markers' removal in scope — yes, delete them as the code
   is fixed.
3. Any test doubles / fakes implementing `MachineRepository.connect` with
   `username`/`port` in signature? → tasks must grep tests (test_ssh_gateway.py,
   test_cloud_provisioner_impl.py, test_cloud_alloc_session_lifecycle.py,
   test_allocate_task_failure_modes.py, conftest fakes) and update.
4. GRACE: knowledge-graph.xml + module contracts (manager.py v2.15.0, ports.py,
   repository.py, cli files) CHANGE_SUMMARY must be bumped.
