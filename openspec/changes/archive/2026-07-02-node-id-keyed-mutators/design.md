## Context

`add-node-id-identity` (archived 2026-07-02) introduced `node_id SERIAL PRIMARY KEY` on `yascheduler_nodes` and a `NodeId` value object, carrying `node_id` alongside `ip` without replacing ip-keyed identification. Its non-goals listed "switching `update/remove/enable/disable` to `WHERE node_id =`" as a plausible follow-up. This is that follow-up, scoped to the mutator surface only.

Current state: every `NodeRepository` mutator (`enable`, `disable`, `remove`, `update`) runs `WHERE ip = :ip`. `ip VARCHAR(15) UNIQUE` is still present as a guard. Every application call-site that invokes a mutator already holds a `Node` (hence `node.node_id`), except two tmp-cleanup paths in `allocate_task` which carry only a `tmp_ip: str`. The `add_tmp` method returns a fake-ip placeholder (`'prov'||MD5(...)`) and is explicitly out of scope here.

Constraints: pg8000 cannot adapt a `NodeId` dataclass to a SQL param — the bare `int` must be passed (precedent: `get_by_id` passes `node_id.value`). The SSH layer (`connect`/`disconnect`/`get_session`/`contains`) keys on ip because ip is the dial address — out of scope. `Task.allocated_ip` and `TaskRepository.list_ids_by_ip_and_status(ip, …)` are out of scope (Surface C, schema + events).

## Goals / Non-Goals

**Goals:**
- Switch `NodeRepository.enable`/`disable`/`remove`/`update` from ip-keying to `node_id`-keying (Protocol, Impl, SQL).
- Update all call-sites to pass `NodeId`.
- Establish the `node_id`-keyed mutator pattern for follow-up changes (lookups, SSH, Task binding, add_tmp removal).
- Keep the change isolated: no schema migration, no SSH-layer change, no Task-schema change, no `add_tmp` change.

**Non-Goals:**
- `add_tmp` signature / `insert_tmp.sql` fake-ip / `"." in ip` echo-filters → separate change `remove-tmp-node-fake-ip`.
- `get` / `get_by_ips` / `list_*` lookup methods → Surface B-3 (s coupled to ip-keyed queues in orchestrator).
- SSH layer `connect`/`disconnect`/`get_session`/`contains` → Surface A (ip = transport address).
- `Task.allocated_ip`, `TaskAllocated.node_ip`, `TaskRepository.list_ids_by_ip_and_status` → Surface C.
- `CloudProvisioner.deallocate(cloud, ip)` → ip is the cloud host, not identity.
- `ip UNIQUE` constraint → stays as guard during the transition window.
- CLI user-facing output → stays ip-only (operators read ip, not node_id).

## Decisions

### D1: `remove` moves to `node_id` fully; tmp-cleanup gets a `get` lookup

**Choice:** `remove(node_id: NodeId)` for all call-sites. The two tmp-cleanup paths (`_cleanup_tmp_node_best_effort`, `_persist_node_with_cleanup`) add `uow.nodes.get(tmp_ip)` before `remove(node.node_id)`.

**Alternatives considered:**
- *A1: `remove` stays ip-keyed, only `enable`/`disable` move (variant b from explore).* Rejected — leaves `remove` asymmetric, and the rationale ("tmp-cleanup has no Node") is a localized consequence of the `add_tmp` fake-ip workaround that is itself slated for removal. A `get` lookup in two best-effort paths is cheaper than carrying the asymmetry forward.
- *A2: `Union[str, NodeId]` on `remove`.* Rejected — erodes the type-safety that is the point of the change.

**Why:** Symmetry across all four mutators. The tmp-cleanup paths are best-effort (`try/except` with logged failures), the tmp-node was just inserted with a unique MD5-placeholder ip, and `get` returning `None` (row already gone) is handled by skipping `remove` — matching current no-op-on-0-rows behavior. No TOCTOU risk in practice.

### D2: `manage_node` helpers take `Node`, not `(node_id, ip)`

**Choice:** `_remove_node_hard(deps, node: Node)` / `_remove_node_soft(deps, node: Node)`. Validation UoW resolves the `Node` early (via `get_by_id` on the node_id path, via `get(spec.host)` on the host_spec path) and passes it down.

