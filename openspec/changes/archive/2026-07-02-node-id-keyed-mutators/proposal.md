## Why

`yascheduler_nodes` gained `node_id SERIAL PRIMARY KEY` and a `NodeId` value object in `add-node-id-identity`, but the four `NodeRepository` mutators (`enable`, `disable`, `remove`, `update`) still key on `ip`. `ip` is the legacy de-facto identity; `node_id` is the real one. The mutators are the cheapest, most isolated surface to switch first — every call-site already holds a `Node` (hence `node.node_id`) except two tmp-cleanup paths in `allocate_task`, which get a `get(tmp_ip)` lookup. This change replaces ip-keying with `node_id`-keying on the mutator surface only, establishing the pattern that follow-up changes (lookup methods, SSH layer, `Task.allocated_ip`, `add_tmp` fake-ip removal) extend.

## What Changes

- **`NodeRepository` Protocol** (`yascheduler/domain/ports.py`): `enable`, `disable`, `remove` signatures change `ip: str → node_id: NodeId`. `update(node: Node)` signature is unchanged (already takes `Node`); its SQL key changes. The Protocol docstring's "all ip-keyed mutators keep their ip keying" statement is updated to reflect the new keying.

- **`PostgresNodeRepository`** (`yascheduler/infra/persistence/postgres.py`): `enable`/`disable`/`remove` accept `node_id: NodeId` and pass `node_id.value` (the bare int — pg8000 cannot adapt a `NodeId` dataclass, same pattern as the existing `get_by_id`). `update` passes `node_id=node.node_id.value` alongside the existing field params.

- **SQL queries** (`yascheduler/infra/persistence/sql/node/`): `enable.sql`, `disable.sql`, `remove.sql`, `update.sql` change `WHERE ip = :ip → WHERE node_id = :node_id`. No schema migration is needed — `node_id` is already `SERIAL PRIMARY KEY` (migration `002_add_node_id.sql` ran in `add-node-id-identity`).

- **Application call-sites** (all hold `Node`):
  - `deallocate_node` (`application/deallocate_nodes.py`): `disable(node.ip) → disable(node.node_id)`, `remove(node.ip) → remove(node.node_id)`.
  - `deallocate_nodes` (`application/deallocate_nodes.py`): the disable loop iterates `all_enabled_nodes: dict[str, Node]` — switch to iterate `.values()` and call `disable(node.node_id)` (Node already in the dict value; today the loop uses the ip key).
  - `abandon_node` (`application/abandon_node.py`): `remove(node.ip) → remove(node.node_id)`.

- **`allocate_task` tmp-cleanup** (the two sites without `Node` in hand): `_cleanup_tmp_node_best_effort` and `_persist_node_with_cleanup` add a `uow.nodes.get(tmp_ip)` lookup before `remove(node.node_id)`. Best-effort paths; tmp-node is just-inserted with a unique MD5-placeholder ip, so no TOCTOU risk. If `get` returns `None` (row already removed), skip `remove` (matches current no-op-on-0-rows behavior — no rowcount check added).

- **CLI `manage_node`** (`entrypoints/cli/manage_node.py`): the validation UoW already resolves a `Node` (via `get_by_id` on the node_id path, via `_get_by_ip` on the host_spec path). The private helpers `_remove_node_hard` and `_remove_node_soft` change signature from `(deps, ip: str)` to `(deps, node: Node)`. Inside, `node.node_id` feeds `nodes.disable`/`nodes.remove`; `node.ip` stays for `tasks.list_ids_by_ip_and_status(ip, RUNNING)` (Surface C, unchanged) and user-facing output (`print(f"Removed host from yascheduler: {ip}")` — operators read ip, not node_id). The CLI surface (`_parse_node_args`, `NodeTarget`, argparse, exit codes) is unchanged.

- **Internal logs**: `deallocate_node` and `abandon_node` log lines gain `node_id=%s` alongside the existing `ip=%s`. User-facing CLI output stays ip-only.

