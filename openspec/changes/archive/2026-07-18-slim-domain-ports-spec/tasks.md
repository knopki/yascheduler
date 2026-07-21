## 1. Trim domain-ports spec

- [x] 1.1 Replace `openspec/specs/domain-ports/spec.md` Purpose with a WHY statement (why these ports exist as abstract contracts), not a WHAT list of Protocol names
- [x] 1.2 Per Requirement: collapse duplicate signature restatements to a single SHALL line; drop "unchanged in signature" historical notes; drop `int`/`TaskId` facade-boundary prose (lives in `package-facades`)
- [x] 1.3 TaskRepository Requirement: drop "sole NewTask → Task conversion site" rationale (relocates to markup); drop Yascheduler facade paragraph; retain SHALL signatures + the two existing scenarios
- [x] 1.4 NodeRepository Requirement: drop hostname-keyed-vs-NodeId migration narrative, "Protocol defines no add_tmp method" paragraph, tmp-reservation flow prose (belongs in `use-cases`); retain one SHALL line, `NodeId`-keyed invariant, `list_all` ordering, and the three existing scenarios
- [x] 1.5 MachineRepository/MachineSession Requirement: drop "former MachineOperations Protocol is REMOVED" historical paragraph, drop "Application-layer consumers SHALL type against MachineRepository" (consumer-side concern); retain Protocol-listing + cross-reference to `ssh-infrastructure` + the one existing scenario
- [x] 1.6 CloudConfig Requirement: unchanged in substance (already minimal); keep as is
- [x] 1.7 CloudProvisioner Requirement: convert narrative into tight SHALL statements — `allocate` reuses `node_id` AND sets `hostname`/`external_id`; `deallocate` no-op on `cloud is None`; `select_provider` does no I/O and returns `None` on no-capacity / locked-semaphore; drop the `capacity() not part of port` and `No ProviderSelection value object` rationales (relocate to markup); retain behavioral scenarios, add explicit "deallocate on cloud=None is a no-op" scenario

## 2. Enrich ports.py CLASS_* contracts

For every change in this group: edit only the contract comment block; do NOT touch code or signatures. Existing CLASS_* regions already wrap the entire class — keep that invariant. `PURPOSE` must answer WHY (what the port enables), not WHAT (a list of methods).

- [x] 2.1 MODULE_CONTRACT: tighten PURPOSE to WHY; add `INVARIANTS` (all ports are `typing.Protocol`; methods async unless noted; `@runtime_checkable`); keep existing SCOPE/KEYWORDS
- [x] 2.2 `CLASS_TaskRepository`: tighten PURPOSE to WHY; add `INVARIANTS` (keyed on `TaskId` end-to-end; `@runtime_checkable`); add `RATIONALE` Q/A — Q: why is `insert` the sole `NewTask → Task` conversion site? A: centralizing it in one repository method guarantees every `Task` carries a DB-generated `TaskId`, eliminating partial-init paths at multiple construction sites
- [x] 2.3 `CLASS_NodeRepository`: tighten PURPOSE to WHY; add `INVARIANTS` (lookups and mutators keyed on `NodeId`; `list_all` ordered by `node_id` ascending; `@runtime_checkable`); add `RATIONALE` Q/A — Q: why no `add_tmp` / hostname-keyed methods on the Protocol? A: a single `insert(NewNode) -> Node` covers both real and tmp-node insertion, and `NodeId` is the canonical allocation identity; hostname-keyed lookups were removed when `ip` was dropped from the task schema (migration 009)
- [x] 2.4 `CLASS_CloudConfig`: tighten PURPOSE to WHY; keep existing INVARIANTS (structural PEP 544 satisfaction); cross-reference `cloud` spec for field list
- [x] 2.5 `CLASS_MachineSession`: tighten PURPOSE to WHY; keep existing INVARIANTS; add `RATIONALE` Q/A — Q: why does the Protocol split collection lifecycle (`MachineRepository`) from the per-session handle (`MachineSession`)? A: so callers operate on a stable per-call handle while the repository owns connection pooling and teardown; the former facade `MachineOperations` was removed in favor of invoking collaborators directly on the session every caller already holds
- [x] 2.6 `CLASS_MachineRepository`: tighten PURPOSE to WHY; add `INVARIANTS` (`connect`/`list_free`/`list_connected`/`get_session` return `MachineSession`; `@runtime_checkable`)
- [x] 2.7 `CLASS_CloudProvisioner`: tighten PURPOSE to WHY; add `INVARIANTS` (`allocate`/`deallocate` async; `select_provider`/`stop` semantics); add `RATIONALE` Q/A covering: (a) why `allocate` reuses the passed `node_id` (one row per cloud allocation lifecycle, not two); (b) why `select_provider` returns a bare `str` instead of a `ProviderSelection` value object (the application treats it as an opaque identity and passes it back unchanged); (c) why `capacity()` is not on the port (capacity counting is an orchestrator/use-case concern, not an adapter concern)

