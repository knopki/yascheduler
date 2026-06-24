## Context

`ProviderSelection(name: str, username: str)` was introduced by the archived `cloud-provisioner-pure` change as a primitive-only domain value object returned by `CloudProvisioner.select_provider`. The intent was to keep `CloudAdapter` / `ConfigCloud` types from crossing the port boundary while still giving the application layer a typed handle to the selected provider.

Two properties have eroded that intent:

1. **`username` is dead data.** `allocate_task` passes `selection.username` to `uow.nodes.add_tmp`, which writes it into a tmp-node row (`enabled=FALSE`). The tmp-node is deleted (`uow.nodes.remove(tmp_ip)`) before any reader ever SELECTs it back. The real `Node.username` is re-derived independently inside `CloudProvisionerImpl._setup_vm` from `config.username` (`manager.py:367`), not from the tmp row. Both values derive from the same `ConfigCloud` so they coincide — but the coincidence is incidental, not load-bearing. The original author flagged this with `# FIXME: username is useless` at `model.py:436` and `# FIXME: very smelly object: remove?` at `model.py:433`.

2. **After removing `username`, the object is a one-field wrapper.** The only consumer (`allocate_task.py:255-256`) immediately destructures it: `selected_name = selection.name`. A value object that exists only to be unwrapped at the call site earns no weight.

The existing port convention across `NodeRepository` is identity strings in, domain objects out (`add_tmp(cloud: str)`, `get(ip: str)`, `remove(ip: str)`, `enable(ip: str)`, `disable(ip: str)`). `CloudProvisioner` already follows this convention for `allocate(provider: str)` and `deallocate(cloud: str, ip: str)`. Only `select_provider` deviates by returning a value object instead of a string. This change brings it into symmetry.

## Goals / Non-Goals

**Goals:**
- Remove `ProviderSelection` value object from the domain model.
- Change `CloudProvisioner.select_provider` return type from `ProviderSelection | None` to `str | None`.
- Remove the `username` parameter from `NodeRepository.add_tmp` and `PostgresNodeRepository.add_tmp`; `insert_tmp.sql` stops binding `:username`.
- Update all tests, contracts, and GRACE knowledge-graph annotations touched by the above.
- Keep `yascheduler_nodes.username` DB column and its `DEFAULT 'root'` intact (no schema change, no migration).