- **Tests updated** (not adapted to — signatures changed, tests reflect the new contract):
  - `tests/unit/test_domain_ports.py`: `StubNodeRepository.enable`/`disable`/`remove` signatures updated to take `NodeId` (match Protocol).
  - `tests/unit/test_cli_manage_node.py`: 2 `disable.assert_called_once_with("10.0.0.1")` → `disable.assert_called_once_with(<NodeId>)`.
  - `tests/unit/test_application_use_cases.py`: 6 `disable` asserts → `NodeId`.
  - `tests/integration/test_db_integration.py`: `enable("10.0.0.1")`/`disable("10.0.0.1")` → `enable(NodeId(...))`/`disable(NodeId(...))` (real DB, same row's node_id).
  - New tests: tmp-cleanup lookup path (`_cleanup_tmp_node_best_effort`/`_persist_node_with_cleanup` calling `get` then `remove(node.node_id)`).

- **GRACE-lite**: `docs/knowledge-graph.xml` `M-DOMAIN-PORTS` and `M-PERSISTENCE` annotations updated; MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY in `ports.py`, `postgres.py`, `deallocate_nodes.py`, `abandon_node.py`, `allocate_task.py`, `manage_node.py`; function contracts on changed methods/helpers.

## Capabilities

### New Capabilities

(None — this change modifies existing capabilities; no new spec file is created.)

### Modified Capabilities

- `domain-ports`: `NodeRepository.enable`/`disable`/`remove` REQUIREMENTS change key from `ip: str` to `node_id: NodeId`. `update` REQUIREMENT clarifies SQL keys on `node_id` (signature unchanged). The "all ip-keyed mutators keep their ip keying" statement is replaced.
- `postgres-persistence`: `PostgresNodeRepository.enable`/`disable`/`remove` REQUIREMENTS change SQL param from `ip` to `node_id.value`; `update` changes `WHERE ip` → `WHERE node_id`. The SQL-file-layout requirement covers `node/{enable,disable,remove,update}.sql` `WHERE` clause changes.
- `use-cases`: `DeallocateIdleNodes` and `AbandonNode` REQUIREMENTS change call-site key from `node.ip` to `node.node_id` (disable/remove). `AllocateTask` tmp-cleanup REQUIREMENT changes to `get(tmp_ip)` lookup before `remove(node.node_id)`.
- `cli`: `yasetnode positional discriminates node_id from host` and `yasetnode dispatches add and remove paths` REQUIREMENTS change — remove helpers take `Node` (not `ip: str`); `nodes.disable`/`nodes.remove` call with `node.node_id`; `tasks.list_ids_by_ip_and_status` stays ip-keyed (Surface C); validation UoW resolves `Node` early on both paths (`get_by_id` for node_id, `get(ip)` for host_spec).

## Impact

- **Code**: `yascheduler/domain/ports.py` (Protocol), `yascheduler/infra/persistence/postgres.py` (Impl), 4 SQL files, `yascheduler/application/deallocate_nodes.py`, `yascheduler/application/abandon_node.py`, `yascheduler/application/allocate_task.py` (tmp-cleanup), `yascheduler/entrypoints/cli/manage_node.py` (helpers + validation flow), `tests/unit/test_domain_ports.py` (`StubNodeRepository` signatures), `tests/unit/test_cli_manage_node.py`, `tests/unit/test_application_use_cases.py`, `tests/integration/test_db_integration.py`.
- **No DB migration**: `node_id SERIAL PRIMARY KEY` already exists (migration `002`). No schema change.
- **No public-API break**: `Yascheduler` facade / Python client / INI config / CLI commands surface unchanged. The `NodeRepository` Protocol is internal.
- **No new dependencies**.
- **Out of scope (explicit non-goals)**: `add_tmp` signature / `insert_tmp.sql` fake-ip / `"." in ip` echo-filters (separate change `remove-tmp-node-fake-ip`); `get` / `get_by_ips` / `list_*` lookup methods (Surface B-3); SSH layer `connect`/`disconnect`/`get_session`/`contains` (Surface A, ip = transport address); `Task.allocated_ip` / `TaskAllocated.node_ip` / `TaskRepository.list_ids_by_ip_and_status` (Surface C); `CloudProvisioner.deallocate(cloud, ip)` (ip = cloud host); `ip UNIQUE` constraint (stays as guard during transition).