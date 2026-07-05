# Design: simplify-cloud-connect-node-args

## Context

`MachineRepository.connect` (domain port `yascheduler/domain/ports.py:274`, impl
`yascheduler/infra/ssh/repository.py:149` + `_connect_impl:199`) currently has the
signature:

```python
async def connect(self, node: Node, username: str,
                  client_keys: Sequence[PurePath] | None, *, port: int = 22,
                  connect_timeout=None, data_dir=None, engines_dir=None,
                  tasks_dir=None, jump_host=None, jump_username=None) -> MachineSession
```

`node.username` and `node.port` already exist on the `Node` dataclass
(`domain/model.py:537` — `username: str = "root"`, `port: int = 22`), so
`username` and `port` are redundant. Six `# FIXME` markers say so directly
(two in `ports.py`, four in `repository.py` across `connect` and `_connect_impl`),
plus a seventh in `manager.py` above `_connect_to_vm` flagging the ersatz `Node`.

In the cloud allocation path, `manager.allocate(provider, tmp_node_id)`:
1. `ip_addr = await adapter.create_node(...)`
2. `node = await self._setup_vm(ip_addr, tmp_node_id, adapter, config)`
3. `_setup_vm` calls `self._connect_to_vm(ip_addr, tmp_node_id, adapter, config)`
4. `_connect_to_vm` builds an **ersatz** `Node(node_id=tmp_node_id, ip=ip_addr,
   ncpus=0, enabled=False, cloud=adapter.name, username=config.username,
   port=22)` solely to pass to `connect`
5. `_setup_vm` then builds a **second** real `Node(node_id=tmp_node_id,
   ip=ip_addr, enabled=True, ncpus=ncpus, ...)` as its return value

Three `Node` constructions for one logical node, with `ip_addr`/`tmp_node_id`
threaded as loose scalars. The correct `ip`/`username`/`cloud` only converge
*inside* `allocate` after `create_node` returns, so the Node cannot be threaded
in from `allocate_task` — it must be built once inside `allocate`.

## Goals / Non-Goals

**Goals:**
- Remove `username` and `port` from `MachineRepository.connect` and its impl;
  read `node.username` / `node.port` internally.
- Reduce the cloud chain to a single `Node` construction threaded as `node: Node`
  through `_setup_vm` / `_connect_to_vm`; eliminate the ersatz `Node`.
- Preserve every externally observable behavior: same wire host/user/port, same
  tmp-node single-row UPDATE lifecycle, same failure/cleanup semantics.
- Remove the five now-obsolete `# FIXME` markers.

**Non-Goals:**
- Do NOT change `CloudProvisioner.allocate(provider, tmp_node_id)` public
  signature — `allocate_task` keeps calling it with `tmp_node_id: NodeId`.
- Do NOT fold `jump_host`/`jump_username`/`client_keys`/timeouts/dirs onto `Node`
  — they are per-connection config, not node identity.
- Do NOT change `_select_and_insert_tmp` to return a full tmp `Node` (rejected —
  couples cloud module to tmp-Node shape; the tmp Node has `ip=""` and wrong
  username anyway).
- Do NOT defer (A) and do only (B) — considered (B is cloud-internal and lower
  risk, A touches the domain port + 4 call sites). Rejected per the explicit
  A+B request; both are bundled in one change and sequenced A-then-B in tasks so
  each diff stays small.
- No DB schema, CLI surface, INI, or AiiDA changes.

## Decisions

### Decision 1: Remove `username`/`port` from `connect`, keep everything else

New port + impl signature:

```python
async def connect(self, node: Node,
                  client_keys: Sequence[PurePath] | None, *,
                  connect_timeout: int | None = None,
                  data_dir: PurePath | None = None,
                  engines_dir: PurePath | None = None,
                  tasks_dir: PurePath | None = None,
                  jump_host: str | None = None,
                  jump_username: str | None = None) -> MachineSession
```

`_connect_impl` passes `node.username` and `node.port` into `_open_connection`
(where `username`/`port` were previously threaded). `client_keys` stays a
positional param (it is not on `Node`).

**Why:** `username`/`port` are pure duplication of `node` attributes at every one
of the four call sites (proven below). The other kwargs are genuinely
per-connection (jump host, keys dir, timeouts, remote dirs) and have no home on
`Node`.

**Alternatives considered:**
- *Keep the params for "flexibility"* — rejected: YAGNI, no caller ever passes a
  username/port that differs from `node.username`/`node.port`; the five FIXMEs
  document the intent to remove.
- *Also move jump params onto Node* — rejected: they are connection-topology
  config sourced from cloud config / remote defaults, not node identity.

### Decision 2: Call-site updates (all four already pass a `node`)

| Call site | Before (dropped args) | After |
| --- | --- | --- |
| `orchestrator._connect_machine_consumer` (orchestrator.py:285) | `username=node.username`, `port=node.port` | pass neither |
| `check_status._display_remote_output` (check_status.py:323) | `username=conn_params.username`, `port=conn_params.port` | pass neither |
| `manage_node._add_node` (manage_node.py:321) | `username=username`, `port=spec.port` | pass neither (node `T` already carries them) |
| `manager._connect_to_vm` (manager.py:465) | `username=config.username`, `port=22` | pass neither |