**Non-Goals:**
- Do not introduce a replacement domain type (e.g., `CloudProviderHandle`, `SelectedProvider`) to carry the adapter or its config across the port. Explore concluded this would only eliminate re-resolve on 1 of 3 `CloudProvisioner` call paths (the in-memory `select→allocate` path); the other 2 paths (`deallocate_nodes` from DB state, `persist-failed` cleanup from `node.cloud`) are forced to accept strings because the DB stores strings. The current port convention is consistent; breaking it for a 1/3 win is not worth the asymmetry.
- Do not eliminate the `dict.get` re-resolve inside `CloudProvisionerImpl.allocate` / `deallocate`. It is O(1) on a path dominated by SSH/cloud-API round-trips; the cost is cognitive, not runtime.
- Do not touch `Node.username` (the real node's username), `_setup_vm`, or any SSH connection logic. The real username flow (`config.username` → `Node(username=config.username)` → `orchestrator._gateway.connect(username=node.username)`) is independent of the selection and is not affected.
- Do not change `yascheduler_nodes.username` schema, do not add a migration. The `schema-migrations` in-progress change owns schema work; this change explicitly leaves the column and its default alone.

## Decisions

### D1 — Collapse to `str | None`, do not replace with a new domain type

**Choice.** `CloudProvisioner.select_provider(...) -> str | None`. Delete `ProviderSelection`.

**Why over alternatives.**

| Alternative | Rejected because |
|---|---|
| Keep `ProviderSelection` for future extensibility (priority, selection reason, capacity snapshot) | Speculative. No near-term field is load-bearing. AGENTS.md emphasizes YAGNI ("Prefer minimal changes", "Do not add compatibility layers without a concrete need"). Adding fields without a consumer is the kind of speculative abstraction the project ruleset rejects. |
| Replace with `CloudProviderHandle` Domain Protocol that the infra `CloudAdapter` implements, so `allocate(handle)` / `deallocate(handle)` skip the dict lookup | Eliminates re-resolve on only 1 of 3 call paths. `deallocate_nodes` reads `node.cloud: str` from DB; `persist-failed` cleanup derives `cloud_name = node.cloud or selected_name`. Both are forced to construct a handle from a string before calling the port, which moves the `dict.get` rather than removing it. Also breaks the symmetry of the port (`allocate(handle)` + `deallocate(str)`), inconsistent with `NodeRepository`'s identity-string convention. |
| Keep `ProviderSelection`, drop only `username` | Leaves a one-field wrapper that is immediately destructured at its only call site. Pure overhead. |

### D2 — Drop `username` from `add_tmp`; rely on DB `DEFAULT 'root'`

**Choice.** `NodeRepository.add_tmp(cloud: str) -> str`. `insert_tmp.sql` becomes `INSERT INTO yascheduler_nodes (ip, enabled, cloud) VALUES (...) RETURNING ip;`. The `username` column retains its `DEFAULT 'root'` (schema.sql:4 and the `ALTER TABLE ... ADD COLUMN IF NOT EXISTS username ... DEFAULT 'root'` at schema.sql:18-19), so the row gets `username='root'` automatically.

**Why.** The `username` value written by the current `add_tmp` is never read back. The tmp-row is a placeholder with `enabled=FALSE` that exists only to reserve an IP and block concurrent allocators from over-counting capacity. It is removed (`uow.nodes.remove(tmp_ip)`) in every flow branch — success (`_persist_node_with_cleanup`), cloud-alloc failure (`_cleanup_tmp_node_best_effort`), and persist failure (`_cleanup_tmp_node_best_effort` + `clouds.deallocate`). No code path SELECTs the tmp-row's `username`. The real `Node` is constructed in `_setup_vm` with `username=config.username` and persisted via `uow.nodes.add(node)`, which uses `node/insert.sql` (a different query that does bind `:username` from the `Node` object).

**Migration / rollback.** None needed. The DB column is untouched. Reverting the change is a code-only revert: restore the `username` parameter to `add_tmp`, restore `:username` binding in `insert_tmp.sql`, restore `ProviderSelection`. No data has to move.

### D3 — `CloudProvisionerImpl.select_provider` returns `adapter.name` directly

**Choice.** Body changes from:

```python
config = self.configs[adapter.name]
return ProviderSelection(name=adapter.name, username=config.username)
```

to:

```python
return adapter.name
```

The throttle-check block (`adapter.get_op_semaphore().locked()` → return `None`) is unchanged. The `select_provider_pure` call is unchanged. The `config = self.configs[adapter.name]` lookup is removed — it was only used to pull `username`, which is no longer needed at this layer.

### D4 — Atomic single change, not split A/B

**Choice.** Ship the `username` removal (A) and the `ProviderSelection` collapse (B) as one change.

**Why.** They form one coupled chain: `ProviderSelection.username` is the only consumer of `add_tmp`'s `username` parameter. Remove the field → the call site `add_tmp(selected_name, selection.username)` loses its argument → `add_tmp`'s signature shrinks. Splitting would create an intermediate state where `add_tmp(cloud, username="root")` accepts a parameter nobody passes — a strictly worse shape than either endpoint. Atomic is cleaner.

### D5 — GRACE knowledge-graph updates alongside code

**Choice.** In the same change:
- Remove `<export-ProviderSelection>` (lives in **M-DOMAIN**, the `domain/__init__.py` re-export block).
- Remove `<type-ProviderSelection>` (lives in **M-DOMAIN-MODEL**).
- Update `<class-CloudProvisioner ...>` annotation in M-DOMAIN-PORTS to reference `select_provider(...) -> str | None` instead of `... -> ProviderSelection | None`.
- Update `<fn-select_provider PURPOSE="...">` annotation in M-CLOUD-PROVISIONER to reference `str | None`.

Per GRACE rules, module contracts and module maps on all touched files get CHANGE_SUMMARY bumps.

## Risks / Trade-offs

- **[Risk] Future need for selection metadata** (e.g., priority, capacity snapshot for structured logs, selection reason for observability) → would require re-introducing a value object. **Mitigation:** the cost of re-introduction is small (one dataclass + signature change). Carrying speculative fields now is the bigger cost. If a concrete consumer emerges, a follow-up change can add a typed return at that point with full knowledge of what fields the consumer needs.

- **[Risk] Breaking change to a port type** → consumers of `ProviderSelection` (use-case, tests, infra) all need to move in lockstep. **Mitigation:** the blast radius is fully enumerated in proposal.md Impact; a single atomic change updates all consumers. The compiler/type-checker will flag any stragglers (`ProviderSelection` import fails after the class is removed).

- **[Risk] Tmp-row username semantics shift silently** → previously `add_tmp(cloud, "deployer")` could write `username='deployer'`; now it always writes `username='root'`. **Mitigation:** no code path reads the tmp-row's username. The one test that asserted `n.username == "deployer"` (`test_persistence_adapter.py`) was asserting a property of a row that is deleted in production before any reader sees it. The assertion is updated to `"root"`. The integration test `test_db_integration.py` already asserts `"root"` and is unaffected apart from dropping the argument.

- **[Trade-off] Loss of named return field** → callers write `selection` (a bare string) instead of `selection.name`. Slightly less self-documenting at the call site. **Mitigation:** the call site is one line, in one function, and the surrounding context (`select_provider` → `selected_name`) makes the intent clear. Consistent with how `NodeRepository.get(ip)` returns a `Node` and `list_all()` returns `list[Node]` but `add_tmp(cloud)` returns a bare `str` (the IP) — bare strings as identity returns are already idiomatic in this codebase.

## Migration Plan

No data migration. Deployment is a code rollout:

1. Merge code change (domain, infra, application, tests, SQL, GRACE graph).
2. Deploy. The `insert_tmp.sql` change takes effect on next daemon restart.
3. Existing tmp-rows (if any orphaned by a crash mid-allocate) retain whatever `username` they had; they will still be reaped by the next deallocate cycle. No data correctness issue.

**Rollback:** revert the commit. No DB state to restore. The `username` column default ensures forward compatibility in both directions.

## Open Questions

(none — all decisions resolved during explore)