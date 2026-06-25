## proposal Round 1 — 2026-06-25
### 🔴 Fixed
- None. Proposal already correctly captures all decisions from the explore-brief.

### 🟡 Addressed
- All 7 fidelity checks pass:

  1. **AiiDA compatibility contract** — Proposal explicitly states `_render_default` outputs `<task_id><whitespace><STATUS_NAME>` (STATUS_NAME ∈ {TO_DO, RUNNING, DONE}) and that `entrypoints/aiida_plugin.py` is unchanged. Analogous to submit's `str(task_id)` contract.

  2. **TaskStatus closed-enum guarantee** — Proposal notes the closed enum `{TO_DO, RUNNING, DONE}` guarantees `_MAP_STATUS_YASCHEDULER` never KeyErrors (L87-89).

  3. **B-full connection bugfix** — `_resolve_conn_params(node, config)` described correctly: `node.username` (not cloud username), `node.port`, `jump_host`/`jump_username` from matching cloud, fallback to `config.remote`. "Duplicated, not shared, YAGNI" framing present (L99-102).

  4. **Q-uow DB-lifecycle fix** — Query/render separation described: one short UoW for fetch, closed before SSH. `_render_view` receives `nodes_by_ip` as argument, no longer opens its own UoW. `make_cli_deps` called once (L103-109).

  5. **`--json` 9 fields** — All 9 listed correctly (L112-118): `task_id, status, label, allocated_ip, port, cloud, engine, local_folder, remote_folder`. Null semantics for TO_DO stated. Second instance of `--json` convention noted.

  6. **Mutex mechanics** — `-v`/`-i`/`--json` in `mutually_exclusive_group`; `-o` NOT in the group (modifier of `-v`); body-check rejects `-o` without `-v` (L62-66). Exactly correct.

  7. **Knowledge-graph edits** — All amendments match the brief and verified source:
     - M-CLI-COMMANDS loses `<fn-check_status>` ✅
     - New M-ENTRYPOINTS-CLI-CHECK-STATUS node with correct depends list ✅
     - 3 CrossLinks from the new node to M-DI, M-APPLICATION-UOW, M-SSH-GATEWAY ✅
     - M-CLI-COMMANDS → M-DI amended: adds "uses make_cli_deps for CLI node management; make_daemon for daemon entry" — correct per `manage_node.py:29` which imports `make_cli_deps` ✅
     - M-CLI-COMMANDS → M-DOMAIN-MODEL amended: drops "Task" and "status", leaving "imports Node, TaskStatus for CLI node management" — correct per `manage_node.py:30` which imports `Node, TaskStatus` (not `Task`) ✅

### 🔴 Outstanding
- None. All decisions from the explore-brief are captured faithfully. The proposal structure (Why → What Changes → Out of scope → Capabilities → Impact) matches the three archived precedents. No contradictions or omissions found.

## design Round 1 — 2026-06-25
### 🔴 Fixed
- None. All 13 decisions (D1–D13) are present, covering every proposal commitment. Verified against codebase ground truth.

