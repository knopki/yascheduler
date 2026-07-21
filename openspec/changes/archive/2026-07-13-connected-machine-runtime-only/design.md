## Context

`ConnectedMachine` is the runtime-only entity representing a connected machine — the domain face of `SSHMachineSession`. It is constructed exactly once, in `SSHMachineRepository.connect` (repository.py:232-239), from values that already exist on the `Node` parameter or are runtime-discovered in `connect`. It is never persisted.

Today's shape:

```python
@dataclass(frozen=True)
class ConnectedMachine:
    node_id: NodeId       # identity back-reference to Node
    hostname: str         # copy of node.hostname set at connect
    platform: str         # runtime-discovered (the only genuinely-runtime field)
    ncpus: int            # runtime-discovered, also propagated to Node.ncpus
    state: MachineState
    free_since: float | None
```

Field-by-field production-read audit (per the exploration that motivated this change):

| Field | Production readers | Notes |
|---|---|---|
| `node_id` | allocator, disconnect, orchestrator idle-map | Genuine identity back-reference. Kept. |
| `hostname` | exactly 1: `occupy()` → `MachineBusyError(self.node_id, self.hostname)`. The exception is never caught in production; its `.hostname` attribute is never read programmatically. | Pure copy of `node.hostname`. Drop. |
| `platform` | `is_compatible(engine.platforms)`, `list_free(platforms)` filter | Genuinely runtime-discovered (not on `Node`). Kept. |
| `ncpus` | exactly 1: `setup_node` logs `"CPUs count: %s" % self._machine.ncpus`. After cloud setup the same value is on `Node.ncpus`. | Copy of a runtime-discovered value that propagates back to `Node`. Drop. |
| `state` | `is_compatible`, `list_free`, allocator | Core runtime state. Kept. |
| `free_since` | `list_free` sort key, idle-detection | Core runtime state. Kept. |

The `"CPUs count: %s"` log line in `SSHMachineSession.setup_node` is functionally misplaced: `setup_node` installs engine packages; the CPU count is unrelated. Discovery happens earlier — `SSHMachineRepository.connect` reads `ncpus = await adapter.get_cpu_cores(...)` at repository.py:231. Moving the log to its discovery site both enables dropping `ConnectedMachine.ncpus` and fixes the placement.

Constraints inherited from the project:

- Public surface stability for `class Yascheduler`, CLI syntax, INI, DB schema — all preserved. `ConnectedMachine` and `MachineBusyError` are domain-layer constructs whose construction is contained to one production site each.
- This change is INDEPENDENT of `node-owns-connection-identity` — either can land first. If both land, no merge conflicts (different files, different fields).

## Goals / Non-Goals

**Goals:**

- `ConnectedMachine` slims to `node_id`, `platform`, `state`, `free_since` — four fields, all genuinely runtime or genuinely identity.
- `MachineBusyError` loses its `hostname` parameter (it carried an attribute nobody read).
- The `"CPUs count: %s"` log moves to its discovery site (`SSHMachineRepository.connect` after `adapter.get_cpu_cores(...)`), away from `SSHMachineSession.setup_node` where it had no functional relationship to the operation.

**Non-Goals:**

- `MachineConnectionError` is UNCHANGED. Its `hostname` comes from `node.hostname` at the connect failure site (where the machine does not exist yet — connect failed). Operators recognize the address in connection-failure messages.
- `SSHMachineSession.hostname` is UNCHANGED. It is the transport-echo used by ~11 operator-facing log lines in `infra/ssh/operations/*`. It stays sourced from `node.hostname` at session construction.
- `Node.ncpus` persistence asymmetry for static nodes (where `Node.ncpus` stays `0` and the orchestrator lazily re-discovers via `session.get_cpu_cores()`) is NOT addressed here. Separate concern; tracked as a potential follow-up.
- No changes to `Node` fields, `connect` signature, or DB schema — those belong to `node-owns-connection-identity` and other possible changes.

## Decisions

### D1: Drop `hostname` and `ncpus` from `ConnectedMachine` together

Both fields share the same shape: a value copied from `Node` (or runtime-discovered and then propagated to `Node`) at connect time, frozen, never updated, with exactly one production reader each (and that reader is either a never-caught exception or a misplaced log). Dropping one without the other leaves half the dead weight.

**Alternative considered:** drop only `hostname` (it is the more clearly dead — `ncpus` at least flows to `Node`). Rejected: half-measure; both fields fail the same "genuinely-runtime-or-identity" test.

### D2: `MachineBusyError` signature drops `hostname`

```python
class MachineBusyError(DomainError):
    def __init__(self, node_id: NodeId) -> None:
        self.node_id = node_id
        super().__init__(f"machine ({node_id}) is busy")
```

The `hostname` attribute is removed. The message loses the `"at {hostname}"` segment.

**Why drop rather than keep:** the exception is raised in exactly one site (`ConnectedMachine.occupy`), caught in zero production sites, and its `.hostname` attribute is read programmatically in zero sites. The `.node_id` attribute remains the identity handle. Operators debugging a "machine busy" condition use `node_id` to look up the node (and its `hostname`) in the DB or via `yanodes`.

**Alternative considered:** keep the attribute, populate it from a repository/Node lookup at raise time. Rejected: `ConnectedMachine.occupy()` is a pure dataclass method with no DI'd access to a repository. Threading a lookup into `occupy()` would violate the frozen-dataclass purity and couple domain to persistence.

**Alternative considered:** keep `MachineBusyError(node_id, hostname)` and source `hostname` from the session at raise time. Rejected for the same DI-purity reason — `occupy()` is on the dataclass, not on the session. The session could intercept and re-wrap, but that adds an orchestration layer for an exception nobody catches.

### D3: `MachineConnectionError` is UNCHANGED

