## Context

`hetzner_create_node` stores the VM's public IP as `external_id`. `hetzner_delete_node` iterates all servers (`client.servers.get_all()`) via `find_srv` to find the matching IP — an O(n) scan that adds latency proportional to project size and depends on fragile IP matching.

The Hetzner API `servers.create()` response already returns a `server` object with a numeric `.id` field. The SDK provides `client.servers.get_by_id(id)` for O(1) server resolution.

## Goals / Non-Goals

**Goals:**
- Hetzner `create_node` stores `str(server.id)` as `external_id` instead of the VM's IP address
- Hetzner `delete_node` resolves the server via `client.servers.get_by_id(int(external_id))` — O(1), no server list scan
- `find_srv` function removed (no longer needed)
- Unit and e2e tests updated for the new external_id semantics

**Non-Goals:**
- No changes to `CloudCreateNodeDTO`, `DeleteNodeCallable` protocol, `CloudAdapter`, `manager.py`, domain `Node` model, or DB schema
- No changes to other cloud providers (Azure, UpCloud, VastAI continue with IP-as-external_id)
- No new abstractions or helpers — the change is purely internal to `hetzner.py`

## Decisions

### Server resolution: `get_by_id` over direct `BoundServer` construction

Selected approach: `client.servers.get_by_id(int(external_id))` returns `BoundServer | None`; if found, call `.delete()`. This provides an explicit existence check with the same not-found logging as the current code (`"NODE %s NOT DELETED AS UNKNOWN"`).

Rejected alternative: constructing `BoundServer(id=int(external_id), client=client)` directly and calling `.delete()` skips the existence check and would raise an unhandled `APIException` for non-existent servers.

### Data mapping

`create_node` returns `CloudCreateNodeDTO(external_id=str(server.id), hostname=ip_str, ...)`. The `hostname` stays the IP — it is the SSH connection address. `external_id` becomes the provider-native resource identifier, enabling direct O(1) deletion.

### Test strategy

- **Unit tests** (`test_cloud_provider_create_delete.py`): mock `server.id` on create; mock `client.servers.get_by_id` returning a `BoundServer` mock on delete, assert `.delete()` was called
- **E2E tests** (`test_hetzner_live.py`): cleanup helpers use `client.servers.get_by_id(server_id)` instead of `find_srv(client, ip)`; tracked server IDs replace IPs as the deletion identity while IP tracking remains for scenario assertions

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Stale IP-string `external_id` in DB (from before the change) causes `int(ip_str)` to succeed but `get_by_id(ip_int)` returns 404 (not a valid Hetzner server ID) | Pre-deployment requirement: drain all existing Hetzner VMs. No DB migration needed — stale values produce the same no-op log as any not-found server |
| `int(external_id)` raises `ValueError` on non-numeric input (stale IP-string) | Caught with try/except — logs `"NODE %s NOT DELETED AS UNKNOWN"` and returns, same as any server-not-found condition. Pre-deployment drain ensures this path never triggers in normal operation |
| `server.delete()` API call fails | Exception propagates through `loop.run_in_executor` and `hetzner_delete_node` — same failure behavior as current code |

### Performance

Removes the O(n) `client.servers.get_all()` call from every deallocation, replacing it with O(1) `client.servers.get_by_id()`. For projects with many Hetzner servers, this eliminates a linear scan on every VM teardown.

### Observability

All existing log markers preserved unchanged: `"CREATED %s"`, `"DELETED %s"`, `"NODE %s NOT DELETED AS UNKNOWN"`. No new log lines added.