### 🟡 Addressed
- **D3 mutex mechanics (high-risk check 1)** — correct: `-v`/`-i`/`--json` in `mutually_exclusive_group`; `-o` NOT in group with explicit rationale (`-o -v` must remain valid); body-check after parse. Verified that `-o` cannot be in the group and the rationale explains why.
- **D5 AiiDA contract (high-risk check 2)** — correct: default renderer snippet `print(f"{task.task_id}   {task.status.name}")` matches current `check_status.py:77` byte-for-byte (3 spaces). No decoration.
- **D7 _resolve_conn_params (high-risk check 3)** — correct: uses `node.username` (not cloud username — explicit bugfix). `Node.username: str = "root"` verified at `model.py:369`.
- **D8 query/render split (high-risk check 4)** — correct: UoW closed before SSH; `_render_view` receives `nodes_by_ip` as arg; `make_cli_deps` called once; node lookup conditional on `args.view or args.json`.
- **D9 golden test (high-risk check 5)** — correct: uses exact plugin parser shape `for job_id, status in job.split()` (not a reimplementation).
- **D13 knowledge-graph (high-risk check 6)** — correct: both CrossLink amendments verified against `knowledge-graph.xml:968-969` and `manage_node.py:29-30`.
- **D4 SystemExit propagation** — design's claim verified: `to_sync` at `async_utils.py:41-63` calls `asyncio.run(coro)`, which correctly propagates `SystemExit` (a `BaseException`).
- **D7 "mirroring ... exactly" claim** — design adds a `break` after the matching-cloud lookup that the orchestrator (`_connect_machine_consumer:211-214`) does not have. Behavior is identical with unique cloud prefixes, so no bug, but the "exactly" qualifier is imprecise.
- **Decision coverage (high-risk check 7)** — all 13 proposal commitments have corresponding Decisions: no-shim (D1), no-usecase (D2), prog/argv/mutex (D3), exit codes (D4), AiiDA contract (D5), --json (D6), bugfix (D7), UoW (D8), golden test (D9), tempfile (D10), FIXME (D11), facade (D12), knowledge-graph (D13).
- **Spec file updates** — proposal lists updating `openspec/specs/package-facades/spec.md` and `cli-commands/spec.md`. Design mentions `cli-commands/spec.md` in D6's rationale (for the `--json` convention) but doesn't explicitly mention `package-facades/spec.md`. The design doesn't contradict these — specs are separate implementation artifacts — but the omission is noted for the implementation phase.
- **Test coverage scope** — proposal lists ~11 test categories. Design's D9 explicitly covers only the AiiDA-contract golden test. Remaining categories (argparse, exit codes, `-v` happy path, `_resolve_conn_params`, query/render separation etc.) are standard relocation-following tests implicit from the proposal but not individually re-decided. Acceptable for a design document.

### 🔴 Outstanding
- None. Design is faithful to the frozen proposal, consistent with the explore-brief, and technically sound against the actual codebase. Ready to proceed to specs/tasks.

## specs Round 1 — 2026-06-25
### 🔴 Fixed
- None.

### 🟡 Addressed
- **4-hashtag scenarios** — grepped both spec files: all 54 scenarios in cli-commands and 4 in package-facades use exactly `####` (4 hashtags). No `### Scenario:` found. ✅
- **Header text matches exactly** — all 4 MODIFIED requirement headers match the current `openspec/specs/*/spec.md` character-for-character:
  1. `### Requirement: CLI commands call use cases via DI` ✅
  2. `### Requirement: Entry points updated` ✅
  3. `### Requirement: --json is the machine-readable CLI output convention` ✅
  4. `### Requirement: Within-package relative imports (R1)` ✅
- **Other MODIFIED requirements reproduce full content** — `CLI commands call use cases via DI` and `--json` reproduction verified against current base spec: full body + all scenarios present with appropriate edits. ✅
- **6 new yastatus requirements** — all 6 present under `## ADDED Requirements`:
  1. `yastatus queries task status` ✅
  2. `yastatus default output format (AiiDA compatibility)` ✅
  3. `yastatus parses flags via argparse` ✅
  4. `yastatus exit code contract` ✅
  5. `yastatus --json output format` ✅
  6. `yastatus view mode connects via SSH with correct node params` ✅