The exception is raised at `SSHMachineRepository.connect:187` from `node.hostname` — at that point `ConnectedMachine` does not exist (the connect failed, so no machine was constructed). The exception's `hostname` is the transport address the operator recognizes; it flows through the orchestrator's connect-machine loop log lines (orchestrator.py:309, 325, 338, 354). Removing it would degrade operator-facing diagnostics with no compensating simplification.

This decision is called out explicitly because the two exceptions look symmetric and a careless implementer might "clean up" both. The asymmetry is intentional: `MachineBusyError.hostname` came from a domain entity (dead weight); `MachineConnectionError.hostname` comes from a Node field at a transport failure site (live).

### D4: Move `"CPUs count: %s"` log to discovery site

Current:
```python
# repository.py:231 (discovery)
ncpus = await adapter.get_cpu_cores(make_run_fn(conn, adapter))
machine = ConnectedMachine(node_id=..., hostname=..., platform=..., ncpus=ncpus, ...)

# session.py:243 (log, in setup_node — unrelated operation)
self._log.info("CPUs count: %s", self._machine.ncpus)
```

Proposed:
```python
# repository.py:231 (discovery + log together)
ncpus = await adapter.get_cpu_cores(make_run_fn(conn, adapter))
self._log.info("[SSHRepository][connect][CPUS] hostname=%s ncpus=%d", node.hostname, ncpus)
machine = ConnectedMachine(node_id=..., platform=..., ...)

# session.py:243 — log line REMOVED
```

**Why at discovery:** the log declares "this is what we found about this machine at connect time." That is a connect-phase statement, not a setup-node-phase statement. Co-locating the log with the discovery makes the connect block self-describing and lets `setup_node` focus on engine-package installation.

**Why include `hostname` in the log line:** operator-facing logs use the address the operator recognizes. `node.hostname` is available in the connect scope; no need to reach into `ConnectedMachine` for it.

**Alternative considered:** drop the log entirely. Rejected — the CPU count is operator-relevant signal (e.g. mis-sized VM, unexpected CPU pinning). Keeping the information, just at the right call site.

### D5: `SSHMachineSession.hostname` stays, sourced from `node.hostname`

The session keeps its `_hostname` field (session.py:98), populated from `node.hostname` at construction (repository.py:243). The ~11 log lines in `infra/ssh/operations/*.py` that read `session.hostname` continue to work unchanged.

After this change, the runtime layer has exactly one hostname copy (`SSHMachineSession._hostname`) and the domain layer has zero hostname copies on `ConnectedMachine`. The domain identity copy stays where it always was — on `Node.hostname`.

### D6: Ordering relative to `node-owns-connection-identity`

The two changes touch disjoint surfaces:

| This change | `node-owns-connection-identity` |
|---|---|
| `ConnectedMachine` field list | `Node.jump_*` semantics |
| `MachineBusyError` signature | `MachineRepository.connect` signature |
| Log line relocation | `_resolve_tunnel` → `_build_tunnel_options` |
| `SSHMachineRepository.connect` construction of `ConnectedMachine` | `SSHMachineRepository.connect` kwargs |

The one shared file is `SSHMachineRepository.connect` (repository.py). Both changes edit its body — one touches the `ConnectedMachine(...)` construction kwargs, the other touches the `_open_connection(...)` / `connect(...)` signatures. They are in different parts of the method and will merge cleanly regardless of land order.

If `node-owns-connection-identity` lands first, this change's `ConnectedMachine(node_id=..., platform=...)` construction call drops `hostname=` / `ncpus=` — a simple kwarg deletion. If this change lands first, `node-owns-connection-identity` proceeds as written. Tasks should note the merge-order independence explicitly. The tasks.md front-matter for section 1 calls this out.

## Risks / Trade-offs

**[Risk] External consumers construct `ConnectedMachine` directly** → The entity is re-exported from `yascheduler.domain`. The AiiDA scheduler plugin and Python client (`yascheduler.client`) are audited in the tasks phase; if either constructs `ConnectedMachine`, it breaks. Mitigation: the audit task is explicit in tasks.md. Probability: low — `ConnectedMachine` is an internal domain entity not part of the documented `class Yascheduler` public API surface.

**[Risk] Log-grep / alerting rules match the old `"at {hostname} is busy"` pattern** → Low probability (`MachineBusyError` is rarely raised — the orchestrator's allocator prevents double-occupy), but documented in the proposal's Impact section. Mitigation: the message text change is called out as operator-visible.

**[Risk] The `"CPUs count: %s"` log relocation confuses operators** → The log now appears at connect rather than at setup_node. For cloud nodes, `setup_node` runs immediately after connect inside `_setup_vm`, so the log order changes only slightly. For static nodes added via `yasetnode`, the log moves from "Setup host..." phase to the connect-before-setup phase. Net effect: the line appears slightly earlier in the log stream.

**[Trade-off] `MachineBusyError` loses diagnostic context in its message** → Operators seeing the exception now see `machine (NodeId(7)) is busy` instead of `machine (NodeId(7)) at 10.0.0.1 is busy`. Acceptable: `node_id` is the stable identity; `hostname` is a mutable transport attribute. Operators can resolve `node_id` → `hostname` via `yanodes`. Keeping the message minimal avoids embedding stale addresses in exceptions (e.g. if the node was re-resolved between connect and the double-occupy attempt).

**[Trade-off] The "two `ConnectedMachine` with the same `hostname` but different `node_id`" spec paragraph is removed** → This paragraph existed to justify why `hostname` was on the entity but was not the identity. With `hostname` removed, the paragraph has no referent. The dup-hostname configuration (which the paragraph described) still works — it is now an emergent property of `node_id` being the sole identity, not a spec'd invariant of `ConnectedMachine`.