Effective behavior is identical because each dropped value already equals the
passed `node`'s attribute:
- orchestrator: `node.username`/`node.port` verbatim.
- check_status: `_ConnParams.username = node.username`, `.port = node.port`
  (check_status.py:231-232).
- manage_node: tmp node `T` was inserted as `NewNode(..., port=spec.port,
  username=username, ...)`, so `T.username == username`, `T.port == spec.port`.
- manager: the constructed `node` carries `username=config.username`, `port=22`.

### Decision 3: `check_status._ConnParams` keeps `username`/`port` fields

`_ConnParams` (`check_status.py:201`) will no longer feed `username`/`port` to
`connect`, but the DTO retains those fields. **Why keep:** minimizes blast radius;
the DTO is built from the node either way, and removing fields is an unrelated
cleanup. `jump_host`/`jump_username` on `_ConnParams` are still passed to
`connect`, so the DTO stays. (If a later change wants to slim it, that is its own
scope.)

### Decision 4: Single `Node` construction in `manager.allocate`; `replace` for the enabled transition

```python
# in allocate, after create_node:
ip_addr = await adapter.create_node(...)
node = Node(node_id=tmp_node_id, ip=ip_addr, ncpus=0, enabled=False,
            cloud=adapter.name, username=config.username, port=22)
try:
    ready = await self._setup_vm(node, adapter, config)
except CloudSetupError:
    ... disconnect(node.node_id) ... delete_node ...
    raise
except Exception as err:
    ... disconnect(node.node_id) ... delete_node ...
    raise CloudSetupError(...) from err
return ready
```

```python
async def _setup_vm(self, node: Node, adapter, config) -> Node:
    session = await self._connect_to_vm(node, adapter, config)
    ... cloud-init (uses node.ip in messages) ...
    ... setup_node, get_cpu_cores ...
    return replace(node, enabled=True, ncpus=ncpus)

async def _connect_to_vm(self, node: Node, adapter, config) -> MachineSession:
    keys = await ...list_private_keys...
    try:
        return await self.machine_repository.connect(
            node=node, client_keys=keys,
            connect_timeout=adapter.create_node_conn_timeout,
            data_dir=self.remote_config.data_dir,
            engines_dir=self.remote_config.engines_dir,
            tasks_dir=self.remote_config.tasks_dir,
            jump_host=config.jump_host or None,
            jump_username=config.jump_username or None,
        )
    except Exception as err:
        raise CloudSetupError(f"SSH connect to {node.ip} failed: {err}") from err
```

**Why `replace(node, enabled=True, ncpus=ncpus)`** over re-constructing `Node(...)`:
it is the same node transitioning state, and `replace` preserves `node_id`, `ip`,
`cloud`, `username`, `port` without re-listing them — honest and less error-prone.

**Why the `ncpus=0, enabled=False` seed on the initial `node`:** it mirrors the
old ersatz Node exactly (which used `ncpus=0, enabled=False`), so `connect`
(which reads only `node.ip`, `node.node_id`, `node.username`, `node.port`) sees
identical inputs; `ncpus`/`enabled` are irrelevant to `connect` and are corrected
by the `replace` on return.

**Alternatives considered:**
- *Thread `node` from `allocate_task` down through `allocate`* — rejected:
  `allocate`'s public signature is `(provider, tmp_node_id)` (a frozen public
  contract) and `ip`/`username` aren't known until `create_node` runs inside
  `allocate`.
- *Build `node` in `_setup_vm` instead of `allocate`* — rejected: `allocate`'s
  failure-handling `except` blocks need `node.node_id` for `disconnect`, and
  building it in `allocate` keeps the ownership at the level that also owns
  create/delete.

### Decision 5: Test doubles updated to match the new port

- `StubMachineRepository.connect` (`test_domain_ports.py:241`): remove
  `username`/`port` params.
- `FakeMachineRepository.connect` (`test_cloud_alloc_session_lifecycle.py:118`):
  already `username: str | None = None` + `**kwargs`; drop the `username` param
  (it reads `node` for everything). `**kwargs` still absorbs the rest.
- Grep all tests for `connect(` / `.connect(` kwargs asserting `username=` or
  `port=` and update.

## Risks / Trade-offs

- **Risk: a hidden caller/test passes `username`/`port` positionally.** Mitigation:
  `client_keys` was the 3rd positional; after removal `client_keys` becomes 2nd
  positional. Grep confirmed only four production callers and two test doubles,
  all using keyword args for `username`/`port` except the signatures themselves.
  Tasks include a repo-wide grep gate.
- **Trade-off: `_ConnParams` keeps now-connect-unused fields** (Decision 3). Minor
  dead-ish data vs. a wider, unrelated diff. Accepted.
- **Risk: `zuban`/`ruff` unused-import or unused-var after dropping params** (e.g.
  a local `username =`/`port =` that only fed `connect`). Mitigation: tasks
  include static-check gate (`uv run zuban check`, `ruff check`).
- **Low behavioral risk overall**: no wire-level change — same host, username,
  port, jump config sent to asyncssh; verified by the equality table in Decision 2.
