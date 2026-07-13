## Why

`Node.ncpus` has a split personality: the field is typed `int` with a magic `0` sentinel meaning "unknown / discover at spawn", but the codebase treats it inconsistently. Cloud nodes persist a runtime-discovered value into `Node.ncpus` once at provision time (`CloudProvisionerImpl._setup_vm` write-back), turning the field into a discovery cache. Static nodes added via `yasetnode` never persist the discovered value — `Node.ncpus` stays `0` forever, and the orchestrator re-disovers it via `session.get_cpu_cores()` on every task deploy. `session.get_cpu_cores()` performs an uncached SSH exec per call, so a long-lived static session deploys N tasks with N redundant `getconf _NPROCESSORS_ONLN` round-trips.

This asymmetry is already a known deferred concern: `connected-machine-runtime-only` explicitly states "Node.ncpus persistence asymmetry for static nodes ... NOT addressed here. Separate concern; tracked as a potential follow-up." Worse, after `connected-machine-runtime-only` removes `ConnectedMachine.ncpus`, the orchestrator's falsy fallback at `_start_task_on_machine` becomes the *only* ncpus source for static-without-`~N` nodes — making the per-task SSH exec a load-bearing design feature rather than a defensive fallback.

## What Changes

- **BREAKING** (domain entity shape): `Node.ncpus` widens from `int` to `int | None`. `None` means "no operator limit, discover at spawn"; `N > 0` means "operator-set static config, use directly". The magic `0` sentinel is eliminated.
- **BREAKING** (domain entity shape): `NewNode.ncpus` default changes from `int = 0` to `int | None = None`.
- The cloud write-back in `CloudProvisionerImpl._setup_vm` (the `replace(node, enabled=True, ncpus=ncpus)` step) is removed. Cloud nodes no longer persist a runtime-discovered `ncpus`; they discover per-spawn like static nodes, unless a future cloud config option supplies a static value (out of scope here).
- The second `get_cpu_cores()` call inside `_setup_vm` (vestigial once the write-back is removed) is dropped — discovery happens once at `SSHMachineRepository.connect` and is cached on the session.
- `SSHMachineSession.get_cpu_cores()` memoizes its result per session lifetime. CPU count is invariant for the duration of one SSH connection, so repeated calls within a session return the cached value instead of re-executing `getconf`/PowerShell remotely. The cache is primed by the discovery already performed in `SSHMachineRepository.connect`.
- The orchestrator's ncpus resolution at `_start_task_on_machine` switches from falsy short-circuit (`(node and node.ncpus) or await ...`) to an explicit `None`-check form, honest about the `int | None` type.
- `yasetnode` encodes an absent `~ncpus` CLI argument as `None` (not `0`) when constructing `NewNode`.
- `yanodes` display treats `None` and `0` equivalently as "MAX" (no operator limit) — the existing `0 → "MAX"` mapping at `show_nodes.py` is generalized to the `None` case.
- DB schema gains a CHECK constraint `ncpus IS NULL OR ncpus > 0`; a migration backfills existing `0` rows to `NULL` (existing `NULL` and `> 0` rows untouched).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `domain-entities`: `Node.ncpus` widens `int → int | None`; `NewNode.ncpus` default `0 → None`; the semantic contract of the field changes from "discovery cache with magic 0" to "operator-set static config or None for per-spawn discovery".
- `postgres-schema-apply`: `yascheduler_nodes.ncpus` gains CHECK constraint `(ncpus IS NULL OR ncpus > 0)`; the column is already `SMALLINT DEFAULT NULL` so no type change is needed, only the constraint.
- `db-migrations`: new migration `013_ncpus_nullable.sql` installs the CHECK constraint and backfills `ncpus = 0` rows to `NULL`. Existing `NULL` and `> 0` rows are untouched.
- `orchestrator`: `_start_task_on_machine` resolves `ncpus` via an explicit `None`-check against `Node.ncpus`, falling back to `session.get_cpu_cores()` only when the node's value is `None` (or the node is absent). The falsy short-circuit form is replaced.
- `ssh-infrastructure`: `SSHMachineSession.get_cpu_cores()` memoizes its result per session instance; the discovery performed in `SSHMachineRepository.connect` primes the same cache so there is at most one remote CPU-count exec per connection lifetime.
- `cli`: `yasetnode` encodes an absent `~ncpus` as `None` in `NewNode`; `yanodes` displays `None` (and legacy `0`) as `"MAX"` to indicate "no operator limit, discovered at spawn".
- `cloud`: `CloudProvisionerImpl._setup_vm` no longer stamps the discovered `ncpus` onto the `Node` via `replace(node, enabled=True, ncpus=ncpus)` — the final replace becomes `replace(node, enabled=True)`. The standalone `get_cpu_cores()` call inside `_setup_vm` is removed as vestigial (discovery already happens in `_connect_to_vm`'s `SSHMachineRepository.connect` and is now session-cached).

## Impact

- **Domain model** (`yascheduler/domain/model.py`): `Node.ncpus` and `NewNode.ncpus` type/default change. The `Node` contract's `INPUTS` line updates to `int | None`.
- **Persistence** (`yascheduler/infra/persistence/sql/schema.sql`, new `migrations/013_ncpus_nullable.sql`, `postgres.py` adapter): schema CHECK constraint, migration backfill, adapter accepts `int | None` for the `ncpus` column binding.
- **Orchestrator** (`yascheduler/application/orchestrator.py`): `_start_task_on_machine` ncpus resolution form changes.
- **SSH session** (`yascheduler/infra/ssh/session.py`): `SSHMachineSession` gains a private `_cached_ncpus` field; `get_cpu_cores()` checks it before dispatching to the adapter.
- **Cloud manager** (`yascheduler/infra/cloud/manager.py`): `_setup_vm` drops the `ncpus=ncpus` kwarg from the final `replace` and drops the standalone `get_cpu_cores()` call.
- **CLI** (`yascheduler/entrypoints/cli/manage_node.py`, `yascheduler/entrypoints/cli/show_nodes.py`): `~ncpus`-absent encoding changes `0 → None`; `yanodes` display generalizes the `0 → "MAX"` mapping to `None`.
- **Tests**: dozens of `Node(..., ncpus=N)` and `NewNode(..., ncpus=N)` constructor sites — values stay valid (positive ints still valid), only the type widens. The `ncpus=0` test cases (e.g. `test_allocate_task_failure_modes.py:60`, `test_cli_manage_node.py:436-447`) become `ncpus=None` semantically; the `test_persistence_node_adapter.py:114-135` "get handles null/zero ncpus" case consolidates on `None`.
- **Ordering**: applies last, after both pending changes (`node-owns-connection-identity`, `connected-machine-runtime-only`). Assumes their post-state: `ConnectedMachine.ncpus` already removed, the misplaced `"CPUs count: %s"` log already relocated to `SSHMachineRepository.connect`. This change's session cache auto-primes from that relocated discovery site.
