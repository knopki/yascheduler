# Review Log — add-node-id-identity

## proposal Round 1 — 2026-07-02
Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` (decisions table + rejected alternatives)

### Verdict: PASS (single-round)

### 🔴 Outstanding
None.

### 🟡 Addressed (non-blocking suggestions applied before freeze)
- Added `postgres-schema-apply` to Modified Capabilities with an explicit note that only
  the `schema.sql` snapshot content changes, not the `apply_schema` contract. (blast-radius
  visibility)
- Specified the `yasetnode` add-by-id `parser.error` message text verbatim in the proposal
  to remove implementer guesswork.

### ✅ Captured well (verified present, do NOT touch when fixing future batches)
Every explore-brief decision row is faithfully reflected: migration mechanics (002 ALTER,
CONSTANT `'001'→'002'`, snapshot node_id-first, ip UNIQUE kept); `NewNode`/`Node`/`NodeId`
split with conversion only in `insert`; `add → insert(new_node) -> Node`; `get_by_id`;
all ip-keyed API unchanged; `CloudProvisioner.allocate → NewNode` ripple; 5 SELECTs +
`node_id`, `ORDER BY node_id`, `RETURNING node_id`, new `get_by_id.sql`; `yanodes`
column/JSON; `yasetnode` `_parse_node_target` + `NodeTarget` + add-path rejection +
remove-by-id via `get_by_id` then ip-keyed ops; all out-of-scope items listed; no
rejected alternative re-adopted.

**proposal.md FROZEN.**

## design Round 1 — 2026-07-02
Reviewer: @k-reviewer-fast
Baseline: frozen `proposal.md` + `explore-brief.md`

### Verdict: PASS (single-round)

### 🔴 Outstanding
None.

### 🟡 Addressed (non-blocking fix applied before freeze)
- Context anchor `Node.ip (domain/model.py:373)` → `domain/model.py:376` (373 is the class
  docstring line; the `ip: str` field is at 376). Citation accuracy.

### ✅ Captured well
Every locked decision faithfully elaborated: migration 002 mechanics + three-cohort
convergence; `NewNode`/`Node`/`NodeId` split with conversion only in `insert`; dataclass
field ordering satisfies "defaults after non-defaults" and construction is keyword-based;
all 5 NodeId boundaries specified; `add→insert -> Node` mirrors `TaskRepository.insert`;
`get_by_id` additive; all ip-keyed API + `add_tmp` unchanged; `CloudProvisioner.allocate
→ NewNode` ripple with consumers named; SQL changes (RETURNING, get_by_id.sql, 5 SELECTs +
node_id, list_all ORDER BY); `_row_to_node` wraps NodeId; yanodes NODE_ID-first + JSON
`.value`; yasetnode `NodeTarget` + `isdigit()` discriminator + `_parse_host_spec` untouched
+ add-path parser.error (message matches proposal verbatim) + remove-by-id via get_by_id
then ip-keyed ops; all out-of-scope items deferred. No decision-level drift, no internal
contradictions.

**design.md FROZEN.**

## specs Round 1 — 2026-07-02
Reviewer: @k-reviewer-fast
Baseline: frozen `proposal.md` + `design.md` + existing main specs

### Verdict: NEEDS-FIXES

### 🔴 Fixed (applied, then round 2 run)
- cli-commands delta missed MODIFIED entries for "yasetnode parses flags via argparse"
  and "yasetnode exit code contract" — both main-spec requirements reference
  `type=_parse_host_spec` (lines 902, 967), which changes to `type=_parse_node_target`.
  Added both as MODIFIED requirements (full restatement + the `type=` change +
  node_id×add-path / remove-by-id-not-in-DB additions).
- "yasetnode parses host grammar via argparse type" MODIFIED requirement dropped 9
  still-in-force scenarios (empty port, port range, port zero, negative ncpus,
  non-integer port, hostname passes, missing host positional, malformed host, prog).
  Restored all 9, adapted to call `_parse_node_target` (delegating to the unchanged
  `_parse_host_spec`).
- (Main-agent-caught) "yasetnode output channels and verbatim success messages"
  defined `{host}` as `HostSpec.host` — incomplete on the node_id path (no HostSpec).
  Added MODIFIED requirement clarifying `{host}=node.ip` on the node_id path.

### 🟡 Addressed
- postgres-repositories "List all nodes" scenario restored "regardless of enabled
  status" alongside the new `ORDER BY node_id` clause.

## specs Round 2 — 2026-07-02
Reviewer: @k-reviewer-fast

### Verdict: PASS (single-round after fixes)

### 🔴 Outstanding
None.

### 🟡 Addressed (non-blocking fix applied before freeze)
- Grammar requirement wording "ALL of its scenarios below are UNCHANGED" was slightly
  contradicted by the scenarios (they now call `_parse_node_target`, not
  `_parse_host_spec` directly). Reworded to "grammar rules and ALL error/rejection
  behavior tested below are UNCHANGED ... so the scenarios below call
  `_parse_node_target` (which delegates non-digit input to the unchanged
  `_parse_host_spec`)".

### ✅ Verified
All 4 cli-commands MODIFIED requirements (grammar/flags/exit-code/output-channels)
restate their main-spec requirements faithfully with all scenarios present; the two
`type=` references corrected; 9 grammar scenarios restored; postgres list_all
scenario fixed; no new contradictions; scope discipline intact (no MachineSession
node_id, no add_tmp change, no WHERE node_id switch, no get_by_ids, no yastatus
node_id). domain-entities/domain-ports/sql-queries deltas spot-checked clean.

**specs/ FROZEN.**

## tasks Round 1 — 2026-07-02
Reviewer: @k-reviewer-fast
Baseline: frozen `proposal.md` + `design.md` + `specs/`

### Verdict: PASS (single-round)

### 🔴 Outstanding
None.

### 🟡 Addressed (non-blocking fix applied before freeze)
- §8.7 contained an optional suggestion to print `(node_id={n.node_id})` in the add
  success message. This would violate the frozen `cli-commands` spec, which fixes the
  add success message as exactly `Added host to yascheduler: {host}:{port}`. Removed
  the optional; §8.7 now states the message format is unchanged.

### ✅ Captured well
Full coverage of every locked decision across all 5 frozen specs (migration mechanics;
NodeId/NewNode/Node; NodeRepository insert/get_by_id; SQL get_by_id.sql/RETURNING/5
SELECTs+node_id/ORDER BY; PostgresNodeRepository insert/get_by_id/_row_to_node with
.value unwrap; CloudProvisioner.allocate→NewNode ripple through ports/_setup_vm/
allocate_task/consumers/mocks; yanodes NODE_ID-first + JSON .value; yasetnode
NodeTarget/_parse_node_target/add-by-id parser.error/remove-by-id via get_by_id then
ip-keyed ops/{host}=node.ip sourcing; tests per area; GRACE graph + static checks +
spec/grace validation). All task signatures match frozen specs. No scope creep
(MachineSession/ConnectedMachine/yastatus node_id, add_tmp change, WHERE node_id
switch, get_by_ids, ip UNIQUE relaxation all absent). Granularity ≤2h with Verify:
lines; sequencing in dependency order.

**tasks.md FROZEN. All four batches frozen — proposal complete.**
