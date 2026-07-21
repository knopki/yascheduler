## 1. DB Migration & Schema

- [x] 1.1 Create `yascheduler/infra/persistence/sql/migrations/012_node_rename_and_fields.sql` — rename `ip`→`hostname` (VARCHAR(255)), add `created_at`/`updated_at` + trigger, `jump_host`/`jump_port`/`jump_username`, `external_id` (backfill for cloud rows only), `NODE_STATUS` enum + `status` column, `port` NOT NULL + CHECK, `jump_port` CHECK
- [x] 1.2 Update `yascheduler/infra/persistence/sql/schema.sql` — bump `last_migration` constant `'011'`→`'012'`; update `CREATE TABLE yascheduler_nodes` snapshot with all new columns + constraints; add `NODE_STATUS` enum creation; add `yascheduler_nodes_touch_updated_at` trigger block

## 2. Domain Layer

- [x] 2.1 Add `StrEnum` re-export to `yascheduler/shared/compat.py` (version-branch: `enum.StrEnum` on 3.11+, `typing_extensions.StrEnum` below; add to `__all__`)
- [x] 2.2 Add `NodeStatus(StrEnum)` enum to `yascheduler/domain/model.py` with single value `OTHER = "OTHER"`; update module map + change summary
- [x] 2.3 Rename `ip`→`hostname` on `Node` and `NewNode` in `yascheduler/domain/model.py`; add new fields (`jump_host`, `jump_port`, `jump_username`, `external_id`, `status`, `created_at`, `updated_at`) to both; update contracts + module map + change summary
- [x] 2.4 Rename `ip`→`hostname` on `ConnectedMachine` in `yascheduler/domain/model.py`; update `MachineBusyError(self.ip)`→`MachineBusyError(self.node_id, self.hostname)` in `occupy()`; update contract + scenarios
- [x] 2.5 Update `yascheduler/domain/exceptions.py` — `MachineBusyError.__init__(node_id: NodeId, hostname: str)` + message format `"machine ({node_id}) at {hostname} is busy"`; `MachineConnectionError.__init__(node_id: NodeId, hostname: str, reason: str)` + message format `"cannot connect to machine ({node_id}) at {hostname}: {reason}"`; update contracts
- [x] 2.6 Update `yascheduler/domain/ports.py` — rename `MachineSession.ip` property→`hostname`; update `CloudProvisioner` docstring `node.ip`→`node.hostname`; update module map + change summary
- [x] 2.7 Update `yascheduler/domain/__init__.py` if it re-exports `Node`/`NewNode`/`ConnectedMachine` (ensure new fields are visible)

## 3. SSH Infrastructure

- [x] 3.1 Update `yascheduler/infra/ssh/session.py` — rename `SSHMachineSession.__init__` param `ip`→`hostname`, `_ip`→`_hostname`, `ip` property→`hostname`; update contract + module map + change summary
- [x] 3.2 Update `yascheduler/infra/ssh/repository.py` — `_connect_impl`: `node.ip`→`node.hostname` (4 sites), `ConnectedMachine(ip=...)`→`ConnectedMachine(hostname=...)`, `SSHMachineSession(ip=...)`→`SSHMachineSession(hostname=...)`, `MachineConnectionError(node.ip, ...)`→`MachineConnectionError(node.node_id, node.hostname, ...)`; `_open_connection` call `node.ip`→`node.hostname`; update contracts + change summary
- [x] 3.3 Update `yascheduler/infra/ssh/operations/occupancy.py` — `session.ip`→`session.hostname` in all log lines (~6 sites)
- [x] 3.4 Update `yascheduler/infra/ssh/operations/deployment.py` — `session.ip`→`session.hostname` in all log lines (~3 sites)

## 4. Cloud Infrastructure

- [x] 4.1 Update `yascheduler/infra/cloud/manager.py` — `node.ip`→`node.hostname` in all log lines (~15 sites); `replace(node, ip=ip_addr, ...)`→`replace(node, hostname=ip_addr, external_id=ip_addr, ...)` in `allocate`; `adapter.delete_node(host=node.ip)`→`host=node.hostname`; update contracts + change summary
- [x] 4.2 Update `yascheduler/infra/cloud/providers/hetzner.py` — check if `node.ip` references exist (the `server.public_net.ipv4.ip` is the SDK field, not `node.ip` — verify and rename only `node.ip` references if any)

## 5. Application Layer

- [x] 5.1 Update `yascheduler/application/allocate_task.py` — `session.ip`/`node.ip`→`.hostname` (6 sites); update contracts + change summary
- [x] 5.2 Update `yascheduler/application/abandon_node.py` — `node.ip`→`node.hostname` (3 sites in logs); update contracts + change summary
- [x] 5.3 Update `yascheduler/application/deallocate_nodes.py` — `node.ip`→`node.hostname` (6 sites in logs); update contracts + change summary
- [x] 5.4 Update `yascheduler/application/orchestrator.py` — `node.ip`→`node.hostname` (5 sites in logs); update contracts + change summary

## 6. Persistence Layer

- [x] 6.1 Update all 12 `yascheduler/infra/persistence/sql/node/*.sql` files — rename `ip`→`hostname` in SELECT/INSERT/UPDATE/WHERE clauses; `count_by_status.sql`: `COUNT(ip)`→`COUNT(node_id)`; `list_disabled.sql`: `ip <> ''`→`hostname <> ''`; `insert.sql`/`update.sql`: add new columns (`jump_host`, `jump_port`, `jump_username`, `external_id`, `status`, `created_at`, `updated_at` for INSERT RETURNING / UPDATE SET)
- [x] 6.2 Update `yascheduler/infra/persistence/postgres.py` — `PostgresNodeRepository.insert`: bind `hostname` + new columns; `update`: bind `hostname` + new columns; `_row_to_node`: read `hostname` + new columns (`created_at`, `updated_at`, `jump_host`, `jump_port`, `jump_username`, `external_id`, `status` via `NodeStatus[row["status"]]`); update contracts + change summary