## 3. Add METHOD_* regions on non-trivial port methods

Each METHOD_* region MUST wrap the entire method (decorator → body `...` → trailing blank line before `# endregion`), not just the contract comment. Apply only to methods whose contract carries information beyond the docstring. Skip trivial accessors and one-line Protocol stubs whose docstring already fully states the contract. Fields allowed on METHOD: `PURPOSE` (required, WHY), `REQUIRES`, `ENSURES`, `RATIONALE` (Q/A), `INVARIANTS`, `SCOPE`. Do NOT invent new field names (no `SHALL NOT:`, no `EFFECTS:`, etc.).

- [x] 3.1 `TaskRepository.insert` — METHOD region; `PURPOSE` (WHY: persist a new task and surface the DB-generated identity); `ENSURES` (returned `Task.task_id` is DB-generated and `> 0`); `RATIONALE` Q/A (sole `NewTask → Task` conversion site)
- [x] 3.2 `NodeRepository.insert` — METHOD region; `PURPOSE` (WHY: persist a new node — real or tmp-reservation — and surface the DB-generated `NodeId`); `ENSURES` (returned `Node.node_id` is DB-generated and `> 0`); `RATIONALE` Q/A (same method serves the tmp-reservation flow: `insert(NewNode(cloud=..., enabled=False))` returns the `Node` whose `node_id` is the cleanup handle and reuse identity)
- [x] 3.3 `CloudProvisioner.allocate` — METHOD region; `PURPOSE` (WHY: provision a cloud VM and return a `Node` carrying its real connection identity); `REQUIRES` (`provider` was returned by `select_provider`; `node` already persisted as the tmp-row); `ENSURES` (returned `Node.node_id == node.node_id`; `hostname` and `external_id` both set to the cloud-provisioned address; `enabled=True`; no DB write inside the adapter)
- [x] 3.4 `CloudProvisioner.deallocate` — METHOD region; `PURPOSE` (WHY: release the cloud VM tied to a node, identified by its provider name and cloud host); `REQUIRES` (`node.cloud` and `node.hostname` are read internally; caller passes the same `Node` returned by `allocate`); `ENSURES` (when `node.cloud is None`, logs and returns without deletion)
- [x] 3.5 `CloudProvisioner.select_provider` — METHOD region; `PURPOSE` (WHY: pick the highest-priority provider with capacity and platform support, without blocking on I/O); `REQUIRES` (called before `allocate`; `platforms` is the task's required-platform list); `ENSURES` (returns the provider name as a bare `str`, or `None` when no capacity or the selected provider's op semaphore is locked); `INVARIANTS` (sync; performs no I/O; no DB access)

## 4. Verify

- [x] 4.1 `openspec validate slim-domain-ports-spec --json` passes
- [x] 4.2 `openspec validate --all --json` does not regress (still 20 specs passing; this change + the in-flight `hetzner-server-id-external-id` are the only change items)
- [x] 4.3 `uv run ruff check yascheduler/domain/ports.py` clean
- [x] 4.4 `uv run ruff format --check yascheduler/domain/ports.py` clean
- [x] 4.5 `uv run lint-imports` clean for `yascheduler/domain/ports.py`
- [x] 4.6 Existing port-conformance tests pass unchanged: `uv run pytest -m unit` for any test importing `yascheduler.domain.ports`
- [x] 4.7 Manual scan: every `# region CLASS_*` and `# region METHOD_*` has a paired `# endregion` and wraps the entire entity (no orphaned trailing code outside the region); no invented GRACE fields present; every `PURPOSE` answers WHY
