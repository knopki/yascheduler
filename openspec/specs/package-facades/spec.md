## Purpose

Define the package-facade discipline for `yascheduler`: the static
import layering, the layer facades as the sole cross-layer public
surface, the public Python client's stable JSON contract, and the
backward-compatibility guarantees for downstream consumers.

## Requirements

### Requirement: Package layering

The system SHALL enforce the import direction
`entrypoints → infra → application → domain → shared` statically. The
`[tool.importlinter]` layers contract in `pyproject.toml` is the
authority for both direct and indirect imports, and `yascheduler.shared`
is the bottom layer that imports nothing from a higher `yascheduler`
layer.

#### Scenario: an import against the layer direction fails the build

- **WHEN** a module in a lower layer imports from a higher layer
- **THEN** the import linter reports a contract violation and the build fails

### Requirement: Layer facades as public surface

Each architectural layer SHALL expose its cross-layer public surface
through the layer facade only. The domain, application, and infra
facades SHALL re-export the entities, ports, use cases, and adapters
their consumers need. Symbols are added to a facade lazily — only when
an external consumer needs them — and an empty facade is valid.

#### Scenario: a consumer resolves a symbol through the layer facade

- **WHEN** an adapter or the composition root needs a symbol from another layer
- **THEN** the symbol resolves through that layer's facade, not through a deep submodule path

### Requirement: Yascheduler public client contract

The `Yascheduler` client SHALL expose queue methods to submit and query
tasks. `queue_submit_task` SHALL return the new task's identity as an
integer. The query methods (`queue_get_tasks`, `queue_get_task`) SHALL
return one mapping per matched task — a sequence for the list variant, a
single mapping or none for the single-task variant — with this stable
shape:

```json
{
  "task_id": <int>,
  "label": <str>,
  "status": <status enum member>,
  "metadata": { "engine": <str>, "...non-null typed fields...": ..., "...extra payload...": ... },
  "node": { "hostname": <str>, "port": <int>, "username": <str>, "cloud": <str|null>, "...": ... } | null
}
```

`task_id` is a bare integer (not the typed identity); `status` is the
task-status enum (not a bare integer). `metadata` is the flat dict of
the task's non-null typed fields merged with its extra payload. `node`
is null when the task has no allocated node; when present, the node
object is keyed by `hostname`. This contract is identical across the
package facade, the entrypoints facade, and the public client shim.

#### Scenario: a query returns the documented task shape

- **WHEN** a consumer queries an existing task through any `Yascheduler` facade
- **THEN** the returned mapping has exactly the top-level keys `task_id`, `label`, `status`, `metadata`, and `node`; `node` is null for an unallocated task, otherwise it carries `hostname` with the node's connection fields

### Requirement: Public API stability

The system SHALL preserve the existing public API surface across
changes. Backward-compatible extensions (new optional parameters, new
public symbols) are permitted; breaking changes (removing or
repositioning parameters, changing a return shape, removing an exported
symbol) SHALL be treated as a new capability requiring explicit spec
coverage.

#### Scenario: the public client resolves through the compat shim

- **WHEN** a downstream consumer imports the public client through the backward-compatibility shim
- **THEN** the symbol resolves without error

#### Scenario: the AiiDA scheduler plugin loads under its entry point

- **WHEN** the AiiDA scheduler plugin is discovered through its scheduler entry-point group
- **THEN** the entry point named `yascheduler` resolves to the plugin