## 7. CLI & Client

- [x] 7.1 Update `yascheduler/entrypoints/cli/show_nodes.py` — `_NodeView.ip`→`.hostname`; table header `IP`→`HOSTNAME`; `_render_nodes_json`: `"ip"`→`"hostname"` + add all new fields (`jump_host`, `jump_port`, `jump_username`, `external_id`, `status`, `created_at`, `updated_at`); update contracts + change summary
- [x] 7.2 Update `yascheduler/entrypoints/cli/check_status.py` — `_render_json`: `"ip"`→`"hostname"` + add all new node fields to the `node` object; `_render_view`: `node.ip`→`node.hostname`; `_display_remote_output`: `"NO ALLOCATED IP"`→`"NO ALLOCATED HOSTNAME"`; update contracts + change summary
- [x] 7.3 Update `yascheduler/entrypoints/cli/manage_node.py` — `node.ip`→`node.hostname` in print statements / filter / comments (~8 sites); update contracts + change summary
- [x] 7.4 Update `yascheduler/entrypoints/client.py` — JSON key `"ip"`→`"hostname"` + add all new node fields to the `node` dict; update contracts + change summary

## 8. Knowledge Graph & GRACE-lite

- [x] 8.1 Update `docs/knowledge-graph.xml` — update `M-DOMAIN-MODEL` annotations for `Node`/`NewNode`/`ConnectedMachine` field changes; add `NodeStatus` annotation; update `M-DOMAIN-EXCEPTIONS` annotations for `MachineBusyError`/`MachineConnectionError` signature changes; update any `CrossLink` referencing `node.ip`→`node.hostname`
- [x] 8.2 Run `python3 scripts/grace_check.py` and fix any reported issues

## 9. Tests

- [x] 9.1 Update `tests/unit/test_domain_exceptions.py` — `MachineBusyError`/`MachineConnectionError` construction + assertion sites: add `node_id` first arg, rename `exc.ip`→`exc.hostname` (3 sites)
- [x] 9.2 Update `tests/unit/test_ssh_gateway_connect.py` — `MachineConnectionError` assertion sites: add `node_id` arg, `exc.ip`→`exc.hostname` (3 sites)
- [x] 9.3 Update `tests/unit/test_application_use_cases.py` — `Node(ip=...)`→`Node(hostname=...)`, `node.ip`→`node.hostname` (~15 sites)
- [x] 9.4 Update `tests/unit/test_cli_show_nodes.py` — `Node(ip=...)`→`Node(hostname=...)`, `_NodeView` assertions, JSON key assertions `"ip"`→`"hostname"` + new fields (~20 sites)
- [x] 9.5 Update `tests/unit/test_cli_check_status.py` — `Node(ip=...)`→`Node(hostname=...)`, JSON assertions `"ip"`→`"hostname"`, `node.ip`→`node.hostname` (~15 sites)
- [x] 9.6 Update `tests/unit/test_cli_manage_node.py` — `Node(ip=...)`→`Node(hostname=...)`, `node.ip`→`node.hostname` (~10 sites)
- [x] 9.7 Update `tests/unit/test_allocate_task_failure_modes.py` — `Node(ip=...)`→`Node(hostname=...)` (~5 sites)
- [x] 9.8 Update `tests/unit/test_application_events.py` — `Node(ip=...)`→`Node(hostname=...)`, `free_machine.ip`→`.hostname` (~5 sites)
- [x] 9.9 Update `tests/unit/test_ssh_gateway.py` — `Node(ip=...)`→`Node(hostname=...)`, `session.ip`→`session.hostname`, `machine.ip`→`machine.hostname` (~10 sites)
- [x] 9.10 Update `tests/unit/test_cloud_alloc_session_lifecycle.py` — `Node(ip=...)`→`Node(hostname=...)`, `NewNode(ip=...)`→`NewNode(hostname=...)`, `session.ip`→`session.hostname`, `node.ip`→`node.hostname` (~20 sites)
- [x] 9.11 Update `tests/unit/test_connect_machine_consumer.py` — `Node(ip=...)`→`Node(hostname=...)` (~5 sites)
- [x] 9.12 Grep for remaining `.ip` references in `tests/` and fix any missed sites
- [x] 9.13 Add unit test for `NodeStatus` enum (isinstance str, `NodeStatus["OTHER"]` lookup, value `"OTHER"`)
- [x] 9.14 Add unit test for `MachineBusyError(node_id, hostname)` and `MachineConnectionError(node_id, hostname, reason)` new signatures
- [x] 9.15 Add integration test for migration 012 (testcontainers: apply migration, verify columns, verify `external_id` backfill for cloud rows only, verify `NODE_STATUS` enum, verify port CHECK)

## 10. Validation

- [x] 10.1 Run `uv run pytest -m unit` — all unit tests pass
- [x] 10.2 Run `uv run pytest -m integration` — all integration tests pass (including migration 012 test)
- [x] 10.3 Run `uv run pytest -m e2e` — all e2e tests pass
- [x] 10.4 Run `uv run zuban check` — passes
- [x] 10.5 Run `uv run ruff check .` — passes
- [x] 10.6 Run `uv run ruff format --check .` — passes
- [x] 10.7 Run `uv run lint-imports` — passes
- [x] 10.8 Run `openspec validate --all --json` — passes
- [x] 10.9 Run `python3 scripts/grace_check.py` — passes