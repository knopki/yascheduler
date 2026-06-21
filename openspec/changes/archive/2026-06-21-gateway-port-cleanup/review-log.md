## proposal Round 1 — 2026-06-20

### 🔴 Fixed (issues found and fixed)

None. Round 1 review — no fixes applied yet.

### 🟡 Addressed (minor issues addressed)

1. **Rejected alternatives not recorded in proposal**
   The explore-brief evaluates and rejects Option A (minimal backoff-only) and
   Option C (split into two Protocols), with explicit rationale. The proposal
   has no "Considered alternatives" / "Rejected alternatives" section, so a
   future reader of `proposal.md` alone sees only the chosen approach (B) with
   no record of why A and C were dismissed. This invites re-proposing them.
   Add a short "Considered Alternatives" section summarising A and C and the
   rejection reason from the brief.

2. **Decision 1 (backoff params hardcoded) missing from proposal**
   Brief Decision 1 states backoff parameters stay hardcoded
   (`fibo, max_time=60`) and are NOT exposed via `ConfigLocal`. The proposal's
   "What Changes" / "Capabilities" only says backoff "moves into adapter" —
   an implementer reading only the proposal could reasonably wire the params
   through config. Add an explicit line: backoff params remain hardcoded, not
   configurable.

3. **Decision 4 (`download_outputs` return type unchanged) missing from proposal**
   Brief Decision 4 keeps `download_outputs` return type as
   `list[tuple[str | None, Exception]]`. The proposal describes the method's
   behaviour but not its signature contract. Add the return type to the
   `download_outputs` bullet so the spec delta and implementation stay aligned.

4. **Deferred items not surfaced as explicit out-of-scope**
   Brief lists deferred items (`_start_task_on_machine`, `_upload_task_data`,
   `_exec_spawn_command`, `_write_remote_file`, `_safe_b64decode`). They are
   correctly excluded from the change scope, but the proposal does not state
   this. Add an "Out of Scope" section naming them so implementers and
   reviewers know the omissions are intentional (not oversights). This matters
   because `_start_task_on_machine` / `setup_node` appear in the brief's
   violation list but are deliberately not added to the Protocol.

5. **Import-removal grouping slightly imprecise**
   Proposal bullet 11 says all four symbols
   (`AllSSHRetryExc`, `SFTPRetryExc`, `asyncssh`, `SFTPError`) are "no longer
   imported in `orchestrator.py` and `consume_task.py`". Per the brief (and
   verified in code) the imports are split:
   `orchestrator.py` → `AllSSHRetryExc`, `asyncssh`;
   `consume_task.py` → `SFTPRetryExc`, `SFTPError`.
   Clarify per-file to avoid confusion during implementation/review.

### Verified correct (no action needed)

- **Method count**: existing `MachineGateway` Protocol has 4 methods
  (`list_free`, `run`, `upload`, `download`); proposal lists exactly the 11 new
  methods from the brief's table. "~11 new methods" in Impact > APIs is
  accurate.
- **Capability mapping**: all five modified capabilities
  (`domain-ports`, `domain-exceptions`, `ssh-gateway`, `orchestrator`,
  `use-cases`) exist under `openspec/specs/`. No new capability needed —
  correct.
- **No contradictions** between brief and proposal on the chosen approach,
  `list_connected()` replacing `items()`, or `MachineConnectionError` wrapping
  `asyncssh.misc.Error`.
- **Deferred items are not pulled into scope** — confirmed.

## design Round 1 — 2026-06-20

### 🔴 Fixed (issues found and fixed)

None. Round 1 review — no fixes applied yet.

### 🟡 Addressed (minor issues addressed)

1. **D7 references the wrong `Engine` class**
   design.md:111 claims "the domain `Engine` config class satisfies `PEngine`
   structurally (has `check_pname`, `check_cmd`, `check_cmd_code`,
   `sleep_interval`, `name`)". There are TWO `Engine` classes:
   - `yascheduler.domain.model.Engine` — lacks `check_cmd_code` and
     `sleep_interval` (verified: only `name`, `spawn`, `input_files`,
     `output_files`, `platforms`, `check_cmd`, `check_pname`). Does NOT
     satisfy `PEngine`.
   - `yascheduler.config.Engine` (attrs) — has all `PEngine` fields
     (`name`, `deployable`, `platforms`, `check_pname`, `check_cmd`,
     `check_cmd_code`, `sleep_interval`). This is the one the orchestrator
     actually passes (`self._engines` is `config.EngineRepository`, and
     `self._engines.get(...)` returns `config.Engine`).
   The decision itself (keep `PEngine` as the port param type) is sound, but
   the rationale must cite `yascheduler.config.Engine`, not "the domain
   `Engine` config class". As written, an implementer verifying the claim
   against `domain.model.Engine` will find it false and lose confidence in the
   decision. Fix the reference.

2. **D1 (`get_machine_state` → `ConnectedMachine | None`) does not address
   the two orchestrator call sites that read `state.machine`**
   `get_machine_state` currently returns `_MachineState | None`. D1 changes
   the return to `ConnectedMachine | None`. But both orchestrator call sites
   dereference `.machine` on the result:
   - `orchestrator.py:445` → `state = self._gateway.get_machine_state(ip)`
     then `orchestrator.py:470` `machine = state.machine`
   - `orchestrator.py:476` → `state = self._gateway.get_machine_state(ip)`
     then `orchestrator.py:478` `machine = state.machine`
   If the return type becomes `ConnectedMachine | None`, `state.machine` is
   invalid (`ConnectedMachine` has no `.machine` attribute). These sites must
   be refactored to `machine = self._gateway.get_machine_state(ip)` (use the
   value directly). D1 states "orchestrator only uses `state.machine`" as
   justification, but does not state the required refactor. Add an explicit
   note that both call sites change from `state.machine` to the returned
   `ConnectedMachine` directly, so the implementation task is visible.

3. **D5 (`list_connected()`) does not enumerate the two `items()` call sites
   that must be refactored**
   `items()` is used in two orchestrator spots, both accessing `state.machine`
   on the `ItemsView` value:
   - `orchestrator.py:323-327` (`_print_stats`): `for s in
     self._gateway.items() ... s[1].machine.state` → must become
     `for m in self._gateway.list_connected() ... m.state`.
   - `orchestrator.py:513-517` (`_deallocator_producer`):
     `for ip, state in self._gateway.items() ... state.machine` → must become
     `for m in self._gateway.list_connected() ... m` (note: also drops the `ip`
     key, but `m.ip` carries it).
   D5 gives the new method but not the refactoring obligation. Add a note so
   these two sites are covered in implementation.

4. **D3 (`connect` wraps `asyncssh.misc.Error`) wraps only `_open_connection`,
   but `connect()` also calls `_detect_platform` and `get_cpu_cores`**
   design.md:64-68 shows the try/except around `self._open_connection(...)`.
   `connect()` (gateway.py:165-203) subsequently calls `_detect_platform(conn,
   ADAPTERS)` and `adapter.get_cpu_cores(...)` — both perform SSH operations
   that can raise `asyncssh.misc.Error` (e.g. channel errors during platform
   detection). The orchestrator's current `except asyncssh.misc.Error`
   (orchestrator.py:391) catches errors from the entire `connect()` body. If
   the wrapper only covers `_open_connection`, a platform-detection
   `asyncssh.misc.Error` would escape as the raw adapter type — the exact leak
   this change removes. Either widen the try/except to cover the full
   `connect()` body, or document that `_detect_platform`/`get_cpu_cores`
   failures are retried via `SSHRetryExc` backoff and only surface as
   `MachineConnectionError` after exhaustion. Decide and document.

5. **`download_outputs` signature drops the `task` parameter, losing
   `task_id` from per-file warning logs**
   `_sftp_download_job` (consume_task.py:96-120) takes `task: Task` and uses
   `task.task_id` in the per-file warning (`"Cannot download file for
   task_id=%s from %s: %s"`). D2's `download_outputs` signature
   (design.md:46-54) has no `task` param. The adapter's `self._log` has no
   task context, so the moved log loses `task_id` correlation — a regression
   in operational traceability for failed output downloads. Either accept the
   regression explicitly (and note it), or add an optional `task_id: int |
   None = None` param for log context. Minor, but the brief's Decision 4 says
   "return type unchanged" and says nothing about logging; an implementer
   should not silently drop a correlated log field.

6. **`check_status.py` (CLI adapter) also calls `get_machine_state` and
   `state.machine` — not mentioned**
   `adapters/cli/check_status.py:163-168` calls
   `gateway.get_machine_state(ip)` then `state.machine`. This is in the
   adapter layer (not application), so D1's port return-type change does not
   force a refactor there — it can keep using the concrete
   `SSHMachineGateway`. But the design lists no callers of
   `get_machine_state` beyond the orchestrator. Since `SSHMachineGateway`
   keeps a concrete `get_machine_state` returning `_MachineState | None` for
   adapter-internal use (the Protocol just adds a `ConnectedMachine`-returning
   method), clarify whether the concrete method's return type also changes or
   whether the Protocol method is a distinct (possibly renamed) member. As
   written, "port method returns `ConnectedMachine | None`" leaves the
   concrete signature ambiguous. Specify: does `SSHMachineGateway.get_machine_state`
   keep returning `_MachineState | None` (and the Protocol declares a
   different method), or does the concrete method's return type change too
   (breaking `check_status.py`)?

### Verified correct (no action needed)

- **Backoff params hardcoded** (brief Decision 1): design D4 and Non-Goals
  both state `fibo, max_time=60` hardcoded, not via `ConfigLocal`. Consistent
  with frozen proposal Decisions.
- **`list_connected()` replaces `items()`** (brief Decision 2): design D5
  matches `list[ConnectedMachine]` return. Consistent.
- **`MachineConnectionError` for `connect`** (brief Decision 3): design D3
  wraps `asyncssh.misc.Error` into `MachineConnectionError(DomainError)`.
  `domain/exceptions.py` has `DomainError` base (verified). Consistent.
- **`download_outputs` return type unchanged** (brief Decision 4): design D2
  keeps `list[tuple[str | None, Exception]]`. Consistent.
- **Deferred items not pulled into scope**: design Non-Goals explicitly defer
  `_start_task_on_machine` / `_upload_task_data` / `_exec_spawn_command`.
  No scope creep into `setup_node`. Consistent with frozen proposal Out of
  Scope.
- **No contradictions with frozen proposal**: design Decisions D1–D7 map to
  proposal "What Changes" and "Decisions" without conflict.
- **Rejected alternatives carried forward**: proposal "Considered
  Alternatives" (A minimal, C split) align with brief; design does not
  re-litigate them.
- **D4 `my_backoff_sftp` variant** for SFTP methods is a reasonable
  derivation from existing `my_backoff_exc` (helpers.py:92-94 uses
  `partial(backoff.on_exception, wait_gen=fibo, max_time=60,
  exception=SSHRetryExc)`). The SFTP variant swaps `SSHRetryExc` →
  `SFTPRetryExc`. Consistent with current `consume_task.py` backoff usage.
- **D6 `contains()` already exists** on `SSHMachineGateway` (gateway.py:530)
  and the Protocol just documents it. Verified.

### 🔴 Outstanding

1. **D1/D5 leave the orchestrator refactoring unspecified** — the two
   `get_machine_state` call sites (orchestrator.py:445,476) and the two
   `items()` call sites (orchestrator.py:323,513) must be rewritten to use
   `ConnectedMachine` directly. The design states the new port shapes but
   does not list these four refactoring obligations. Without them, the
   implementation task list will likely miss the `.machine` dereferences and
   the change will not compile. (See Addressed #2 and #3 — listed as
   Outstanding until the design text is updated to enumerate the sites.)

