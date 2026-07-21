## Why

`hetzner_create_node` stores the server's public IP as `external_id`. `hetzner_delete_node` then iterates all servers (`client.servers.get_all()`) in `find_srv` to locate the matching IP — an O(n) scan over every server in the project, adding latency and I/O on every deallocation. The Hetzner API already returns a numeric `server.id` on creation, which `client.servers.get_by_id()` can resolve directly in O(1).

Without this change: every Hetzner VM deletion requires listing all servers, which scales linearly with project size and adds a fragile IP-matching step that fails silently (not-found → no-op log line) whenever the API temporarily returns incomplete server lists or the server's IP field is unreachable.

## What Changes

- **MODIFIED** `yascheduler/infra/cloud/providers/hetzner.py::hetzner_create_node`: store `str(server.id)` as `external_id` instead of `ip_str`; `hostname` remains the IP
- **MODIFIED** `yascheduler/infra/cloud/providers/hetzner.py::hetzner_delete_node`: use `client.servers.get_by_id(int(external_id))` instead of `find_srv(client, external_id)` — O(1) lookup, no list-all scan
- **REMOVED** `yascheduler/infra/cloud/providers/hetzner.py::find_srv` — no longer needed
- **MODIFIED** `tests/unit/test_cloud_provider_create_delete.py`: Hetzner mock assertions — `external_id` now carries the numeric server ID, tests mock `get_by_id` instead of `get_all` on delete
- **MODIFIED** `tests/e2e/test_hetzner_live.py`: cleanup helpers (`_assert_vm_deleted`, `_delete_one_best_effort`, `_cleanup_observed`) switch from IP-based to server-ID-based server lookup; observed-IP tracking remains for scenario assertions

**Upgrade note:** Old `external_id` values in the database (IP strings) will cause `get_by_id(int(ip))` to fail cleanly (404 from Hetzner API → server not found → no-op log). All existing cloud VMs must be deleted before deploying this change. No DB migration is required — the column schema is unchanged.

## Capabilities

### Modified Capabilities

- `hetzner`: `create_node` stores numeric server ID as `external_id` instead of IP; `delete_node` resolves the server in O(1) via `get_by_id` instead of O(n) via `find_srv`; `find_srv` function removed

## Impact

- `yascheduler/infra/cloud/providers/hetzner.py` — `hetzner_create_node` external_id field, `hetzner_delete_node` resolution strategy, `find_srv` removed
- `tests/unit/test_cloud_provider_create_delete.py` — Hetzner test mocks and assertions update
- `tests/e2e/test_hetzner_live.py` — cleanup helpers use server ID for deletion
- No change to: `CloudCreateNodeDTO`, `DeleteNodeCallable` protocol, `CloudAdapter`, `manager.py`, domain `Node` model, DB schema, other cloud providers (Azure, UpCloud, VastAI follow current IP-as-external_id pattern unchanged)
- **Pre-deployment requirement:** all existing Hetzner VMs must be deleted before this change is deployed; old IP-string `external_id` values are not retroactively resolvable to server IDs