**Alternatives considered:**
- *A1: `(deps, node_id: NodeId, ip: str)` pair.* Rejected — two keys risk desynchronization; validation already has the `Node`.
- *A2: helpers do their own `get`/`get_by_id` inside the mutating UoW.* Rejected — doubles the queries; validation already fetched the row.

**Why:** Single object, no desync. `node.ip` remains available for `tasks.list_ids_by_ip_and_status(ip, RUNNING)` (Surface C, unchanged) and user-facing logs. The CLI public surface (`_parse_node_args`, `NodeTarget`, argparse, exit codes) is untouched — only private helper signatures change.

### D3: `update(node: Node)` — signature unchanged, SQL key changes

**Choice:** `update(node: Node)` keeps its signature (already takes `Node`, which carries `node_id`). Only the SQL `WHERE ip = :ip → WHERE node_id = :node_id` and the `_run` param (`node_id=node.node_id.value`) change.

**Why:** Free — no call-site changes (there are no call-sites today; `uow.nodes.update` is unused in app and tests). Included for mutator-surface completeness.

### D4: SQL param passes `node_id.value`, not `NodeId`

**Choice:** `_run(…, node_id=node_id.value)` in all four mutators.

**Why:** pg8000 cannot adapt a `NodeId` dataclass. Same pattern as the existing `get_by_id` (established in `add-node-id-identity`). No new precedent.

### D5: Internal logs gain `node_id=%s` alongside `ip=%s`; user-facing CLI stays ip-only

**Choice:** `deallocate_node` and `abandon_node` log lines add `node_id=%s` next to the existing `ip=%s`. `manage_node` user-facing `print(...)` output keeps ip only.

**Why:** Internal logs serve debugging — both identifiers are useful (node_id for correlation, ip for reachability). CLI output serves the operator, who knows nodes by ip; node_id is not meaningful there.

### D6: No rowcount check on `remove` after the tmp-cleanup lookup

**Choice:** If `get(tmp_ip)` returns `None`, skip `remove`. If it returns a `Node`, call `remove(node.node_id)`. Do NOT assert a row was deleted.

**Why:** Current `remove` is no-op on 0 rows (no rowcount check). Adding one now would change behavior and isn't required — the lookup's purpose is to obtain `node_id`, not to guard deletion.

### D7: No DB migration

**Choice:** No new migration file. `node_id SERIAL PRIMARY KEY` exists (migration `002_add_node_id.sql`). Only SQL query text changes.

**Why:** Additive — the column and PK are already in place.

## Ris / Trade-offs

- **[Risk] tmp-cleanup `get` returns `None` under concurrent removal** → Mitigation: skip `remove`, log nothing extra. The path is best-effort and already swallows exceptions. The tmp-node's ip is a unique MD5 placeholder; concurrent removal only happens if a prior cleanup already ran, in which case skipping is correct.
- **[Risk] `ip UNIQUE` constraint stays, allowing a latent dual-keying ambiguity if a future change relaxes it before all ip-keyed lookups migrate** → Mitigation: the constraint is an explicit non-goal to remove in this change; it stays as a guard. The follow-up sequence (B-3 lookups → A SSH → C Task) must complete before `ip UNIQUE` is dropped.
- **[Risk] Test churn (8 unit asserts + 2 integration calls + StubNodeRepository)** → Mitigation: expected cost of changing a signature; tests reflect the new contract rather than papering over it. The `NodeId` value is constructible in tests via `NodeId(<int>)`.
- **[Trade-off] `manage_node` helpers now take `Node`, slightly widening the validation-UoW-to-helper coupling** → Accepted: the validation UoW already fetched the row; passing the result down is cheaper than re-fetching.

## Migration Plan

No schema migration. Deployment is a code-only release:

1. Merge code changes (Protocol, Impl, SQL, call-sites, tests).
2. Deploy — existing rows keep their `node_id` (SERIAL-assigned in migration 002); mutators now `WHERE node_id =`.
3. Rollback: revert the code release; `WHERE ip =` returns. `ip UNIQUE` is intact throughout, so ip-keyed behavior is unchanged on rollback.

## Open Questions

None — all resolved during explore (see explore-brief.md "Open questions" section, items 1–10).