- **AiiDA contract scenarios** — verified against `aiida_plugin.py:298-300`: `[job.split() for job in stdout.split("\n") if job]` and `for job_id, status in job_list` — the scenario mirrors the exact parser shape. ✅
- **Mutex mechanics** — `-v/-i/--json` in `mutually_exclusive_group`; `-o` NOT in group with explicit body-check. All 6 mutex scenarios verified. ✅
- **`--json` 9 fields** — all 9 fields present with correct types and null semantics. TO_DO task → null `allocated_ip`/`port`/`cloud` scenario present. ✅
- **`_resolve_conn_params` scenarios** — 4 scenarios cover: `node.username` (not cloud), `node.port`, matching cloud jump host, `config.remote` fallback. ✅
- **tempfile + try/finally** — both scenarios present: unique temp name (no fixed collision), cleanup on exception. ✅
- **Query/render separation** — scenarios verify: UoW closed before SSH; `nodes_by_ip` fetched only for `-v`/`--json`; default/`-i` skip nodes lookup; `make_cli_deps` once. ✅
- **package-facades R1** — infra/cli scenario correctly drops `check_status` from imports, adds to "does NOT import" list. Entrypoints/cli scenario adds `check_status` to "NOT re-exported" list. ✅
- **Precedent shape/depth** — delta structure matches archive precedent (`relocate-submit-command`). ✅

### 🔴 Outstanding
- **`Entry points updated` missing yainit content (partial reproduction)** — MODIFIED `### Requirement: Entry points updated` in `specs/cli-commands/spec.md:35` only reproduces the console_script mapping paragraph (base spec lines 247-268) and omits the yainit functional specification (base spec lines 271-331: sync function, apply_schema, systemd detection, service template rendering, overwrite behavior, OSError handling, and 10 scenarios). Per the rule "MODIFIED requirements reproduce full content... partial content loses detail at archive time," this risks silently dropping the yainit content at sync time if the process performs header-matched replacement. The same pattern was followed by all three prior relocation deltas (init, show_nodes, submit) — none included the yainit content. If sync is resilient (merges content rather than replacing), this is a no-op. But per the strict rule, it is a data-loss risk.
  - **Location**: `specs/cli-commands/spec.md:35-63`
  - **Fix**: Add the missing yainit functional specification prose and all 10 scenarios to the MODIFIED `Entry points updated` section, preserving existing content while making only the console_script edits.

## specs Round 2 — 2026-06-25
### 🔴 Fixed
- **Entry points updated now includes full yainit content** — The MODIFIED `Entry points updated` requirement (delta lines 35-125) now contains:
  - Updated prose: yastatus line added (`check_status`), counter changed from "other 3" → "other 2"
  - 5 console_script resolution scenarios (yainit, yanodes, yasubmit, yastatus, All 6) — yastatus resolves scenario added at line 57-59
  - yainit prose paragraph (sync function, `apply_schema`, systemd detection via `Path`, overwrite behavior, `OSError` handling) — identical to main spec lines 271-279
  - All 13 yainit functional scenarios (no flags, `--schema`, `--daemon`, `--schema --daemon`, `--help`, unknown flag, idempotent, DatabaseError, service write failure, overwrite systemd, overwrite sysv, detect systemd, detect non-systemd) — faithfully reproduced verbatim from main spec lines 281-331

### 🟡 Addressed
- **Cross-check against main spec** — Every line of yainit content (prose + 13 scenarios) in the delta matches the main spec character-for-character. The only differences in the entire `Entry points updated` requirement are the three intended delta changes: (a) yastatus mapping added to prose, (b) "other 3" → "other 2" with `check_status` removed from the parenthetical list, (c) `yastatus resolves to the new location` scenario added. No yainit scenario text was altered. ✅
- **4-hashtag check** — Grepped both spec files: all 67 scenarios in the delta file use exactly `#### Scenario:` (4 hashtags). All 94 scenarios in the main spec also use exactly 4 hashtags. No `### Scenario:` or `##### Scenario:` found. ✅
- **No regressions** — The first MODIFIED requirement (`CLI commands call use cases via DI`) was already correctly updated in Round 1 with yastatus prose and scenario. The `--json` MODIFIED requirement was already correctly updated. The `package-facades` MODIFIED requirement was already correct. The ADDED Requirements section (6 yastatus requirements, lines 150-478) is fully intact. No unintended changes found. ✅

### 🔴 Outstanding
- None. All Round 1 issues resolved.
