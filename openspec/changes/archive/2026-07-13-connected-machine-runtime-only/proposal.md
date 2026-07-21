## Why

`ConnectedMachine` carries `hostname` and `ncpus` as frozen fields, but both are pure copies of values that already live on `Node` (set at connect time from `node.hostname` and `adapter.get_cpu_cores(...)`). Production consumption audit shows: `hostname` has exactly one reader — `occupy()` formats `MachineBusyError(self.node_id, self.hostname)`, an exception nobody catches and whose `.hostname` attribute nobody reads programmatically. `ncpus` has exactly one reader — a single info log `"CPUs count: %s"` in `SSHMachineSession.setup_node`, which is misplaced: discovery happens earlier (in `SSHMachineRepository.connect` at `adapter.get_cpu_cores(...)`), and the same ncpus value is also separately discovered again in `CloudProvisionerImpl._setup_vm` and again lazily in `Orchestrator._print_stats`-adjacent paths. The fields are dead weight carried through every `replace(self, state=...)` transition, and they obscure the actual responsibility of `ConnectedMachine`: runtime-only state (state, free_since) plus the one field that cannot live anywhere else (`platform` — runtime-discovered, not persisted).

## What Changes

- **BREAKING** (domain entity shape): `ConnectedMachine` loses fields `hostname` and `ncpus`. The frozen dataclass becomes `node_id: NodeId`, `platform: str`, `state: MachineState = FREE`, `free_since: float | None = None`.
- **BREAKING** (domain exception shape): `MachineBusyError(node_id, hostname)` → `MachineBusyError(node_id)`. The `.hostname` attribute is dropped; the message format loses the "at {hostname}" segment. Nobody catches `MachineBusyError` in production today and no consumer reads `.hostname` programmatically, so the break is contained.
- `MachineConnectionError(node_id, hostname, reason)` is UNCHANGED — its `hostname` comes from `node.hostname` at the raise site in `SSHMachineRepository.connect` (transport-level address the operator recognizes), not from `ConnectedMachine` (which does not exist yet at that point).
- The `"CPUs count: %s"` log line moves from `SSHMachineSession.setup_node` (where it is functionally unrelated to engine-package installation) to its discovery site in `SSHMachineRepository.connect`, immediately after `ncpus = await adapter.get_cpu_cores(...)`. The session method no longer reads `self._machine.ncpus`.
- `SSHMachineSession.hostname` (the transport-echo used by ~11 operator-facing log lines in `infra/ssh/operations/*`) is UNCHANGED — it stays as the session-level transport address, sourced from `node.hostname` at construction.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `domain-entities`: `ConnectedMachine` field list loses `hostname` and `ncpus`; `occupy()` raises `MachineBusyError(self.node_id)`; the requirement's "hostname is the transport address (the asyncssh host)" paragraph and the "two ConnectedMachine instances with the same hostname but different node_id are distinct" paragraph are removed (they describe a field that no longer exists).
- `domain-exceptions`: `MachineBusyError.__init__(node_id: NodeId)` — loses `hostname` parameter and attribute; message format becomes `"machine ({node_id}) is busy"`. `MachineConnectionError` is unchanged.
- `ssh-infrastructure`: `SSHMachineRepository.connect` constructs `ConnectedMachine` without `hostname` / `ncpus` arguments; the `"CPUs count: %s"` info log moves from `SSHMachineSession.setup_node` to the connect path's `START_BLOCK_CREATE_MACHINE` (after `ncpus = await adapter.get_cpu_cores(...)`). The `SSHMachineSession implements MachineSession` requirement's "initial snapshot with `state=FREE`, `free_since=time.monotonic()`" wording remains accurate; the construction description drops the implied shape detail.
- `testing-unit`: the `ConnectedMachine` state-transition test surface (`occupy`/`release`/`replace` scenarios) and the `MachineBusyError` construction assertions are updated for the slimmer shape. The `ConnectedMachine occupy sets state to BUSY` / `release resets free_since` scenarios drop the "and the same `hostname`, `platform`, `ncpus`" assertion tails.

## Impact

- **Code**:
  - `yascheduler/domain/model.py` — drop `hostname`, `ncpus` from `ConnectedMachine`; `occupy()` raises `MachineBusyError(self.node_id)`.
  - `yascheduler/domain/exceptions.py` — `MachineBusyError.__init__(self, node_id)`; message format.
  - `yascheduler/infra/ssh/repository.py` — `ConnectedMachine(...)` construction drops `hostname=`/`ncpus=` kwargs; add info log at the discovery site.
  - `yascheduler/infra/ssh/session.py` — `setup_node` drops the `"CPUs count: %s"` log line.
  - `yascheduler/domain/__init__.py` — module map docstring update (`MachineBusyError` loses "carries node_id, hostname").
- **APIs / Public Surface**: `ConnectedMachine` is a domain entity re-exported from `yascheduler.domain`; its constructor surface changes (BREAKING for direct construction outside the repo). `MachineBusyError` constructor surface changes (BREAKING for anyone raising it externally). Both are contained: `ConnectedMachine` is constructed in exactly one production site (`SSHMachineRepository.connect`); `MachineBusyError` is raised in exactly one site (`ConnectedMachine.occupy`). `class Yascheduler` public API, CLI syntax, INI format, DB schema — unchanged.
- **DB**: no schema change. `Node.ncpus` persists as before; `ConnectedMachine` is not persisted.
- **Operational behavior**: the `"CPUs count: %s"` log moves from engine-setup phase to connect phase (operator-visible: the line now appears once at connect rather than at every `setup_node` invocation; `setup_node` is rarely called more than once per session, so the net effect is minor). The `MachineBusyError` message text changes — any log-grep / alerting rule matching the old "at {hostname} is busy" pattern needs updating (very low probability; the exception is rarely raised in practice — it guards double-occupy which the orchestrator's allocator prevents).
- **Relationship to `node-owns-connection-identity` change**: the two changes are independent — either can land first. If `node-owns-connection-identity` lands first, this change is unaffected (it touches different fields on different entities). If this change lands first, `node-owns-connection-identity` is unaffected (it touches `Node.jump_*` and the `connect` signature, neither of which is `ConnectedMachine.hostname`/`ncpus`).