2. **D3 wrapping scope is ambiguous** — whether the `asyncssh.misc.Error`
   wrapper covers the full `connect()` body or only `_open_connection` is
   undecided. This determines whether platform-detection errors leak as raw
   adapter types. (See Addressed #4.)

## design Round 2 — 2026-06-20

### 🔴 Fixed

None. `design.md` is unchanged since Round 1 — no Round 1 issue has been
resolved in the document. This round re-verified all Round 1 findings against
the current source and added new gaps surfaced on a second pass.

### 🟡 Addressed (new issues found in Round 2)

1. **D2 overstates what moves into the adapter — `meta_add` is orphaned**
   `design.md:58` claims D2 "moves `_sftp_download_job` +
   `_download_task_outputs` logic from `consume_task.py` into adapter". The
   D2 signature (`design.md:46-54`) returns only
   `list[tuple[str | None, Exception]]` (sftp_errors). But
   `_download_task_outputs` (consume_task.py:137-161) currently returns
   `tuple[list[tuple[str, Any]], list[...]]` — i.e. `(meta_add, sftp_errors)`.
   `meta_add` (`[("remote_folder", remote_folder),
   ("local_folder", str(store_folder))]`) is consumed by `_finalize_task` →
   `_record_finalization_event` (consume_task.py:180-191) to populate
   `task.context.local_folder`/`remote_folder`/`extra`. If both helper functions
   "move into the adapter" but the new method returns only errors, `meta_add`
   has no producer. The caller still has `remote_folder` and `store_folder` as
   parameters and could rebuild `meta_add` inline, but the design does not say
   so. Fix: either (a) narrow D2's rationale to "moves `_sftp_download_job`
   logic; `meta_add` construction stays in `consume_task` using its existing
   parameters", or (b) widen the return type to carry `meta_add`. (a) is
   simpler and matches the proposal's wording ("SFTP session management,
   per-file retry, and remote directory cleanup").

2. **D2 drops the outer catch-all → error-tuple behaviour of
   `_download_task_outputs`**
   `_download_task_outputs` (consume_task.py:151-159) wraps the whole job in
   `try/except Exception` and on failure returns `[(remote_folder, err)]` —
   a single error tuple, not a raised exception. This guarantees
   `_finalize_task` always receives a list (possibly with one entry) and never
   propagates a download-time exception to the orchestrator's consume loop.
   D2's "Responsibilities" (`design.md:56`) only describe per-file download
   with retry and remote-dir removal — the outer catch-all is not preserved in
   the described contract. If `download_outputs` lets an unexpected exception
   escape (e.g. `SFTPError` not under `SFTPRetryExc`, or `rmtree` failure),
   the orchestrator's `_task_consumer_consumer` will see a raw exception
   instead of a finalized `TaskFailed` event — a behaviour regression. Fix:
   add "swallow non-retry exceptions and return them as
   `[(remote_dir, err)]`" to D2's Responsibilities, or explicitly state the
   method re-raises and the caller wraps.

3. **D7 introduces a NEW domain→adapter dependency, contradicting the
   change's own Goal**
   `design.md:21` Goal: "Application layer has zero runtime imports from
   `yascheduler.adapters`". Verified: today `yascheduler/domain/**` has zero
   imports from `yascheduler.adapters` (clean hexagonal direction). D7 keeps
   `PEngine` as the `start_occupancy_check` parameter type in the port. But
   `PEngine` is defined in `yascheduler/adapters/ssh/platform/protocol.py`
   (protocol.py:110-119), so `domain/ports.py` would now
   `from yascheduler.adapters.ssh.platform.protocol import PEngine`. Worse,
   `PEngine.deployable` is typed as
   `tuple[LocalFilesDeploy | LocalArchiveDeploy | RemoteArchiveDeploy, ...]`
   (protocol.py:112-114) — adapter-defined deploy-strategy types — so the
   import is transitively dirtier than a "pure structural Protocol". The
   design's mitigation ("could be moved to domain in a future change",
   design.md:123) is a punt: this change trades one architectural leak
   (application importing adapter symbols) for another (domain port importing
   adapter symbols). Fix: either (a) move `PEngine` (or a slimmed
   domain-owned `OccupancyEngine` Protocol without `deployable`) to
   `domain/ports.py` or a new `domain/protocols.py` in this change, or (b)
   define a minimal domain Protocol inline in `ports.py` with only the fields
   `start_occupancy_check` touches (`name`, `check_pname`, `check_cmd`,
   `check_cmd_code`, `sleep_interval`). Option (b) also dissolves Round 1
   issue #1 (the wrong-`Engine`-class citation) because the structural
   protocol would be satisfied by `config.Engine` directly.

4. **D6 `contains()` is sync but the rest of the extended port is async —
   worth saying explicitly**
   `contains` already exists as a sync method on `SSHMachineGateway`
   (gateway.py:530) and the design keeps it sync in the Protocol
   (design.md:104). Fine, but the rest of the extended port is async. An
   implementer writing the spec delta or a mock might assume uniform `async`.
   Add a one-line note that `contains`, `list_connected`, `list_free`,
   `update_machine`, `get_machine_state`, `start_occupancy_check` are sync
   (matching the existing concrete signatures) while the I/O methods
   (`connect`, `disconnect`, `disconnect_all`, `run`, `run_bg`, `upload`,
   `download`, `download_outputs`, `get_cpu_cores`) are async. This is the
   kind of detail that should be settled in design, not discovered at
   implementation time.

5. **`update_machine` is in the proposal/brief but absent from every design
   decision**
   The proposal (proposal.md:7) and the brief's table (explore-brief.md:44)
   list `update_machine` as a new port method. The design has decisions D1–D7
   covering 14 of the 15 table rows, but `update_machine` is mentioned
   nowhere. It is trivial (takes `ConnectedMachine`, returns `None`, no
   backoff, no adapter-type leak) so it likely needs no dedicated decision —
   but the design should at least acknowledge its existence (e.g. a one-line
   note under D5 or D6: "`update_machine(machine: ConnectedMachine) -> None`
   passes through unchanged; no design considerations"). Otherwise an
   implementer scanning D1–D7 may miss it.

### 🔴 Outstanding

All Round 1 items remain unresolved (design.md unchanged). Re-verified each
against current source — call sites and code line numbers below are accurate
as of this round.

1. **(Round 1 #1) D7 cites the wrong `Engine` class** — `design.md:111`
   still says "the domain `Engine` config class satisfies `PEngine`
   structurally". Verified: `domain/model.py:122` `Engine` has only
   `check_cmd`, `check_pname` — no `check_cmd_code`, `sleep_interval`,
   `deployable`. The class that actually satisfies `PEngine` is
   `config/engine.py:116` `Engine` (attrs, has all fields). Fix the
   reference. (If Round 2 #3 above is adopted — inline domain Protocol —
   this issue dissolves.)

2. **(Round 1 #2) D1 does not enumerate the refactoring of the two
   `get_machine_state` call sites** — `orchestrator.py:445`→`:470`
   (`machine = state.machine`) and `orchestrator.py:476`→`:478`
   (`machine = state.machine`). With D1's return-type change to
   `ConnectedMachine | None`, `state.machine` is invalid. Both sites must
   become `machine = self._gateway.get_machine_state(ip)` (use the value
   directly). D1's rationale "orchestrator only uses `state.machine`"
   implies but does not list the required refactor.

3. **(Round 1 #3) D5 does not enumerate the refactoring of the two `items()`
   call sites** — `orchestrator.py:323-327` (`_print_stats`,
   `s[1].machine.state`) and `orchestrator.py:513-517`
   (`_deallocator_producer`, `for ip, state in self._gateway.items()` →
   `state.machine`). Both must be rewritten to consume
   `list[ConnectedMachine]` directly. Note `_deallocator_producer` also uses
   the dict key `ip` — `ConnectedMachine.ip` carries it, but the rewrite is
   non-mechanical.

4. **(Round 1 #4) D3 wrapping scope is ambiguous** — `design.md:64-68`
   wraps only `self._open_connection(...)`. But `connect()` (gateway.py:165
   -203) also calls `_detect_platform(conn, ADAPTERS)` (line 175) and
   `adapter.get_cpu_cores(...)` (line 184), both of which perform SSH I/O
   that can raise `asyncssh.misc.Error`. The orchestrator's current
   `except asyncssh.misc.Error` (orchestrator.py:391) catches failures from
   the entire `connect()` body. If the wrapper only covers
   `_open_connection`, a platform-detection `asyncssh.misc.Error` escapes as
   the raw adapter type — the exact leak this change removes. Decide:
   widen the try/except to cover the full `connect()` body, or document
   that `_detect_platform`/`get_cpu_cores` failures surface as
   `MachineConnectionError` via `SSHRetryExc` backoff exhaustion.

5. **(Round 1 #5) `download_outputs` drops `task_id` from per-file warning
   logs** — `_sftp_download_job` (consume_task.py:114-115) logs
   `"Cannot download file for task_id=%s from %s: %s"` with `task.task_id`.
   D2's signature has no `task` param (design.md:46-54). The moved log loses
   `task_id` correlation — an operational-traceability regression for
   failed output downloads. Either accept the regression explicitly in the
   design, or add an optional `task_id: int | None = None` param purely for
   log context.

6. **(Round 1 #6) D1 is ambiguous about the concrete
   `SSHMachineGateway.get_machine_state` return type** — the Protocol method
   returns `ConnectedMachine | None`, but `adapters/cli/check_status.py:163
   -168` calls `gateway.get_machine_state(ip)` then `state.machine` on the
   concrete class. Does the concrete method keep returning
   `_MachineState | None` (and the Protocol declares a co-existing method
   under a different name?), or does the concrete signature change too
   (breaking `check_status.py`)? The design must state which. If the
   concrete method's return type changes, `check_status.py` is a caller that
   breaks; if it stays, the Protocol method needs a distinct name (e.g.
   `get_connected_machine`) or the Protocol method is a separate member.

7. **(Round 2 #1) D2 `meta_add` flow is unspecified** — see Addressed #1.
   Listed as Outstanding because if implemented as currently written, the
   `consume_task` → `_finalize_task` path breaks: `meta_add` has no producer
   and `task.context.local_folder`/`remote_folder` stop being populated.

8. **(Round 2 #2) D2 outer catch-all behaviour unspecified** — see
   Addressed #2. Behaviour regression risk for `_task_consumer_consumer` if
   unexpected exceptions escape `download_outputs`.

9. **(Round 2 #3) D7 creates a new domain→adapter import** — see
   Addressed #3. Directly contradicts the change's stated Goal
   (design.md:21). The mitigation "could be moved in a future change" is
   not acceptable as the sole resolution for a change whose entire purpose
   is enforcing dependency-direction rules.

### Verified correct (re-confirmed, no action)

- **Backoff params hardcoded `fibo, max_time=60`** (brief Decision 1):
  design D4 + Non-Goals consistent with frozen proposal Decisions.
- **`list_connected()` replaces `items()`** (brief Decision 2): design D5
  matches `list[ConnectedMachine]`.
- **`MachineConnectionError(DomainError)` for `connect`** (brief Decision 3):
  design D3 + `domain/exceptions.py:31` `DomainError` base verified.
- **`download_outputs` return type unchanged** (brief Decision 4): design D2
  keeps `list[tuple[str | None, Exception]]` — the *element* type is
  unchanged; the surrounding flow (meta_add) is the open question.
- **Deferred items not pulled into scope**: `_start_task_on_machine`,
  `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
  `_safe_b64decode`, `setup_node` — all correctly excluded. Verified none
  appear in D1–D7 or in the proposal's "What Changes".
- **No contradictions with frozen proposal**: D1–D7 map cleanly to
  proposal.md "What Changes" and "Decisions".
- **`my_backoff_sftp` SFTP variant** (D4) is a correct derivation of the
  existing `my_backoff_exc` (gateway.py:63-68) — only swaps the exception
  type, matching current `consume_task.py:105,151`.
- **`contains()` already exists on concrete** (gateway.py:530) — D6 is a
  pure Protocol documentation change.

## design Round 3 — 2026-06-20

Note on numbering: the log already contains a "design Round 2" entry (a
second pass on the *unchanged* design that surfaced new gaps). This is the
first review of the *updated* design, hence Round 3.

### 🔴 Fixed

1. **D2 `meta_add` orphan resolved** — design.md:53 now returns
   `tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]`
   i.e. `(meta_add, sftp_errors)`. Verified `_finalize_task`
   (consume_task.py:234-241) consumes both elements and
   `_record_finalization_event` (consume_task.py:170-217) reads `meta_add`
   to populate `task.context.local_folder`/`remote_folder`/`extra`. Frozen
   proposal.md:22 signature matches. Closes Round 2 Outstanding #7.

2. **D2 catch-all behaviour now explicit** — design.md:60 states "Catches
   all exceptions (including non-retry) and returns them in `sftp_errors`
   list, guaranteeing the caller always gets a result rather than an
   exception." This preserves `_download_task_outputs`'s outer
   `try/except Exception` contract (consume_task.py:151-159) that prevents
   raw download exceptions reaching `_task_consumer_consumer`. Closes
   Round 2 Outstanding #8.

3. **`update_machine` now has a dedicated decision (D8)** — design.md:123-132
   adds D8 covering `update_machine(machine: ConnectedMachine) -> None`.
   Verified concrete exists at gateway.py:332-336 and orchestrator calls it
   at orchestrator.py:277. Resolves Round 2 Addressed #5.

### 🟡 Addressed

1. **D6 sync/async split — partial** — design.md:113 adds a note that
   `contains()` and `list_connected()` are sync. But Round 2 #4 asked for
   all sync/async distinctions; the note covers 2 of the 6 sync methods.
   Verified at gateway.py: `list_free` (gateway.py:238), `update_machine`
   (gateway.py:332), `get_machine_state` (gateway.py:328),
   `start_occupancy_check` (gateway.py:402) are also sync but unclassified.
   An implementer writing the Protocol/mock still has to discover this.

2. **D7 domain→adapter import — import leak fixed, but the replacement
   rationale is verifiably false (see Outstanding #1)** — D7
   (design.md:115-121) no longer imports `PEngine` into `domain/ports.py`,
   so the strict "no adapter import in domain" goal is met. However the
   substitution trades the import leak for an incorrect structural claim.

### 🔴 Outstanding

1. **D7's central claim is false: domain `Engine` does NOT satisfy `PEngine`**
   design.md:119 asserts "domain `Engine` satisfies `PEngine` structurally
   (has `check_pname`, `check_cmd`, `check_cmd_code`, `sleep_interval`,
   `name`)". Verified FALSE: `domain/model.py:121-131` `Engine` has only
   `name`, `spawn`, `input_files`, `output_files`, `platforms`, `check_cmd`,
   `check_pname`. It LACKS `check_cmd_code`, `sleep_interval`, and
   `deployable` — all three required by `PEngine`
   (`adapters/ssh/platform/protocol.py:110-119`). Round 1 #1 identified
   `config/engine.py:116` `Engine` as the class that actually satisfies
   `PEngine`; the fix changed the citation to `domain/model.py` `Engine` —
   precisely the class Round 1 said does NOT satisfy it. The adapter
   dereferences the missing fields at runtime: gateway.py:384,386 reads
   `engine.check_cmd_code`; gateway.py:415,419 reads `engine.sleep_interval`;
   `platform/linux.py:261` and `platform/windows.py:300` read
   `engine.deployable`. The orchestrator passes `self._engines.get(...)`
   (orchestrator.py:472), which returns `config.Engine`, so runtime works
   by accident — but the port contract is wrong and mypy flags the
   `config.Engine` vs `domain.Engine` mismatch. Round 1 #1 / Round 2 #1+#9
   NOT resolved; the cited class is still wrong. Fix: (a) define a minimal
   domain-owned Protocol in `domain/ports.py` with only the fields
   `start_occupancy_check` touches (`name`, `check_pname`, `check_cmd`,
   `check_cmd_code`, `sleep_interval`), satisfied structurally by
   `config.Engine`; or (b) move a slimmed `PEngine` (without `deployable`)
   into the domain layer.

2. **(Round 1 #2) D1 still does not enumerate the two `get_machine_state`
   refactoring sites** — orchestrator.py:445→:470 (`machine = state.machine`)
   and :476→:478 (`machine = state.machine`). With D1's return-type change
   to `ConnectedMachine | None`, `state.machine` is invalid
   (`ConnectedMachine` has no `.machine`). Both must become
   `machine = self._gateway.get_machine_state(ip)`. design.md:35-41 still
   does not list these.

3. **(Round 1 #3) D5 still does not enumerate the two `items()` refactoring
   sites** — orchestrator.py:323-327 (`_print_stats`: `s[1].machine.state`)
   and :513-517 (`_deallocator_producer`:
   `for ip, state in self._gateway.items()` → `state.machine`). Both must
   be rewritten to consume `list[ConnectedMachine]` directly. Note
   `_deallocator_producer` also uses the dict key `ip`; `ConnectedMachine.ip`
   carries it but the rewrite is non-mechanical. design.md:91-102 still
   does not list these.

4. **(Round 1 #4) D3 wrapping scope still ambiguous** — design.md:66-72
   shows the try/except around only `self._open_connection(...)`. `connect()`
   (gateway.py:165-203) subsequently calls `_detect_platform(conn, ADAPTERS)`
   (line 175) and `adapter.get_cpu_cores(...)` (line 184), both performing
   SSH I/O that can raise `asyncssh.misc.Error`. If the wrapper only covers
   `_open_connection`, platform-detection errors escape as the raw adapter
   type — the exact leak this change removes. Decide: widen the try to cover
   the full `connect()` body, or document the alternate surfacing path.

5. **(NEW) D3 defeats the existing `@my_backoff_exc()` retry on `connect()`**
   `connect()` is decorated with `@my_backoff_exc()` (gateway.py:149),
   which retries on `SSHRetryExc`. D3 adds an inner
   `except asyncssh.misc.Error` converting to `MachineConnectionError`.
   Because every `SSHRetryExc` member (e.g. `ChannelOpenError`,
   `ConnectionLost`) is a subclass of `asyncssh.misc.Error`, the inner
   except catches retryable errors BEFORE they reach the backoff decorator,
   converts them to `MachineConnectionError` (not in `SSHRetryExc`), and
   backoff never retries. This is a silent behaviour regression: connection
   retries disappear. Reconcile conversion with retry — e.g. a two-phase
   wrapper (backoff on the impl, convert only what escapes after
   exhaustion), or explicitly narrow the except to non-retryable asyncssh
   errors. State the chosen ordering in D3.

6. **(Round 1 #5) `download_outputs` still drops `task_id` from per-file
   warning logs** — `_sftp_download_job` (consume_task.py:113-118) logs
   `"Cannot download file for task_id=%s from %s: %s"` with `task.task_id`.
   D2's signature (design.md:46-54) has no `task`/`task_id` param, so the
   moved log loses task correlation — an operational-traceability
   regression for failed output downloads. Either accept the regression
   explicitly in the design, or add an optional `task_id: int | None = None`
   param purely for log context.

7. **(Round 1 #6) D1 still ambiguous about the concrete
   `SSHMachineGateway.get_machine_state` return type** — the Protocol
   method returns `ConnectedMachine | None`, but
   `adapters/cli/check_status.py:163-168` calls
   `gateway.get_machine_state(ip)` then `state.machine` on the concrete
   class. Does the concrete method keep returning `_MachineState | None`
   (co-existing Protocol method under a different name?), or does its
   return type change too (breaking `check_status.py`)? design.md:35-41
   does not say.

8. **(NEW) `run_bg` port return type is an adapter-type leak** — concrete
   `run_bg` (gateway.py:284-294) returns `SSHClientProcess` (asyncssh
   type). The brief lists `run_bg` as a new port method
   (explore-brief.md:39) but neither brief, proposal, nor design specifies
   its return type in the port. Declaring `-> SSHClientProcess` leaks an
   adapter type into the domain port (violates the change's own Goal);
   declaring `-> None` is an incompatible override (concrete returns a
   value). The orchestrator discards the return (orchestrator.py:250), so
   a `None`-returning wrapper is functionally fine — but the design must
   state the resolution.

9. **(NEW) Proposal's "remove `asyncssh`" from orchestrator.py is
   unachievable given the deferred scope** — proposal.md:11 says remove
   `import asyncssh` from orchestrator.py. But deferred functions still
   reference it: `_write_remote_file` (orchestrator.py:100
   `except asyncssh.misc.Error`) and `_upload_task_data` (orchestrator.py:192
   `except asyncssh.misc.Error`). With D3 only covering
   `_connect_machine_consumer` (orchestrator.py:391), the
   `import asyncssh` at orchestrator.py:34 cannot be removed without also
   refactoring those two sites. The design's Non-Goals defer
   `_upload_task_data`/`_write_remote_file` but do not reconcile this with
   the proposal's import-removal claim. Either narrow the proposal
   ("remove `asyncssh` usage from `_connect_machine_consumer`; the import
   stays for deferred helpers") or pull those two `except` clauses into
   scope.

10. **(NEW) Deferred functions call non-Protocol methods on a gateway typed
    `MachineGateway`** — once `self._gateway` is annotated `MachineGateway`,
    the deferred helpers `_start_task_on_machine` / `_upload_task_data` /
    `_exec_spawn_command` call `get_path` (orchestrator.py:278), `get_sftp`
    (orchestrator.py:189,282), `get_hostname` (orchestrator.py:274),
    `get_quote` (orchestrator.py:247) — none of which are in the Protocol.
    Static checking flags every call. The deferral rationale ("isolated
    behind a callback") does not address how these calls type-check
    against the Protocol. Either the callback receives the concrete
    `SSHMachineGateway` (Goal not met for those functions), or these
    methods are added to the Protocol, or the helpers move into the
    adapter.

11. **(NEW) `len(self._gateway)` (orchestrator.py:607) needs `__len__` in
    the Protocol** — `_await_first_machine` calls `len(self._gateway)`.
    Neither Protocol nor any design decision defines `__len__`. After
    re-typing `_gateway` as `MachineGateway`, this is a static error. Add
    `__len__` to the Protocol, or refactor the check to
    `self._gateway.list_connected()`.

### Verified correct (re-confirmed, no action)

- **Backoff params hardcoded `fibo, max_time=60`** (brief Decision 1):
  design D4 + Non-Goals consistent with frozen proposal Decisions.
- **`list_connected()` replaces `items()`** (brief Decision 2): design D5
  matches `list[ConnectedMachine]`.
- **`MachineConnectionError(DomainError)` for `connect`** (brief Decision
  3): `domain/exceptions.py:31` `DomainError` base verified; design D3
  wraps `asyncssh.misc.Error` (interaction with backoff is the open
  question — see Outstanding #5).
- **`download_outputs` return type matches frozen proposal** (proposal.md:22):
  design D2 `tuple[list[tuple[str, Any]], list[tuple[str | None,
  Exception]]]` is identical.
- **Deferred items not pulled into scope**: `_start_task_on_machine`,
  `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
  `_safe_b64decode`, `setup_node` — all correctly excluded from D1–D8.
- **`my_backoff_sftp` SFTP variant** (D4) correctly derives from
  `my_backoff_exc` (gateway.py:63-68), swapping `SSHRetryExc`→`SFTPRetryExc`.
- **D8 `update_machine`** correctly notes the concrete already exists
  (gateway.py:332-336).

## design Round 4 — 2026-06-20

Note on numbering: appending as Round 4. The log already contains a
"design Round 3" entry; the fixes reviewed here address Round 3
Outstanding items (#1 D7 false claim, #5 D3 backoff defeat, #9 proposal
asyncssh). The three Round-3 blockers the author flagged as fixed are
re-verified below against current source.

### 🔴 Fixed

1. **D7 false claim resolved — `OccupancyConfig` Protocol in domain**
   design.md:128-152 replaces the `PEngine` parameter with a new
   `OccupancyConfig` Protocol in `domain/ports.py` carrying exactly
   `name`, `check_pname`, `check_cmd`, `check_cmd_code`, `sleep_interval`.
   Verified `config.Engine` (config/engine.py:119,121,124,154,155) has all
   five fields → satisfies the Protocol structurally. Verified
   `start_occupancy_check` + `occupancy_check` (gateway.py:344-443)
   dereference exactly those five (gateway.py:352,368,375,382,384,386,415,
   429) and no others. No `domain→adapter` or `domain→config` import.
   Closes Round 3 Outstanding #1 (and dissolves the wrong-`Engine`-class
   citation: the claim now correctly names `config.Engine`, not
   `domain.Engine`).

2. **D3 backoff defeat resolved — two-method pattern**
   design.md:64-88 splits `connect` into `_connect_impl` (decorated with
   `@my_backoff_exc()`, retries on `SSHRetryExc`) and an outer `connect`
   that translates the post-exhaustion exception to
   `MachineConnectionError`. The backoff decorator now sees the raw
   `SSHRetryExc` before any translation, so retries are preserved. Also
   resolves Round 1 #4 / Round 3 #4 (wrapping scope): `_connect_impl`
   contains `_open_connection`, `_detect_platform`, AND `get_cpu_cores`,
   so the whole `connect()` body is covered by the wrapper. Closes Round 3
   Outstanding #4 and #5.

3. **Proposal `asyncssh` removal claim reconciled**
   proposal.md:11 now states "`asyncssh` remains in `orchestrator.py` for
   deferred `_write_remote_file`/`_upload_task_data` — will be removed
   when those move to adapter." This matches the code reality
   (orchestrator.py:100,192 still reference `asyncssh.misc.Error`) and the
   design's Non-Goals. Closes Round 3 Outstanding #9.

### 🟡 Addressed

1. **Brief decision 5 consistent with design D7** — explore-brief.md:107
   accurately states "`domain.Engine` lacks these fields; `config.Engine`
   satisfies it structurally. Avoids domain→adapter and domain→config
   imports." Matches design.md:147,152. No cross-artifact drift on the
   OccupancyConfig fix.

2. **Brief decision 3 consistent with design D3** — explore-brief.md:102
   describes the two-method pattern ("inner `_connect_impl` with backoff,
   outer `connect` translates exhausted `SSHRetryExc` into
   `MachineConnectionError`"). Matches design.md:64-88.

### 🔴 Outstanding

1. **(NEW) D3 outer `except SSHRetryExc` is too narrow — leaks
   non-retryable `asyncssh.misc.Error` subclasses**
   design.md:76 catches only `SSHRetryExc`. But `SSHRetryExc`
   (protocol.py:89-100) does NOT cover all `asyncssh.misc.Error`
   subclasses. Verified at runtime:
   `issubclass(asyncssh.PermissionDenied, <each SSHRetryExc member>)` →
   False; same for `asyncssh.DisconnectError`. Both are
   `asyncssh.misc.Error` subclasses (mro confirms). Trace of the leak:
   `_open_connection` raises `PermissionDenied` (auth failure) → backoff
   does not catch it (not in `SSHRetryExc`, correct — not retryable) →
   outer `connect` does not catch it (not in `SSHRetryExc`) → propagates
   RAW to orchestrator. The current orchestrator handler
   (orchestrator.py:391 `except asyncssh.misc.Error`) catches it; once
   that catch is replaced by `except MachineConnectionError` (the whole
   point of this change), auth failures and `DisconnectError` become
   unhandled or fall through to the generic `except Exception`
   (orchestrator.py:393), losing the "Can't connect" categorisation and
   breaking the stated Goal that `connect()` failures surface as
   `MachineConnectionError`. Fix: widen the outer to
   `except asyncssh.misc.Error as err` (covers all SSH failures including
   non-retryable), keeping `@my_backoff_exc()` on `_connect_impl` limited
   to `SSHRetryExc` (only retryable types retry). Post-exhaustion
   `OSError`/`asyncio.TimeoutError` (in `SSHRetryExc` but not
   `asyncssh.misc.Error` subclasses) also need coverage — catch
   `(asyncssh.misc.Error, OSError)` or extend the tuple deliberately.

2. **(Round 3 #2) D1 does not enumerate the two `get_machine_state`
   refactoring sites** — orchestrator.py:445→:470 and :476→:478 both do
   `state = self._gateway.get_machine_state(ip)` then `machine =
   state.machine`. With D1's return-type change to
   `ConnectedMachine | None`, `state.machine` is invalid
   (`ConnectedMachine` has no `.machine`). Both must become
   `machine = self._gateway.get_machine_state(ip)`. design.md:35-41 still
   does not list these. Verified call sites unchanged.

3. **(Round 3 #3) D5 does not enumerate the two `items()` refactoring
   sites** — orchestrator.py:323-327 (`_print_stats`:
   `s[1].machine.state`, verified present) and :513-517
   (`_deallocator_producer`). Both must be rewritten to consume
   `list[ConnectedMachine]` directly. `_deallocator_producer` also uses
   the dict key `ip`; `ConnectedMachine.ip` carries it but the rewrite is
   non-mechanical. design.md:91-102 still does not list these.

4. **(Round 3 #6) `download_outputs` drops `task_id` from per-file
   warning logs** — `_sftp_download_job` (consume_task.py) logs
   `"Cannot download file for task_id=%s ..."` with `task.task_id`. D2's
   signature (design.md:46-54) has no `task`/`task_id` param, so the moved
   log loses task correlation — an operational-traceability regression.
   Either accept explicitly in the design, or add
   `task_id: int | None = None` for log context.

5. **(Round 3 #7) D1 still ambiguous about the concrete
   `SSHMachineGateway.get_machine_state` return type** — Protocol method
   returns `ConnectedMachine | None`, but
   `adapters/cli/check_status.py:163-168` calls the concrete method then
   `state.machine`. Does the concrete keep returning `_MachineState | None`
   (co-existing method under a different name?) or does its return type
   change too (breaking `check_status.py`)? design.md:35-41 does not say.

6. **(Round 3 #8) `run_bg` port return type is unspecified — adapter-type
   leak risk** — concrete `run_bg` (gateway.py:284-294) returns
   `SSHClientProcess` (asyncssh type). Neither brief, proposal, nor design
   specifies the port return type. `-> SSHClientProcess` leaks an adapter
   type into the domain port (Goal violation); `-> None` is an
   incompatible override. The orchestrator discards the return
   (orchestrator.py:250), so `None` is functionally fine — but the design
   must state the resolution.

7. **(Round 3 #10) Deferred helpers call non-Protocol methods on a
   `MachineGateway`-typed gateway** — once `self._gateway` is annotated
   `MachineGateway`, the deferred `_start_task_on_machine` /
   `_upload_task_data` / `_exec_spawn_command` call `get_quote`
   (orchestrator.py:247), `run_bg` (orchestrator.py:250), `get_sftp`,
   `get_hostname`, `get_path` — none in the Protocol. Static checking
   flags every call. The deferral rationale ("isolated behind a
   callback") does not address how these type-check. Either the callback
   receives the concrete `SSHMachineGateway`, these methods join the
   Protocol, or the helpers move into the adapter. Decide and document.

8. **(Round 3 #11) `len(self._gateway)` (orchestrator.py:607) needs
   `__len__` in the Protocol** — `_await_first_machine` calls
   `len(self._gateway)`. Verified present. Neither Protocol nor any
   decision defines `__len__`. After re-typing `_gateway` as
   `MachineGateway`, this is a static error. Add `__len__` to the
   Protocol, or refactor to `self._gateway.list_connected()`.

### Verified correct (re-confirmed, no action)

- **Backoff params hardcoded `fibo, max_time=60`** (brief Decision 1):
  design D4 + Non-Goals consistent with frozen proposal.
- **`list_connected()` replaces `items()`** (brief Decision 2): design D5
  matches `list[ConnectedMachine]`.
- **`OccupancyConfig` field set is exact** — `start_occupancy_check` +
  `occupancy_check` use precisely the 5 Protocol fields, no more.
- **`download_outputs` return type** (design D2) matches frozen proposal
  signature exactly; `meta_add` flow and catch-all behaviour now
  documented.
- **D8 `update_machine`** correctly notes concrete exists
  (gateway.py:332-336) and orchestrator call site (orchestrator.py:277).
- **`my_backoff_sftp` SFTP variant** (D4) correctly derives from
  `my_backoff_exc`, swapping `SSHRetryExc`→`SFTPRetryExc`.
- **Deferred items not pulled into scope** — `_start_task_on_machine`,
  `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
  `_safe_b64decode`, `setup_node` all correctly excluded from D1–D8.

## design Round 4 — 2026-06-20

Note on numbering: this round re-verifies the 8 Round 3 Outstanding items
against the updated design.md and current source, then surveys cross-artifact
consistency and remaining gaps. All 8 Round 3 blockers are now resolved at
the design level.

### 🔴 Fixed

1. **D3 outer except widened to `(asyncssh.misc.Error, OSError)`** —
   design.md:85 now catches `(asyncssh.misc.Error, OSError) as err` instead
   of only `SSHRetryExc`. design.md:97-101 documents the coverage:
   `asyncssh.misc.Error` covers ALL asyncssh exceptions (including
   non-retryable `PermissionDenied`, `DisconnectError`); `OSError` covers
   network-level failures that are in `SSHRetryExc` but are not
   `asyncssh.misc.Error` subclasses. Re-verified the leak path Round 3 #1
   identified: `_open_connection` raising `PermissionDenied` is no longer
   in `SSHRetryExc` (correct — not retried by `@my_backoff_exc()` on
   `_connect_impl`), now caught by the outer wrapper and translated to
   `MachineConnectionError`. Goal "connect() failures surface as
   `MachineConnectionError`" now holds for both retryable and
   non-retryable transport errors. Closes Round 3 Outstanding #1.

2. **D1 enumerates the two `get_machine_state` refactoring sites** —
   design.md:41-45 now lists all four line transitions explicitly:
   `orchestrator.py:445` (`state = ...` → `machine = ...`),
   `:470` (`machine = state.machine` → removed),
   `:476` (`state = ...` → `machine = ...`),
   `:478` (`machine = state.machine` → removed). Re-verified all four
   sites present at the cited lines in orchestrator.py. Closes Round 3
   Outstanding #2.

3. **D5 enumerates the two `items()` refactoring sites** — design.md:132
   -134 now lists both: `orchestrator.py:323-327` (`_print_stats`) and
   `:513-517` (`_deallocator_producer`). The `_deallocator_producer`
   rewrite (drop `ip` dict key, recover via `m.ip`) is shown. Re-verified
   both sites present at the cited lines. Closes Round 3 Outstanding #3.

4. **D2 adds `task_id: int | None = None` parameter** — design.md:59
   adds the parameter to the `download_outputs` signature; design.md:69
   documents its purpose ("optional, used for log correlation ... "
   "Cannot download file for task_id=%s ..."; "Preserves operational
   traceability from current `_sftp_download_job`."). Re-verified the
   current `_sftp_download_job` log (consume_task.py:113-118) uses
   `task.task_id` in `"Cannot download file for task_id=%s from %s: %s"`.
   The regression is now remediated. Closes Round 3 Outstanding #4.

5. **D1 clarifies concrete `_get_machine_state` vs port `get_machine_state`**
   — design.md:39 states: "Concrete `SSHMachineGateway` keeps internal
   `_get_machine_state() -> _MachineState | None` for adapter-internal
   use (e.g., `check_status.py`). Port method `get_machine_state()`
   returns `ConnectedMachine | None` for application layer." This makes
   the dual-method structure explicit: a private concrete-only method
   for adapter consumers and a public Protocol method returning a domain
   entity. Closes Round 3 Outstanding #5.

6. **D4 specifies `run_bg` port return type as `None`** — design.md:119
   states: "`run_bg` port return type: `None`. Current concrete `run_bg`
   returns `SSHClientProcess` (adapter type — leaks into port).
   Orchestrator discards the return value (`orchestrator.py:250`). Port
   method returns `None`; concrete method keeps returning
   `SSHClientProcess` for internal use but port contract is `-> None`."
   Re-verified concrete `run_bg` (gateway.py:284-294) returns
   `SSHClientProcess` and orchestrator.py:250 discards the return.
   Adapter-type leak into the port is avoided. Closes Round 3
   Outstanding #6.

7. **D10 documents deferred helpers receiving concrete
   `SSHMachineGateway`** — design.md:197-214 adds D10 specifying that
   the `start_task_on_machine` callback receives the concrete
   `SSHMachineGateway`, not the Protocol, and that `Orchestrator.__init__`
   annotates `self._gateway: SSHMachineGateway`. The deferred helpers
   (`_start_task_on_machine`, `_upload_task_data`, `_exec_spawn_command`)
   can continue calling non-Protocol methods (`get_quote`, `get_sftp`,
   `get_hostname`, `get_path`, `run_bg`) without static-check failures.
   Closes Round 3 Outstanding #7.

8. **D9 adds `__len__` to Protocol** — design.md:186-195 adds D9 with
   `def __len__(self) -> int: ...`, citing orchestrator.py:607
   (`_await_first_machine` calls `len(self._gateway)`). Re-verified the
   call site and that concrete already defines `__len__`
   (gateway.py:539-540). Closes Round 3 Outstanding #8.

### 🟡 Addressed

1. **D1 does not enumerate the `check_status.py` refactoring site** —
   D1 design.md:47 says "Adapter-internal consumers (like `check_status.py`)
   use the private `_get_machine_state()` method", which implies but does
   not list the concrete refactoring obligation. Verified
   `adapters/cli/check_status.py:163` currently calls
   `gateway.get_machine_state(ip)` then `state.machine` (line 168). After
   D1's split, this site must change to `gateway._get_machine_state(ip)`
   (the body stays `state.machine` since `_MachineState` still has
   `.machine`). Also, design.md:39 says the concrete "keeps internal
   `_get_machine_state()`" — wording is slightly ambiguous: the existing
   method is `get_machine_state` (no underscore, gateway.py:328), so the
   change is "rename existing `get_machine_state` to `_get_machine_state`
   AND add a new public `get_machine_state` returning `ConnectedMachine`",
   not "keep an existing `_get_machine_state`". State the rename + new
   method operation explicitly, and list `check_status.py:163` as a
   refactoring site. (Adapter layer, so not a port violation — but the
   rename is a breaking change to a same-layer caller.)

2. **`disconnect` and `disconnect_all` have no design decision** — both
   are listed as new port methods in the brief table (explore-brief.md:33
   -34) and in proposal.md:7, and are actively called from application
   layer (orchestrator.py:546, orchestrator.py:711,
   application/deallocate_nodes.py:56). They have NO dedicated design
   decision and are not mentioned in any of D1–D10. Same pattern as the
   Round 2 #5 gap on `update_machine` (which got D8 added in Round 3).
   They are trivial (async, `(ip: str) -> None` / `() -> None`, no
   backoff, no adapter-type leak — verified at gateway.py:209,229) so
   they likely need no dedicated decision, but the design should
   acknowledge them with a one-line note (e.g., under D8: "`disconnect`
   and `disconnect_all` pass through unchanged; no design
   considerations"). Otherwise an implementer scanning D1–D10 may miss
   them when writing the spec delta.

3. **Goals section overpromises relative to D10** — design.md:21 lists
   Goal "Application layer depends only on `MachineGateway` Protocol
   (not `SSHMachineGateway`)" and "MachineGateway Protocol covers all
   methods application actually calls". D10 (design.md:197-214) keeps
   `self._gateway: SSHMachineGateway` as a concrete annotation in
   `Orchestrator.__init__` and the deferred helpers call non-Protocol
   methods (`get_quote`, `get_sftp`, `get_hostname`, `get_path`,
   `run_bg`) — verified at orchestrator.py:247,250,274,278,282. The
   Non-Goals section (design.md:28) acknowledges the deferral, but the
   Goals bullets remain overstated and now contradict D10. Soften the
   Goal wording (e.g., "Application layer depends only on
   `MachineGateway` Protocol, except for deferred helpers explicitly
   listed in Non-Goals") so the design does not contradict itself.

4. **`MachineConnectionError` constructor signature unspecified** — D3
   (design.md:86) uses `MachineConnectionError(ip, str(err))` (two-arg
   form) in the code example, but neither design nor proposal formally
   specifies the constructor. Existing domain exceptions follow
   consistent patterns: `MachineBusyError(ip)` (single arg,
   exceptions.py:92-97), `UnsupportedEngineError(engine_name)` (single
   arg, exceptions.py:39-44). An implementer writing
   `domain/exceptions.py` needs the exact signature and message format.
   Add a one-line spec in D3: e.g.,
   `MachineConnectionError(ip: str, detail: str)` with
   `super().__init__(f"cannot connect to {ip}: {detail}")`.

5. **Brief table does not reflect the `task_id` parameter added in D2** —
   explore-brief.md:42 still shows
   `download_outputs(ip, remote_dir, local_dir, files)` without
   `task_id`. Brief decision 4 (explore-brief.md:103) describes the
   return type but not the `task_id` parameter. The task description
   says "Brief updated with decisions 6-8" — the `task_id` addition
   (Round 4 expansion of decision 4) was not propagated. Minor
   cross-artifact drift; either update the brief table/signature or
   note that design.md is authoritative for the final signature.

6. **(Carry-over from Round 2 #4 / Round 3 🟡 #1) sync/async split
   remains partial** — design.md:147 classifies only `contains()` and
   `list_connected()` as sync. Verified at gateway.py that five other
   port methods are also sync and remain unclassified in the design:
   `list_free` (gateway.py:238 — sync despite being in original
   Protocol), `update_machine` (gateway.py:332), `get_machine_state`
   (gateway.py:328), `start_occupancy_check` (gateway.py:402), and the
   new `_get_machine_state`. An implementer writing the Protocol or a
   mock still has to discover this from the concrete class. Add a
   one-line classification table or expand the existing note.

### 🔴 Outstanding

None. All 8 Round 3 Outstanding items are resolved at the design level
and verified against current source. Remaining items in 🟡 Addressed
are minor completeness/consistency gaps that do not block
implementation but should be picked up before the design is archived.

### Verified correct (re-confirmed, no action)

- **Backoff params hardcoded `fibo, max_time=60`** (brief Decision 1):
  design D4 + Non-Goals consistent with frozen proposal Decisions.
- **`list_connected()` replaces `items()`** (brief Decision 2): design
  D5 matches `list[ConnectedMachine]`; refactoring sites now listed.
- **`OccupancyConfig` field set is exact** — `start_occupancy_check` +
  `occupancy_check` (gateway.py:344-443) dereference precisely the 5
  Protocol fields (`name`, `check_pname`, `check_cmd`,
  `check_cmd_code`, `sleep_interval`) at gateway.py:352,368,375,382,
  384,386,415,419,429; `config.Engine` (config/engine.py:119,121,124,
  154,155) satisfies the Protocol structurally.
- **`download_outputs` signature** (design D2) matches frozen proposal
  (proposal.md:22) on the return type; `meta_add` flow and catch-all
  behaviour documented; `task_id` parameter added for log correlation.
- **D3 two-method pattern** (`_connect_impl` + `connect`) preserves
  backoff retry on `SSHRetryExc` and translates post-exhaustion errors
  to `MachineConnectionError`; outer wrapper now covers the full
  `connect()` body (including `_open_connection`, `_detect_platform`,
  `get_cpu_cores`) via `_connect_impl`.
- **D8 `update_machine`** correctly notes concrete exists
  (gateway.py:332-336) and orchestrator call site (orchestrator.py:277).
- **D9 `__len__`** matches existing concrete (gateway.py:539-540).
- **`my_backoff_sftp` SFTP variant** (D4) correctly derives from
  `my_backoff_exc`, swapping `SSHRetryExc`→`SFTPRetryExc`.
- **Deferred items not pulled into scope** — `_start_task_on_machine`,
  `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
  `_safe_b64decode`, `setup_node` all correctly excluded from D1–D10.

### Recommendation

**APPROVE WITH NOTES.** All 8 Round 3 blocking issues are resolved. The
6 🟡 Addressed items are minor consistency/completeness gaps (the
`disconnect`/`disconnect_all` omission and the Goals-vs-D10 tension are
the most useful to address before archive). None block implementation.

## specs Round 1 — 2026-06-20

Reviewed all 5 delta spec files against frozen `proposal.md`, `design.md`
(D1–D10 incl. D6b), and `explore-brief.md`. Also cross-checked existing
main specs to confirm MODIFIED requirements carry full updated content
and ADDED/MODIFIED placement is sensible. Verified scenario signatures
against current source (`consume_task.py:272`, `allocate_task.py:219`).
`openspec validate gateway-port-cleanup --strict` passes.

### 🔴 Fixed

None. Round 1 review — no fixes applied yet.

### 🟡 Addressed

1. **`Backoff on gateway methods` is a NEW requirement but lives under
   `## MODIFIED Requirements`** (`ssh-gateway/spec.md:78`). The existing
   main spec (`openspec/specs/ssh-gateway/spec.md`) has 6 requirements;
   none is `Backoff on gateway methods`. Repo convention (verified across
   `archive/2026-06-19-*` changes) places genuinely new requirements
   under `## ADDED Requirements`. `openspec validate` passes either way
   (it does not enforce section-vs-requirement-name semantics), but
   archive-time sync and human reviewers expect the section header to
   match the delta kind. Either split the file into `## ADDED
   Requirements` (for `Backoff on gateway methods`) + `## MODIFIED
   Requirements` (for the other two), or move the new requirement into
   its own delta spec file under `## ADDED Requirements`.

2. **`Consume loop` requirement hosts two scenarios that are not
   consume-loop** (`orchestrator/spec.md:55`). The requirement body
   itself is about polling RUNNING tasks and dispatching to
   `consume_task`, but its scenarios include:
   - `Stats uses list_connected` — about `_print_stats` (belongs in
     `Stats logging` per `orchestrator.py:323-327` / design D5)
   - `Deallocator uses list_connected` — about `_deallocator_producer`
     (belongs in `Deallocate loop` per `orchestrator.py:513-517` /
     design D5)
   The information is correct and traceable, but the placement
   contradicts the requirement's stated scope and will confuse
   implementers writing tests against the "Consume loop" requirement.
   Cleaner split: modify `Stats logging` and `Deallocate loop`
   requirements to carry their respective `list_connected` scenarios,
   and leave `Consume loop` with only the consume-specific scenario.

3. **`SSH connection retry` requirement omits the exception coverage
   tuple** (`ssh-gateway/spec.md:3`). Design D3 (`design.md:85,97-101`)
   explicitly widens the outer wrapper to
   `except (asyncssh.misc.Error, OSError)`. The spec only says
   "translates exhausted exceptions to `MachineConnectionError`" — an
   implementer reading the spec alone can miss that BOTH
   `asyncssh.misc.Error` AND `OSError` must be caught (the latter
   covers network-level failures in `SSHRetryExc` that are not
   `asyncssh.misc.Error` subclasses). Add an explicit clause or
   scenario: "WHEN `connect` raises `OSError` after backoff exhaustion
   THEN it is translated to `MachineConnectionError`".

4. **Several newly-added port methods have no scenario**
   (`domain-ports/spec.md:8-33`). The `MachineGateway port` requirement
   gains 11 scenarios but skips: `disconnect`, `disconnect_all`,
   `run_bg`, `upload`, `download`, `__len__`. Most notable is `__len__`
   (D9 — explicitly added so `len(self._gateway)` in
   `_await_first_machine` type-checks against the Protocol). A short
   scenario ("WHEN `len(gateway)` is called THEN it returns the count of
   currently registered `ConnectedMachine`s") would lock in the D9
   contract and give reviewers something to test against. `upload` /
   `download` are covered at the adapter side (`ssh-gateway/spec.md:49
   -55`) so the gap is purely on the port surface.

5. **`MachineConnectionError` constructor signature remains implicit**
   (`domain-exceptions/spec.md:3`). Round 4 🟡 #4 flagged the same gap
   in design D3. The spec scenarios demonstrate usage
   (`MachineConnectionError("10.0.0.1", "Connection refused")` and
   `e.ip == "10.0.0.1"`) but never state the formal signature
   `MachineConnectionError(ip: str, detail: str)` or the message format
   (e.g., `f"cannot connect to {ip}: {detail}"`). Existing domain
   exceptions follow strict single-arg patterns
   (`MachineBusyError(ip)`, `UnsupportedEngineError(engine_name)`);
   `MachineConnectionError` is the first two-arg form and deserves an
   explicit signature line so the implementer of
   `domain/exceptions.py` does not have to infer it from scenarios.

6. **`OccupancyConfig` Protocol is bundled into the `MachineGateway
   port` requirement** (`domain-ports/spec.md:30,35-40`). This is
   defensible (it has a single consumer), but for symmetry with how
   `MachineConnectionError` got its own requirement in
   `domain-exceptions`, `OccupancyConfig` could be its own Requirement
   block ("`OccupancyConfig` port Protocol") with its own scenarios
   (e.g., "`config.Engine` satisfies `OccupancyConfig` structurally").
   This would also give D7 (`design.md:161-185`) a cleaner spec anchor.
   Optional — bundling is not wrong, just less navigable.

7. **No scenario verifies the D10 deferred-helpers exception**
   (`orchestrator/spec.md:12-15`). The requirement body correctly
   states the orchestrator keeps `self._gateway: SSHMachineGateway` for
   deferred helpers, but there is no scenario asserting e.g. "WHEN
   `_start_task_on_machine` runs THEN it may call non-Protocol methods
   (`get_sftp`, `get_path`, `get_quote`, `run_bg`) on the concrete
   gateway". Adding one would make the deliberate-scope-creep visible
   to future readers who might otherwise see `MachineGateway` in the
   signature and assume the concrete type is gone.

### 🔴 Outstanding

None. All D1–D10 (including D6b) decisions are captured. Every
requirement has at least one scenario. All scenarios use the `####`
format. SHALL is used consistently for normative requirements (no MUST,
no SHOULD). MODIFIED requirements carry full updated content. The
deferred items (`_start_task_on_machine`, `_upload_task_data`,
`_exec_spawn_command`, `_write_remote_file`, `_safe_b64decode`,
`setup_node`) are correctly excluded from the port surface — they
appear only in the orchestrator requirement body as the D10
justification for keeping the concrete annotation. No contradictions
with `proposal.md` or `design.md`. `asyncssh` is correctly NOT in the
banned-imports list (matches the proposal's deferred-helpers note).
The 🟡 items above are structural/completeness improvements that do
not block implementation.

### Verified correct (no action needed)

- **D1 dual `get_machine_state`**: `domain-ports/spec.md:16` returns
  `ConnectedMachine | None`; `ssh-gateway/spec.md:36-38` documents both
  the private `_get_machine_state -> _MachineState | None` and the
  public `get_machine_state -> ConnectedMachine | None`; scenarios at
  `ssh-gateway/spec.md:70-76` cover both.
- **D2 `download_outputs`**: signature with `task_id: int | None = None`
  captured at `domain-ports/spec.md:27`; `(meta_add, sftp_errors)` flow
  and catch-all behavior at `ssh-gateway/spec.md:30-34,57-64`.
- **D3 two-method pattern**: `_connect_impl` with `@my_backoff_exc()` +
  outer `connect` translation captured at `ssh-gateway/spec.md:3-21`
  with 3 scenarios.
- **D4 backoff on 4 methods + `my_backoff_sftp`**: `ssh-gateway/
  spec.md:78-99` applies `@my_backoff_exc()` to `run_bg, get_cpu_cores`
  and `@my_backoff_sftp()` to `upload, download`, with 4 scenarios.
- **D5 `list_connected` replaces `items()`**: signature at
  `domain-ports/spec.md:14`; refactoring sites acknowledged in
  orchestrator scenarios (placement issue flagged above).
- **D6 `contains` + D6b `disconnect`/`disconnect_all` + D8
  `update_machine` + D9 `__len__`**: all present in port signature
  list at `domain-ports/spec.md:9-18`.
- **D7 `OccupancyConfig`**: full attribute set (`name`, `check_pname`,
  `check_cmd`, `check_cmd_code`, `sleep_interval`) at
  `domain-ports/spec.md:35-40`; matches `gateway.py` field
  dereferences.
- **D10 deferred helpers**: captured at `orchestrator/spec.md:12-15`
  with explicit reference to the helpers and the future-change intent.
- **Cross-artifact signature consistency**: `consume_task` and
  `allocate_task` scenario call signatures in `use-cases/spec.md:17,36`
  match current source (`consume_task.py:272-280`, `allocate_task.py
  :219-226`) — `ip` and `clouds` (plural) confirmed.
- **TYPE_CHECKING carve-out**: orchestrator and use-cases scenarios
  correctly allow `TYPE_CHECKING` imports while banning runtime
  adapter imports.
- **`asyncssh` not over-banned**: matches proposal's deferred-helpers
  note (`asyncssh` remains in `orchestrator.py` for
  `_write_remote_file` / `_upload_task_data`).
- **Scenario hashtag format**: every scenario across all 5 files uses
  exactly `####` (verified by `grep -rh "^#### " …` vs `grep -rh
  "^### " …`).
- **Normative keyword usage**: only `SHALL` / `SHALL NOT` used (no
  bare indicative mood for normative claims, no orphan `MUST`/
  `SHOULD`).
- **`openspec validate gateway-port-cleanup --strict`**: passes with
  zero issues.

### Recommendation

**APPROVE WITH NOTES.** No blocking issues. The 7 🟡 Addressed items
are minor structural/completeness improvements; the most useful to
pick up before archive are #1 (ADDED vs MODIFIED section for `Backoff
on gateway methods`) and #2 (mis-placed scenarios in `Consume loop`).
The remaining items can be deferred to a follow-up spec-polish pass
without risk to implementation.

## tasks Round 1 — 2026-06-20

Reviewed `tasks.md` (44 tasks across 8 sections) against frozen
`proposal.md`, `design.md` (D1–D10 incl. D6b), all 5 delta specs, and
`explore-brief.md`. Cross-checked every design decision and spec
requirement against task coverage; verified each task against current
source (`consume_task.py`, `allocate_task.py`, `orchestrator.py`,
`gateway.py`, `deallocate_nodes.py`, `check_status.py`,
`knowledge-graph.xml`).

### Coverage matrix (verified)

- **D1–D10 all mapped**: D1→3.7+6.6; D2→2.5+3.9+4.2/4.3; D3→3.6+6.3;
  D4→3.1–3.5; D5→2.3+3.8+6.4/6.5; D6→2.3; D6b→2.2; D7→2.1+2.6;
  D8→2.3; D9→2.3; D10→6.7.
- **Spec requirements all covered** (with the `deallocate_nodes.py`
  gap noted in Outstanding #1): domain-exceptions→1.1/1.2;
  domain-ports→2.1–2.9; ssh-gateway→3.1–3.9; orchestrator→6.1–6.7;
  use-cases→4.1–4.4, 5.1.
- **Dependency ordering correct at section level**: domain (1–2) →
  adapter (3) → application (4–6) → tests (7) → GRACE artifacts (8).
- **No deferred items pulled in**: `_start_task_on_machine`,
  `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
  `_safe_b64decode`, `setup_node` — none appear as tasks. Task 6.7
  only acknowledges the deferral by keeping the concrete annotation.
- **Pre-existing Protocol methods not re-listed**: `list_free`, `run`,
  `upload`, `download` correctly omitted from new-method tasks.

### 🔴 Fixed

None. Round 1 review — no fixes applied yet.

### 🟡 Addressed

1. **`deallocate_nodes.py` application-layer refactor is missed**
   Proposal Goal: "Replace concrete types with Protocol —
   `SSHMachineGateway` type annotations replaced with `MachineGateway`
   Protocol in application layer". Verified `deallocate_nodes.py:52`
   annotates `gateway: SSHMachineGateway` and `:55` calls
   `gateway.keys()` (NOT in the Protocol; same family as the
   `items()` leak that D5 fixes in orchestrator). Tasks 4.x and 5.x
   cover only `consume_task.py` and `allocate_task.py`; the proposal's
   Impact file list omits `deallocate_nodes.py` without rationale. The
   file is application layer and has the identical port-bypass pattern
   this change exists to remove. Either (a) add a task under section 5
   or 6: "Change type annotation in `deallocate_nodes.py:52` from
   `SSHMachineGateway` to `MachineGateway` and replace
   `gateway.keys()` membership check at `:55` with
   `gateway.contains(node.ip)` (D6)"; or (b) add it to the proposal's
   Out of Scope with explicit rationale. (Listed as Outstanding #1
   until resolved.)

2. **No task verifies the change's central invariant — "no adapter
   runtime imports in application layer"**
   This is the proposal's headline Goal ("Application layer has zero
   runtime imports from `yascheduler.adapters`"). Tasks 7.1–7.5 cover
   behavioural scenarios, but none asserts the import-purity invariant
   itself. A regression that re-introduces `import backoff` or
   `from yascheduler.adapters import AllSSHRetryExc` in
   `orchestrator.py` / `consume_task.py` would pass every existing
   test. Add a task under section 7: e.g., a static AST/import test
   that asserts the banned symbols (`AllSSHRetryExc`, `SFTPRetryExc`,
   `SFTPError`, runtime `backoff`) do not appear in the runtime
   import scope of the application modules. Cheap to write, locks in
   the Goal, catches the most likely regression vector.

3. **Task 8.1 knowledge-graph update is incomplete — `M-SSH-GATEWAY`
   omitted**
   Task 8.1 only mentions `M-DOMAIN-EXCEPTIONS` and `M-DOMAIN-PORTS`.
   Verified `docs/knowledge-graph.xml:729-750` `M-SSH-GATEWAY`
   annotations list `get_machine_state` (will be renamed to
   `_get_machine_state` per Task 3.7) and lack `download_outputs` and
   `list_connected` (added by Tasks 3.8 and 3.9). Per GRACE-lite rule
   "public API changed → `<annotations>`", M-SSH-GATEWAY needs: rename
   `get_machine_state` → `_get_machine_state` PURPOSE update; add
   `fn-download_outputs` and `fn-list_connected` entries. Expand
   Task 8.1 to include `M-SSH-GATEWAY`.

4. **GRACE-lite artifacts placed at END, violating criterion 6
   (top-down ordering)**
   Review criterion 6 requires "knowledge graph → module contracts →
   function contracts → code". Tasks 8.x are the LAST section, after
   all code tasks. GRACE-lite Principle 1 states "Create/update
   MODULE_CONTRACT before code." Recommended restructure: split
   section 8 — move the knowledge-graph entry (8.1) and the
   MODULE_CONTRACT updates (8.2, 8.3) to BEFORE their corresponding
   code sections (e.g., 1.0/2.0: update `domain/exceptions.py` and
   `domain/ports.py` MODULE_CONTRACT and knowledge-graph first); keep
   CHANGE_SUMMARY (8.4) and `grace_check.py` run (8.5) at the end
   (those are inherently post-code).

5. **No tasks for adding `START_CONTRACT:` to new public methods**
   GRACE-lite methodology: "Required: core business logic, exported
   functions, public methods". The change adds several new public
   methods/functions that should carry `START_CONTRACT:`/`END_CONTRACT:`
   blocks per the existing pattern in `gateway.py` (verified:
   `run_bg`, `upload`, `download`, `get_sftp`, `occupancy_check`,
   etc. all have contracts). New methods requiring contracts:
   `download_outputs` (Task 3.9), new public `connect` two-method
   wrapper (Task 3.6), new public `get_machine_state` returning
   `ConnectedMachine | None` (Task 3.7), `list_connected` (Task 3.8),
   `OccupancyConfig` Protocol (Task 2.1). Tasks 8.2/8.3 only cover
   MODULE_CONTRACT and MODULE_MAP — not function-level contracts.
   Either add a task "Add `START_CONTRACT:` blocks to all new public
   methods per existing pattern" or expand 8.2/8.3 to enumerate them.

6. **Tasks 8.2/8.3 only cover domain files — `gateway.py`,
   `orchestrator.py`, `consume_task.py`, `allocate_task.py`
   MODULE_MAPs also need updates**
   Verified all 6 modified files have `START_MODULE_CONTRACT` /
   `START_MODULE_MAP` markers. The 4 non-domain files' MODULE_MAPs
   will change (e.g., `gateway.py` MODULE_MAP gains `download_outputs`,
   `list_connected`, `_get_machine_state`; `orchestrator.py` MODULE_MAP
   should reflect removal of `@backoff` decorator and import cleanup;
   `consume_task.py` MODULE_MAP should reflect deletion of
   `_sftp_download_job` / `_download_task_outputs`). Task 8.4
   (CHANGE_SUMMARY) is bundled into one task covering "modified files"
   but MODULE_MAP updates for the 4 non-domain files are not
   separately acknowledged. Either expand Task 8.4 to explicitly list
   each file's MODULE_MAP changes, or add per-file MODULE_MAP update
   tasks.

7. **Task 3.9 (`download_outputs`) likely exceeds the ~2-hour session
   budget**
   The task combines: SFTP session management, per-file retry logic,
   remote directory cleanup, catch-all exception handling, and optional
   `task_id` logging. Effectively reimplements two existing helpers
   (`_sftp_download_job` + `_download_task_outputs`, ~70 LOC combined
   per `consume_task.py:96-161`). Consider splitting into:
   3.9a (skeleton + SFTP session open/close + meta_add construction),
   3.9b (per-file download with retry + sftp_errors collection +
   `task_id` logging), 3.9c (remote dir cleanup + outer catch-all +
   return tuple). Each is then ~30–60 min.

8. **Task 7.3 (`MachineConnectionError` unit test) does not specify
   location**
   Verified `tests/unit/test_domain_exceptions.py` exists (alongside
   `test_machine_gateway_protocol` placement convention). Task 7.3
   should name the target file to remove ambiguity; the natural home
   is `test_domain_exceptions.py`.

9. **Tests do not cover 4 spec scenarios for backoff on `run_bg`,
   `upload`, `download`, `get_cpu_cores`**
   `ssh-gateway/spec.md:87-100` defines 4 backoff scenarios. Tasks
   3.2–3.5 add the decorators but no task verifies they actually retry.
   A simple unit test using a fake that raises `SSHRetryExc` /
   `SFTPRetryExc` N times then succeeds would lock in D4 behaviour.
   Optionally add a task under section 7. (Pre-existing
   `test_ssh_gateway.py:TestConnectionLifecycle` may already cover
   similar territory for `connect` — worth checking before adding
   duplicates.)

10. **Tests do not cover `list_connected` behaviour nor the
    `_connect_machine_consumer` → `MachineConnectionError` catch**
    Two spec scenarios lack any test mapping:
    - `domain-ports/spec.md:50-52` "List all connected machines" — no
      test asserts `list_connected()` returns the registered
      `ConnectedMachine` list.
    - `orchestrator/spec.md:39-41` "Connection failure caught as
      domain error" — no test asserts `_connect_machine_consumer`
      catches `MachineConnectionError` (the round-3/4 fix that made
      the outer wrapper catch `(asyncssh.misc.Error, OSError)`).
    Adding tasks for these would close the loop on D3 and D5 at the
    behaviour level.

### 🔴 Outstanding

1. **`deallocate_nodes.py` is in-scope per the proposal Goal but has
   no task and is omitted from the proposal Impact file list**
   Verified at `application/deallocate_nodes.py:52,55`:
   `gateway: SSHMachineGateway` annotation and
   `if node.ip in gateway.keys():` — `keys()` is not in the
   `MachineGateway` Protocol (only `__len__`, `contains`,
   `list_connected` are). This is the same port-bypass pattern
   (`items()` in orchestrator) that D5 fixes; leaving it unfixed
   means the change ships with a known port leak in the application
   layer, contradicting the proposal's headline Goal
   ("Application layer bypasses the Protocol and uses the concrete
   class directly"). Resolve by either: (a) adding a task
   "5.2 Change `deallocate_nodes.py:52` type annotation to
   `MachineGateway`; replace `:55` `gateway.keys()` membership with
   `gateway.contains(node.ip)`"; AND updating `proposal.md` Impact
   to include `application/deallocate_nodes.py`; or (b) explicitly
   adding `deallocate_nodes.py` to Out of Scope with rationale and
   softening the Goal wording to "application layer except
   `deallocate_nodes.py` (deferred to follow-up)". (See Addressed #1.)

### Verified correct (no action needed)

- **All design decisions D1–D10 mapped to tasks** — verified
  one-to-one (see Coverage matrix above).
- **Section-level dependency ordering correct** — domain (1–2) →
  adapter (3) → application (4–6) → tests (7) → GRACE (8). No
  forward references (e.g., application code does not call a port
  method before that method is added in section 2).
- **No deferred items pulled into scope** — `_start_task_on_machine`,
  `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
  `_safe_b64decode`, `setup_node` correctly absent from tasks.
  Task 6.7 keeps concrete annotation solely to support deferred
  helpers per D10.
- **Task granularity generally appropriate** — most tasks (1.1, 1.2,
  2.x, 3.1–3.8, 4.1, 4.3, 4.4, 5.1, 6.1–6.7) are small, atomic, and
  independently completable. Task 3.9 is the only clear outlier
  (see Addressed #7).
- **Call-site references in tasks are accurate** — verified
  orchestrator.py:445/470/476/478 (Task 6.6), 323-327 (Task 6.4),
  513-517 (Task 6.5), 391 (Task 6.3); consume_task.py:32-35 (Task
  4.1 — actually lines 32, 33, 35); check_status.py:163 (Task 3.10).
- **Tasks 4.1 and 6.1 correctly preserve `asyncssh` import** in
  orchestrator.py for deferred helpers per proposal.md:11 and D10.
- **Knowledge-graph entries referenced in 8.1 exist** — M-DOMAIN-
  EXCEPTIONS (kg:223), M-DOMAIN-PORTS (kg:260) both verified present.
- **Task 3.10 (`check_status.py` uses `_get_machine_state`)**
  correctly identified — verified `adapters/cli/check_status.py:163`
  calls `gateway.get_machine_state(ip)` then `state.machine` (line
  168); after D1 split, this site must switch to the private
  `_get_machine_state` to preserve `.machine` access.
- **All 5 existing test files referenced by tasks 7.1–7.5 exist** —
  `test_application_use_cases.py`, `test_application_orchestrator.py`,
  `test_ssh_gateway.py`, `test_domain_exceptions.py`,
  `test_domain_ports.py` all present.
- **Section 7 covers the change's main behavioural scenarios** —
  download_outputs catch-all (7.4), connect retry+translate (7.5),
  consume_task mocked (7.1), orchestrator mocked via Protocol (7.2),
  MachineConnectionError attributes (7.3).

### Recommendation

**REQUEST CHANGES.** One blocking issue: `deallocate_nodes.py` is an
application-layer file that the proposal Goal explicitly targets but
neither the tasks nor the proposal Impact file list covers. The file
calls `gateway.keys()` (a non-Protocol method, same family as the
`items()` leak D5 fixes) and annotates the gateway with the concrete
`SSHMachineGateway` type. Either pull it into scope (preferred —
small, mechanical, completes the Goal) or formally defer it with
softened Goal wording. The remaining 🟡 items are quality/completeness
gaps that do not individually block, but #2 (no import-purity test),
#3 (M-SSH-GATEWAY knowledge-graph gap), and #5 (no START_CONTRACT
tasks) are worth picking up before implementation begins.

## tasks Round 2 — 2026-06-20

Re-reviewed `tasks.md` (44 tasks across 10 sections) after the Round 1
REQUEST CHANGES. Re-verified every Round 1 item against the updated
`tasks.md`, frozen `proposal.md`, `design.md` (D1–D10 incl. D6b), the 5
delta specs, and current source (`deallocate_nodes.py:52,55`,
`orchestrator.py:100,192,325,391,513,544,546,711`, `consume_task.py:32
-35,96-161,290-292`, `gateway.py:149,284-315,328-330,530-540`,
`tests/unit/test_domain_exceptions.py`).

### 🔴 Fixed

1. **(Round 1 Outstanding #1 / Addressed #1) `deallocate_nodes.py`
   pulled into scope** — Tasks 7.1 and 7.2 added. Task 7.1 changes the
   `gateway: SSHMachineGateway` annotation at `deallocate_nodes.py:52`
   to `MachineGateway`; Task 7.2 replaces the non-Protocol
   `gateway.keys()` membership check at `:55` with
   `gateway.contains(node.ip)` (D6 method). Re-verified both the
   annotation and the `keys()` call are present at the cited lines.
   Note: `proposal.md` Impact file list (proposal.md:46) still omits
   `application/deallocate_nodes.py` — see Outstanding #1 below.

### 🟡 Addressed

1. **(Round 1 #2) Import-purity invariant now has a test** — Task 9.6
   added: "Add import hygiene test — verify no adapter runtime imports
   (`AllSSHRetryExc`, `SFTPRetryExc`, `SFTPError`, `backoff`) in
   application layer modules." This locks in the proposal's headline
   Goal and catches the most likely regression vector. The four banned
   symbols match the per-file import removal in Tasks 5.1 and 8.1
   (verified at `consume_task.py:32,33,35` and `orchestrator.py:35,37`).

2. **(Round 1 #3) `M-SSH-GATEWAY` knowledge-graph update added** —
   Task 1.1 now includes "update M-SSH-GATEWAY annotations (rename
   `get_machine_state`→`_get_machine_state`, add `download_outputs`,
   `list_connected`)". Verified `docs/knowledge-graph.xml` M-SSH-GATEWAY
   exists and currently lists `get_machine_state` (will be renamed per
   Task 4.7) and lacks `download_outputs`/`list_connected` (added by
   Tasks 4.8–4.11). Matches GRACE-lite rule "public API changed →
   `<annotations>`".

3. **(Round 1 #4) Top-down GRACE ordering adopted** — Tasks split:
   Section 1 (knowledge-graph + MODULE_CONTRACT for the two domain
   files) at the TOP before any code; Section 10 (CHANGE_SUMMARY +
   START_CONTRACT + `grace_check.py` run) at the BOTTOM after all code
   + tests. Satisfies GRACE-lite Principle 1 ("Create/update
   MODULE_CONTRACT before code") and Criterion 6 (knowledge graph →
   module contracts → function contracts → code).

4. **(Round 1 #5) START_CONTRACT task added** — Task 10.2 added: "Add
   `START_CONTRACT:` blocks for new public methods (`download_outputs`,
   `list_connected`, `OccupancyConfig`)". Matches existing `gateway.py`
   pattern (verified: `run_bg`, `upload`, `download`, `get_sftp`,
   `occupancy_check`, `start_occupancy_check` all carry contracts).
   Coverage is partial — see Outstanding #3.

5. **(Round 1 #7) `download_outputs` task split into subtasks** —
   Tasks 4.9 (SFTP session + per-file retry + remote cleanup), 4.10
   (catch-all exception handling → `sftp_errors`), 4.11 (`task_id`
   parameter for log correlation) break the original monolithic 3.9
   into ~3 × 30–60 min slices. Each slice maps cleanly to design D2
   responsibilities (design.md:63-69).

### 🔴 Outstanding

1. **(Carry-over) `proposal.md` Impact file list still omits
   `application/deallocate_nodes.py`** — Round 1 flagged the task gap
   AND the proposal Impact omission. Tasks 7.1/7.2 close the task gap,
   but `proposal.md:46` "Impact > Code" still reads: `domain/ports.py`,
   `domain/exceptions.py`, `adapters/ssh/gateway.py`,
   `application/orchestrator.py`, `application/consume_task.py`,
   `application/allocate_task.py` — no `deallocate_nodes.py`. With the
   tasks now modifying that file, the proposal's Impact list is
   inconsistent with both `tasks.md` and the change's actual surface.
   Trivial fix: append `application/deallocate_nodes.py` to
   `proposal.md:46`. (Not a `tasks.md` defect, but the tasks round is
   the natural place to surface the inconsistency since it becomes
   visible only after Task 7.x is added.)

2. **(Carry-over from Round 1 #6) Task 10.1 only covers CHANGE_SUMMARY,
   not MODULE_MAP updates for the 4 non-domain modified files** —
   Task 10.1 reads "Update CHANGE_SUMMARY in all modified files".
   Per GRACE-lite rule "After editing: update MODULE_MAP if public
   surface changed", four files need MODULE_MAP edits that 10.1 does
   not enumerate:
   - `gateway.py` MODULE_MAP gains `download_outputs`, `list_connected`,
     `_get_machine_state` (and the MODULE_MAP currently only lists
     `_MachineState`, `_open_connection`, `SSHMachineGateway` — verified
     at gateway.py:10-14).
   - `consume_task.py` MODULE_MAP loses `_sftp_download_job` and
     `_download_task_outputs` (verified at consume_task.py:13-14).
   - `orchestrator.py` MODULE_MAP unchanged in surface but
     `Orchestrator` description should reflect Protocol typing.
   - `allocate_task.py` MODULE_MAP: minor — type annotation only.
   `grace_check.py` (Task 10.3) will likely catch any miss, but the
   task should at least name MODULE_MAP explicitly so the implementer
   does not treat 10.1 as "CHANGE_SUMMARY only". Expand Task 10.1 to
   "Update CHANGE_SUMMARY and MODULE_MAP in all modified files" or
   split MODULE_MAP into its own task.

3. **(Carry-over / partial) Task 10.2 START_CONTRACT coverage is
   incomplete** — Task 10.2 names only `download_outputs`,
   `list_connected`, `OccupancyConfig`. Round 1 #5 enumerated 5
   candidates; 2 are still uncovered:
   - `_connect_impl` (Task 4.6) — new public-ish method on
     `SSHMachineGateway`, decorated with `@my_backoff_exc()`. Per the
     existing pattern (`connect`, `disconnect`, `_open_connection` all
     carry contracts in `gateway.py:102-148,205-208`), `_connect_impl`
     should too.
   - New public `get_machine_state` returning `ConnectedMachine | None`
     (Task 4.7). The existing one-line `get_machine_state`
     (gateway.py:328-330) has no contract, but after Task 4.7 it becomes
     a public port method returning a domain entity — deserves a
     `START_CONTRACT`.
   - (Existing `connect` contract at gateway.py:144-148 needs its
     PURPOSE/SIDE_EFFECTS updated to reflect the two-method split —
     arguably part of Task 10.1, not 10.2.)
   Also: Task 10.2 says "new public methods" but does not mention
   updating START_CONTRACT blocks for functions whose *signatures*
   changed without being new — `consume_task` (gateway type annotation
   → `MachineGateway`, Task 5.4) and `deallocate_node` (same, Task 7.1)
   both have START_CONTRACT blocks (verified at consume_task.py:257-271,
   deallocate_nodes.py:39-49) that name `SSHMachineGateway` in INPUTS.
   Those contracts need updating even though the functions are not
   "new". Either widen Task 10.2 wording to "new and signature-changed
   public methods" or add a task for contract-text updates.

4. **(Carry-over from Round 1 #8) Task 9.3 does not name the target
   test file** — Task 9.3 reads "Add unit test for
   `MachineConnectionError` — verify attributes and inheritance" with
   no file path. Verified `tests/unit/test_domain_exceptions.py` exists
   and already hosts the analogous `test_machine_busy_error`
   (line 157) — natural home for the new test. Naming the file would
   remove ambiguity for the implementer and matches how Tasks 9.1, 9.2
   implicitly target `test_application_use_cases.py` /
   `test_application_orchestrator.py` (verifiable from existing tests,
   but 9.1/9.2 do not name them either — same minor pattern).

5. **(Carry-over from Round 1 #9) No test tasks for the 4 backoff
   scenarios in `ssh-gateway/spec.md:87-100`** — Tasks 4.2–4.5 add the
   `@my_backoff_exc()`/`@my_backoff_sftp()` decorators but no task
   verifies they actually retry. Spec has 4 scenarios
   (`run_bg retries`, `upload retries`, `download retries`,
   `get_cpu_cores retries`) with no test mapping. A simple test using a
   fake that raises `SSHRetryExc`/`SFTPRetryExc` N times then succeeds
   would lock in D4. Optional but cheap; the spec scenarios otherwise
   have no behaviour-level verification.

6. **(Carry-over from Round 1 #10) No test task for `list_connected`
   behaviour** — `domain-ports/spec.md` and `ssh-gateway/spec.md:66-68`
   define the `list_connected()` scenario but Tasks 9.x do not cover
   asserting `list_connected()` returns the registered
   `ConnectedMachine` list. Task 9.5 covers the connect two-method
   pattern (the other half of Round 1 #10) — the `list_connected` half
   remains unaddressed.

7. **(NEW) Tasks 5.2 and 5.3 overlap confusingly** — Task 5.2 says
   "Replace `_sftp_download_job` and `_download_task_outputs` with
   `gateway.download_outputs()` call" (i.e., delete both helpers).
   Task 5.3 then says "Update `_download_task_outputs` call site to
   receive `(meta_add, sftp_errors)` tuple". If 5.2 deletes
   `_download_task_outputs`, there is no "call site" of it left to
   update — the only site is the call inside `consume_task` itself
   (`consume_task.py:290-292`), which 5.2 already rewires to
   `gateway.download_outputs()`. 5.3 adds nothing 5.2 does not, and the
   wording suggests `_download_task_outputs` survives. Either drop 5.3
   (5.2 covers the whole replacement) or split cleanly: 5.2 = delete
   `_sftp_download_job`; 5.3 = rewrite `_download_task_outputs` body to
   call `gateway.download_outputs()` and unpack the tuple (keeping the
   wrapper as a thin adapter so the `consume_task` call site is
   untouched). Pick one interpretation and make the tasks reflect it.

8. **(NEW) Task 1.1 M-SSH-GATEWAY wording under-counts the new public
   method** — Task 1.1 says "rename `get_machine_state`→
   `_get_machine_state`" plus "add `download_outputs`, `list_connected`".
   But Task 4.7 introduces a NEW public `get_machine_state` returning
   `ConnectedMachine | None` (distinct from the renamed private one).
   So M-SSH-GATEWAY annotations gain a new `fn-get_machine_state` entry
   in addition to renaming the existing one — Task 1.1 does not mention
   this add. Minor, but a precise task prevents the graph update from
   dropping the new public method.

### Verified correct (no action needed)

- **All Round 1 Outstanding items resolved at the task level** —
  `deallocate_nodes.py` covered by Tasks 7.1, 7.2 (verified source
  matches the task description).
- **All design decisions D1–D10 still mapped to tasks** — D1→3.7+8.6;
  D2→3.5+4.9/4.10/4.11+5.2/5.3; D3→3.2+4.6+8.3; D4→3.4+4.1–4.5;
  D5→3.3+8.4/8.5; D6→3.3+7.2; D6b→3.2; D7→3.1+3.6; D8→3.3; D9→3.3;
  D10→8.7.
- **Section-level dependency ordering correct** — Section 1 (GRACE
  planning) → 2 (exceptions) → 3 (ports) → 4 (adapter) → 5-7
  (application: consume / allocate / deallocate) → 8 (orchestrator) →
  9 (tests) → 10 (GRACE finalize). No forward references.
- **No deferred items pulled into scope** — `_start_task_on_machine`,
  `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
  `_safe_b64decode`, `setup_node` correctly absent. Task 8.7 keeps
  concrete annotation solely for deferred helpers per D10.
- **Call-site references in tasks are accurate** — re-verified
  orchestrator.py:445/470/476/478 (Task 8.6), 323-327 (Task 8.4),
  513-517 (Task 8.5), 391 (Task 8.3), 411 (Task 8.2);
  consume_task.py:32,33,35 (Task 5.1); deallocate_nodes.py:52,55
  (Tasks 7.1, 7.2); check_status.py:163 (Task 4.12).
- **Task 5.1 banned-import list matches source** — verified
  `import backoff` (line 32), `from asyncssh.sftp import SFTPError`
  (line 33), `from yascheduler.adapters import SFTPRetryExc` (line 35).
- **Task 8.1 correctly preserves `asyncssh` import** in
  orchestrator.py for deferred helpers (`_write_remote_file`:100,
  `_upload_task_data`:192) per proposal.md:11 and D10.
- **Task 9.5 covers connect catch half of Round 1 #10** — "verify
  retry then translate" maps to `orchestrator/spec.md:39-41` "Connection
  failure caught as domain error".
- **Test files referenced or implied by 9.x all exist** — verified
  `tests/unit/test_application_orchestrator.py`,
  `test_application_use_cases.py`, `test_ssh_gateway.py`,
  `test_domain_exceptions.py`, `test_domain_ports.py`.

### Recommendation

**APPROVE WITH NOTES.** The Round 1 blocking issue (`deallocate_nodes.py`
omitted) is fully resolved by Tasks 7.1 and 7.2. The remaining items are
non-blocking completeness/consistency gaps. The two most worth picking
up before implementation begins are Outstanding #1 (proposal Impact file
list — trivial one-line fix to keep artifacts consistent) and #7 (5.2 vs
5.3 overlap — pick one interpretation to avoid implementer confusion).
The rest (MODULE_MAP enumeration in 10.1, START_CONTRACT coverage in
10.2, test file naming in 9.3, missing backoff/list_connected test
tasks) are quality polish that `grace_check.py` and the spec scenarios
will largely force into existence during implementation.
