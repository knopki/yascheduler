# Review Log — relocate-submit-command

## proposal Round 1 — 2026-06-24

Round 1 review of `proposal.md` against the `explore-brief.md` baseline. The
brief is the authoritative checklist; this round verifies every commitment is
captured with no gaps or contradictions.

### ✅ Captured

All commitments from the brief are reflected in the proposal. Verified against
current source state where the brief makes claims about files.

**The 5 user decisions:**

1. **FIXME drop** (brief L246-254). Proposal L95-101 commits to dropping the
   `# FIXME: split adapter and application layer` comment with the same
   "stale framing + in-module split resolves it" reasoning as show-nodes D13.
   ✅ Verified the FIXME exists verbatim at `infra/cli/submit.py:20`.

2. **Delete smoke test + add real unit test file** (brief L329-331). Proposal
   L139-162 commits to deleting `test_submit_function_exists` from
   `test_cli_smoke.py`, deleting the `TestSubmit` class + `submit_mod` import
   from `test_cli_behavioral.py`, and adding `tests/unit/test_cli_submit.py`.
   ✅ Verified all three targets exist: `test_cli_smoke.py:65
   test_submit_function_exists`, `test_cli_behavioral.py:38 submit_mod = ...`,
   `test_cli_behavioral.py:121 class TestSubmit`.

3. **--help/error screens, exit codes, argv parameter, in-module split**
   (brief L127-227). Proposal L46-101 captures: `prog="yasubmit"`,
   `argv: list[str] | None = None`, the `0`/`1`/`2` exit-code contract, the
   `_existing_path` argparse validator, and the in-module function split
   (`_existing_path`, `_parse_submit_args`, `_parse_script_metadata`,
   `_read_input_files`, `_build_metadata`, `submit`). All six functions named.

4. **Knowledge graph node `M-ENTRYPOINTS-CLI-SUBMIT`** (brief L349-352).
   Proposal L128 uses the correct spelling `M-ENTRYPOINTS-CLI-SUBMIT` (matching
   `M-ENTRYPOINTS-CLI-INIT` at `knowledge-graph.xml:143` and the show-nodes
   precedent `M-ENTRYPOINTS-CLI-SHOW-NODES`), NOT the user's typo
   `M-ENTRYPOINS-CLI-SUBMIT`. ✅ Correct.

5. **Sequencing after `relocate-show-nodes-command` archives** (brief L16-17,
   L333-356). Proposal L10-14, L104-108, L110-113, L123-125 all assume
   show-nodes archives first. ✅ Verified show-nodes is still in
   `openspec/changes/` (not yet archived), confirming the sequencing
   assumption holds.

**The 2 follow-up decisions:**

6. **YAGNI on `DF-SUBMIT`** (brief follow-up #1). Proposal L134-138 commits to
   NOT touching `DF-SUBMIT` with the same reasoning: the CLI path is trivial
   (`M-ENTRYPOINTS-CLI-SUBMIT → M-DI → M-APPLICATION-SUBMIT`), and adding a
   parallel `/` alternative would mix two entry points in one flow element.
   ✅ Verified `DF-SUBMIT` exists at `knowledge-graph.xml:887` as
   `M-ENTRYPOINTS-CLIENT -> M-DI -> M-APPLICATION-SUBMIT -> ...`.

7. **argparse-layer file-existence validation → exit 2; body-layer ENGINE
   validations → exit 1** (brief follow-up #2). Proposal L50-57 captures the
   argparse/body split: `type=_existing_path` for shape (file exists → exit 2),
   body for content (ENGINE key present, engine known → exit 1). L70-71 lists
   exit 2 cases including "file not found via `type=_existing_path`". L67-69
   lists exit 1 cases including ENGINE key missing and engine unknown.

**The central distinguishing constraint:**

8. **AiiDA stdout compatibility** (brief L199-215, L303-316). Proposal L72-83
   captures the key constraint distinguishing submit from show-nodes: success
   MUST print exactly `str(task_id)` (no prefix, suffix, decoration, JSON
   envelope) because `entrypoints/aiida_plugin.py:_parse_submit_output` parses
   `int(stdout.strip())`. ✅ Verified the contract at
   `aiida_plugin.py:268-273`: `output = stdout.strip(); try: int(output);
   except ValueError: logger.error("Submitting failed, no task id
   received")`. Proposal correctly identifies this as the constraint that
   forbids `--json`/`--table` flags.

**Behavior change note:**

9. **Missing-file: was exit 1 + traceback, becomes exit 2 + clean argparse
   message, AiiDA-compatible** (brief L169-176). Proposal L217-222 surfaces
   this explicitly in the Impact section as "the one observable behavior
   change, AiiDA-compatible (still != 0)". ✅ Current `infra/cli/submit.py:75-
   76` confirmed (`if not script_file.exists(): raise ValueError("Script
   parameter is not a file name")`) — the proposal's claim that this currently
   surfaces as exit 1 + traceback is accurate.

**YAGNI rejections:**

10. **Move-all-3** (brief L87-91). Proposal L35-37, L164-170 commits the other
    3 commands (`check_status`, `manage_node`, `daemonize`) to follow-up.
11. **Compat shim** (brief L92-102). Proposal L41-43 rejects with the layer-
    direction reasoning.
12. **`--json`/`--table` flags** (brief L103-111). Proposal L80-83, L173-175
    rejects with the AiiDA contract reasoning.
13. **`application/` use-case extraction** (brief L112-119). Proposal L89-94,
    L171-172 rejects with YAGNI reasoning.
14. **Output transformation** (brief L120-123). Proposal L72-83 commits to
    preserving `str(task_id)` exactly via the output-contract section.
15. **Pure relocation** (brief L82-86) — see 🟡 #2 below (implicit only).

**Files table completeness** (brief L318-331 vs proposal L31-162, L210-238):

All 10 file actions covered: add `entrypoints/cli/submit.py`, remove
`infra/cli/submit.py`, modify `infra/cli/__init__.py` (drop import + `__all__`
+ MODULE_MAP line, bump VERSION, CHANGE_SUMMARY), modify `pyproject.toml`
console_script, modify `package-facades` spec R1, modify `cli-commands` spec,
modify `knowledge-graph.xml`, modify `test_cli_smoke.py`, modify
`test_cli_behavioral.py`, add `test_cli_submit.py`. ✅ Verified
`pyproject.toml:54` is the `yasubmit` line; `infra/cli/__init__.py:11` has the
`submit - Re-exported from .submit` MODULE_MAP line; `infra/cli/__init__.py:27`
has `from .submit import submit`; `infra/cli/__init__.py:34` has `"submit"` in
`__all__`.

**Capabilities:**

16. **No new capabilities; modified: `cli-commands`, `package-facades`**
    (brief does not introduce new spec capability). Proposal L188-208 correctly
    states "None" for new capabilities and identifies `cli-commands` and
    `package-facades` as modified. Mirrors show-nodes proposal structure.

**AGENTS.md constraints:**

17. **CLI command name `yasubmit` preserved, INI/DB schema untouched, AiiDA
    entrypoint untouched, no new deps, Python >=3.9 ok.** Proposal L173-176
    ("No new dependencies — stdlib only: argparse, pathlib, base64, logging,
    os, sys"), L180-184 ("schema-migrations — unaffected; yasubmit touches no
    schema"; "entrypoints/aiida_plugin.py — unchanged"), L222-224 ("No BREAKING
    change to the command name or the success invocation; the AiiDA scheduler
    plugin contract is preserved exactly"). ✅ Verified `aiida_plugin.py:251`
    `_get_submit_command` returns `f"{_CMD_PREFIX}yasubmit {submit_script}"` —
    the command name stays. Stdlib-only claim holds for the reimplemented
    logic (no new deps introduced).

### 🟡 Addressed-minor

Recommend addressing before freeze (non-blocking precision/polish):

1. **`package-facades` R1 "already" list is internally contradictory
   (proposal L109-113).** The proposal says: *"assuming
   `relocate-show-nodes-command` archived first: the list is already
   `check_status`, `daemonize`, `manage_node`; this change drops `submit` →
   `check_status`, `daemonize`, `manage_node`."* If the list this change finds
   is already `check_status, daemonize, manage_node` (3 items, no `submit`),
   then there is nothing to drop. The actual pre-state this change sees (after
   show-nodes archives) is `check_status, daemonize, manage_node, submit`
   (4 items); this change drops `submit` → 3 items. The brief (L326) gets this
   right. **Fix:** change "the list is already `check_status`, `daemonize`,
   `manage_node`" → "the list is already `check_status`, `daemonize`,
   `manage_node`, `submit`" so the before/after states are consistent.

2. **Pure-relocation rejection is only implicit (proposal L31-32 vs brief
   L82-86).** The brief lists pure relocation as rejected-alternative #1 with
   the user's verbatim quote ("Нет, не надо вот придумывать какие-то pure
   relocation..."). The proposal embeds the rejection implicitly in "real
   implementation, not a shim" (L32) but does not call it out as a rejected
   alternative. This matches the show-nodes precedent shape, so it is
   consistent across the relocate-* series. Optional one-line addition to the
   "Out of scope" list would close the gap with the brief; non-blocking because
   the substantive commitment (real reimplementation) is unambiguous.

3. **"submit does NOT call `sys.exit(0)` explicitly on success" implementation
   note not surfaced (brief L192-197, L281-284).** The brief spells out twice
   that `submit` returns normally and the process exits 0 implicitly, while
   only the failure path calls `sys.exit(1)`. The proposal L66 says only
   "normal completion" for the success case and L68-69 says the failure path
   is "caught at the top level" — the apply phase can infer the no-`sys.exit(0)`
   shape, but the brief's explicit note would remove ambiguity for the
   implementer. Mirrors show-nodes precedent, which also leaves this to the
   implementer. Optional precision add; non-blocking.

4. **Brief's invocation/error table and validation-split table flattened to
   prose.** The brief uses two tables (L129-138 invocation×exit, L159-167
   validation×layer×exit) to enumerate all cases exhaustively. The proposal
   captures all substantive cases in prose (L46-83) but loses the tabular
   exhaustive form. All 8 invocation rows and all 6 validation rows are
   covered content-wise. Matches the show-nodes proposal shape (also prose);
   non-blocking. Optional: re-introduce the validation-split table in the spec
   delta rather than the proposal, where it belongs.

5. **`M-CLI-COMMANDS → M-DI` CrossLink edit is ambiguous (proposal L131-133).
   ** The proposal says "drop any stale `M-CLI-COMMANDS → ...` edge that
   existed for `submit`". Verified `knowledge-graph.xml:943`: `<CrossLink
   from="M-CLI-COMMANDS" to="M-DI" relation="uses make_cli_deps for CLI
   submit; make_daemon for daemon entry" />` — this single edge covers both
   `submit` AND `daemon`. "Drop the edge" is therefore wrong (would also drop
   the daemon clause); the correct edit is to amend the relation string to
   drop only the "CLI submit" clause, leaving "uses make_daemon for daemon
   entry". Show-nodes had no analogous edge to edit (show_nodes is not in the
   relation string), so this is a new precision issue specific to submit.
   Non-blocking — apply phase can infer — but worth one clarifying line.

### 🔴 Outstanding

None. The proposal is freeze-ready subject to fixing the 🟡 #1
package-facades wording contradiction (the only item that is internally
inconsistent rather than merely imprecise). The remaining 🟡 items are
optional polish.

**Cross-verified claims (sampled):**

- `infra/cli/submit.py:20` — `# FIXME: split adapter and application layer
  (business logic)` exists verbatim (FIXME-drop commitment grounded).
- `infra/cli/submit.py:75-76` — body-layer file-existence check via
  `raise ValueError` confirmed (the exit-1-with-traceback baseline for the
  behavior-change note is accurate).
- `infra/cli/submit.py:100-102` — webhook block confirmed
  (`_build_metadata` encapsulation target grounded).
- `infra/cli/submit.py:34-56` — `_parse_script_metadata` and
  `_read_input_files` already pure (the "moved as-is" claim holds).
- `aiida_plugin.py:247-275` — `_get_submit_command` returns
  `f"{_CMD_PREFIX}yasubmit {submit_script}"`; `_parse_submit_output` does
  `int(stdout.strip())` then logs "Submitting failed, no task id received" on
  ValueError (the AiiDA stdout compatibility constraint is grounded).
- `pyproject.toml:54` — `yasubmit = "yascheduler.infra.cli.submit:submit"`
  confirmed as the line to update.
- `infra/cli/__init__.py:11,27,34` — `submit` re-export, MODULE_MAP line, and
  `__all__` entry all confirmed present (deletion commitments grounded).
- `knowledge-graph.xml:887` — `DF-SUBMIT` exists with the client-API path
  shape the proposal describes (YAGNI-leave-alone commitment grounded).
- `knowledge-graph.xml:94` — `<fn-submit PURPOSE="Submit task via AiiDA script
  (infra/cli/submit.py)" />` confirmed under `M-CLI-COMMANDS` (deletion
  target grounded).
- `knowledge-graph.xml:143` — `M-ENTRYPOINTS-CLI-INIT` precedent shape
  confirmed (the `M-ENTRYPOINTS-CLI-SUBMIT` node mirrors it correctly).
- `cli-commands/spec.md:17` — current "other 5 CLI commands remain in
  `infra/cli/`" text confirmed (show-nodes reduces to 4; this change to 3,
  matching the proposal's "from 'other 4' to 'other 3'").
- `package-facades/spec.md:100` — current R1 scenario lists `check_status`,
  `daemonize`, `manage_node`, `show_nodes`, `submit` (5 items; show-nodes → 4;
  this change → 3, matching the proposal's terminal state but NOT its
  contradictory "already" wording — see 🟡 #1).

Batch is NOT frozen — one 🟡 internal contradiction to fix (🟡 #1) before
freeze; remaining 🟡 items are optional polish.

## proposal Round 2 — 2026-06-24

Verification of the two fixes applied by the main agent per Round 1 review.

### ✅ Fixed

**🟡 #1 — package-facades pre-state wording now consistent.**
Proposal L111-114: pre-state reads `check_status, daemonize, manage_node, submit`
(4 items, show_nodes already dropped); this change drops `submit` →
`check_status, daemonize, manage_node` (3 items). Before/after consistent.
✅ Resolved.

**🟡 #5 — CrossLink edit now explicit.**
Proposal L134-139: instead of "drop any stale edge", the text now says "this
change amends that relation to drop only the 'CLI submit' clause, leaving
'uses make_daemon for daemon entry' (NOT deleting the edge — the daemon clause
still applies while `daemonize` remains in `infra/cli/`)." No ambiguity about
whether the whole edge is dropped.
✅ Resolved.

### 🟡 Addressed / minor

No new observations. The remaining 🟡 items (#2, #3, #4) from Round 1 were
flagged as optional polish only and were intentionally not modified; they
remain acceptable as-is.

### 🔴 Outstanding

None.

**FREEZE READY.** proposal.md frozen.

## design + specs Round 1 — 2026-06-24

Reviewed `design.md` + `specs/cli-commands/spec.md` (delta) + `specs/
package-facades/spec.md` (delta) against the frozen `proposal.md`.
Cross-checked against current main specs (`openspec/specs/cli-commands/
spec.md`, `openspec/specs/package-facades/spec.md`), the AiiDA plugin source
(`yascheduler/entrypoints/aiida_plugin.py:_parse_submit_output` L260-275),
the current submit source (`yascheduler/infra/cli/submit.py`), and the
knowledge graph (`docs/knowledge-graph.xml`).

### ✅ Captured

**Commitment 1 (Real move + reimplementation).** Design D1 fully captures:
move to `entrypoints/cli/submit.py`, delete `infra/cli/submit.py`, drop
re-export + `__all__` entry + MODULE_MAP line from `infra/cli/__init__.py`,
update `pyproject.toml` L54. Shim alternative explicitly rejected (layer
inversion). Spec "Entry points updated" + "yasubmit parses AiiDA script and
submits task" state the new module path. Package-facades R1 scenario drops
submit from infra/cli submodule list.

**Commitment 2 (argparse with prog="yasubmit").** Design D9 captures
`prog="yasubmit"`. Spec "yasubmit parses flags via argparse" cites
`ArgumentParser(prog="yasubmit", ...)` and one positional `script`.

**Commitment 3 (type=_existing_path).** Design D3 captures the validator
shape (`_existing_path(s) -> Path`, raises `ArgumentTypeError`), the
argparse-layer vs body-layer validation split, and the behavior change
(missing-file exit 1→2). Spec "yasubmit with a non-existent script exits 2"
+ "yasubmit validates script content in the body" correctly split exit 2
(argparse) from exit 1 (body).

**Commitment 4 (argv parameter).** Design D8 captures
`argv: list[str] | None = None`. Spec requirement states the signature and
the `None` reads `sys.argv` convention.

**Commitment 5 (Exit codes 0/1/2).** Design D4 enumerates all three codes
with sources. Spec "yasubmit exit code contract" mirrors exactly: 0 success,
1 runtime (ENGINE/engine/DB/config/unexpected), 2 argparse. D4 note on
`sys.exit(0)` not called explicitly is captured in the spec too.

**Commitment 6 (Output contract / AiiDA compatibility).** Design D5 cites
the verbatim AiiDA code (`output = stdout.strip(); try: int(output); except
ValueError: self.logger.error("Submitting failed, no task id received");
return output`), verified against `aiida_plugin.py` L268-275 — exact match.
Explains WHY decoration breaks `int(output)` with concrete examples.
Distinguishes submit (machine consumer) from show_nodes (no machine
consumer). Spec "yasubmit preserves AiiDA stdout compatibility" cites the
same code and forbids `--json`/`--table`/output-mode flags via an explicit
scenario.

**Commitment 7 (In-module function split; no application/ extraction).**
Design D2 (split + YAGNI rejection of use case), D6 (`_build_metadata`
encapsulates webhook), D7 (`_parse_script_metadata` + `_read_input_files`
moved as-is). Spec "yasubmit parses AiiDA script and submits task" lists all
five helpers with their responsibilities and has dedicated scenarios for
each (metadata parsing, input file reading, base64 fallback, webhook
present/absent/None).

**Commitment 8 (FIXME drop).** Design D10 captures: do NOT carry `# FIXME:
split adapter and application layer` — stale framing (`entrypoints/` is not
the adapter layer) + in-module split resolves the concern. Adapts
`relocate-show-nodes-command` D13 reasoning.

**Commitment 9 (entrypoints/cli/__init__.py declarative edit).** Design D11
captures the declarative PURPOSE edit (generalize to add submit), no
re-export added (invoked by console_script). Mirrors show_nodes D14.

**Commitment 10 (package-facades spec).** Delta MODIFIED R1 requirement:
infra/cli submodule list correctly shows post-state `check_status,
daemonize, manage_node` (3 items); "does NOT import init, show_nodes, or
submit". Entrypoints/cli scenario updated: "`show_nodes` and `submit` are
NOT re-exported by the facade". Verified against current main spec (which is
in post-show_nodes state: lists `check_status, daemonize, manage_node,
submit` + does-not-import init/show_nodes).

**Commitment 11 (cli-commands spec).** Delta captures: module path, prog,
argv, type=_existing_path, exit codes, validation split, AiiDA stdout
contract, in-module split. Counter correctly updated: "Entry points
updated" says "The other 3 CLI commands" (was "other 4" after show_nodes).
"CLI commands call use cases via DI" requirement REPLACED with post-submit
text including both yanodes and yasubmit clauses + "other 3".

**Commitment 12 (knowledge-graph).** Design D12 correctly captures the
combined-edge amend (existing relation covers BOTH submit AND daemon in one
string; amend drops only "CLI submit" clause, keeps "make_daemon for daemon
entry"; NOT a full-edge drop — verified against `knowledge-graph.xml` L957
which reads exactly `relation="uses make_cli_deps for CLI submit; make_daemon
for daemon entry"`). D13 captures DF-SUBMIT untouched (YAGNI). Verified
`M-CLI-COMMANDS` L94 has `<fn-submit>` to delete; `M-ENTRYPOINTS-CLI-INIT`
and `M-ENTRYPOINTS-CLI-SHOW-NODES` already exist as precedents for the new
`M-ENTRYPOINTS-CLI-SUBMIT` node.

**Commitment 13 (Tests).** Not a design/spec concern per se; specs encode
the testable behavior via scenarios (argparse errors, happy path, validation
errors, webhook branches, helper behaviors, exit codes). The proposal
carries the full test plan.

**Commitment 14 (Out of scope).** Design Non-Goals capture: other 3 commands
stay, no application/ use case, no --json/--table, no new deps, di.py/
application/domain/infra/persistence/aiida_plugin.py unchanged. Design
Context notes schema-migrations non-conflict and show_nodes sequencing.

**Cross-check A (D3 behavior change).** Design D3 "Behavior change" section
correctly states: missing-file currently raises ValueError → traceback +
exit 1; after change → argparse type error → clean message + exit 2.
AiiDA-compatible. Matches proposal Impact L223-225.

**Cross-check B (D5 AiiDA contract).** Verified above — verbatim code match,
WHY-explanation present, submit vs show_nodes distinction present.

**Cross-check C (D12 CrossLink amend).** Verified above — combined edge
correctly identified, amend-not-drop reasoning correct, daemon clause
preserved.

**Cross-check D (cli-commands spec delta).** "Entry points updated"
post-state correct (init + show_nodes + submit in entrypoints; check_status,
manage_node, daemonize in infra/cli). "yasubmit parses AiiDA script and
submits task" captures full module shape. "yasubmit parses flags via
argparse" has prog + type=_existing_path. "yasubmit validates script content
in the body" correctly distinguishes exit 1 (body) from exit 2 (argparse).
"yasubmit exit code contract" has all three codes. "yasubmit preserves AiiDA
stdout compatibility" cites verbatim code + forbids output-mode flags.

**Cross-check E (package-facades spec delta).** R1 post-state correct (3
items). Entrypoints/cli scenario mentions show_nodes AND submit not
re-exported.

**Cross-check F (design vs specs consistency).** D3 ↔ "yasubmit with a
non-existent script exits 2": consistent. D5 ↔ "yasubmit preserves AiiDA
stdout compatibility": consistent. No contradictions found across D1-D13
and spec requirements.

**Cross-check G (sequencing).** Main specs are in post-show_nodes state
(show_nodes dropped from infra/cli list at L101, in does-not-import at
L103-104; "Entry points updated" already shows yanodes in entrypoints). The
submit deltas target this state correctly: do not re-move show_nodes,
correctly decrement counters (4→3 in "Entry points updated"; replaces "other
5" with "other 3" in "CLI commands call use cases via DI").

### 🟡 Addressed / minor (non-blocking)

**#1 — Design D3/D4 imprecise about AiiDA retval.** Design D3 says "The
AiiDA scheduler plugin treats any `retval != 0` as a failed submission
(`int(stdout.strip())` fails on empty stdout → ...)". The actual
`_parse_submit_output` (L260-275) does NOT check `retval` at all — it only
does `int(stdout.strip())` and logs on ValueError. The parenthetical gives
the correct mechanism (int failure), so the conclusion (AiiDA-compatible) is
correct, but the lead clause ("treats retval != 0 as failed") is technically
wrong. The spec "yasubmit preserves AiiDA stdout compatibility" cites the
verbatim code without mentioning retval, so the spec is precise. This
imprecision originates in the explore-brief/proposal and was carried through
to the design. Non-blocking: the exit-code-change conclusion holds because
empty stdout → int() fails regardless of retval.

**#2 — Design D3 doesn't echo "the ONE observable behavior change" framing.**
The proposal Impact section (L223-225) characterizes the missing-file
exit-code change as "the one observable behavior change, AiiDA-compatible".
Design D3 calls it "a deliberate improvement within the reimplementation
scope" and lists it under Risks, but doesn't state its uniqueness. Substance
captured; phrasing not. Non-blocking.

**#3 — LABEL default not in spec scenarios.** Current code L87:
`label = script_params.get("LABEL", "AiiDA job")`. The design's call-path
pseudocode (L266-278) omits the label extraction line. No spec scenario
covers "LABEL absent → default 'AiiDA job'". The happy-path scenario uses a
script WITH `LABEL = Test job`. Behavior is preserved (the body logic is
moved, and the spec says `deps.submit(label, ...)`), just the default-value
contract is not explicitly asserted. Non-blocking: the logic moves as-is and
the proposal's test plan (L157) implies label extraction testing.

**#4 — Design D12 doesn't restate M-ENTRYPOINTS-CLI-SUBMIT node attributes.**
D12 focuses on the CrossLink amend decision and mentions the new
`M-ENTRYPOINTS-CLI-SUBMIT → M-DI` edge but doesn't restate the node's `path`
and `depends` attributes. Those are in the proposal (L129-131:
`path: yascheduler/entrypoints/cli/submit.py`, `depends: M-CONFIG, M-DI,
M-SHARED`). The design treats node creation as a mechanical consequence of
D1, not a separate decision. Non-blocking: the proposal is authoritative and
complete.

### 🔴 Outstanding (blocking — must be empty for freeze)

None.

**design + specs FREEZE READY.**

## tasks Round 1 — 2026-06-24

Round 1 review of `tasks.md` against the frozen `proposal.md` + `design.md` +
`specs/cli-commands/spec.md` + `specs/package-facades/spec.md`. Cross-checked
against current codebase state (`infra/cli/submit.py`, `infra/cli/__init__.py`,
`entrypoints/cli/__init__.py`, `pyproject.toml`, `knowledge-graph.xml`,
`tests/unit/test_cli_smoke.py`, `tests/unit/test_cli_behavioral.py`) and the
applied `relocate-show-nodes-command/tasks.md` precedent.

### ✅ Captured

**Real move + facades + pyproject (proposal L29-44, L109-113; design D1):**
Tasks 1.1-1.8 create the new module; 2.1 deletes the old; 2.2 drops the re-export
+ `__all__` + MODULE_MAP line from `infra/cli/__init__.py`; 2.3 updates the
`entrypoints/cli/__init__.py` facade; 3.1 updates `pyproject.toml` L54. ✅
Verified `pyproject.toml:54` is the `yasubmit` line; `infra/cli/__init__.py`
currently has `from .submit import submit` and `"submit"` in `__all__`.

**All 6 in-module functions (design D2, D3, D6, D7, D8, D9):** `_existing_path`
→ 1.2; `_parse_submit_args` → 1.3; `_parse_script_metadata` → 1.4;
`_read_input_files` → 1.5; `_build_metadata` → 1.6; `submit` → 1.7. All six
named with START_CONTRACT + block anchors where appropriate.

**`type=_existing_path` → exit 2 (design D3):** Task 1.2 specifies the exact
signature `_existing_path(s: str) -> Path`, returns `Path(s)` if `.is_file()`
else raises `argparse.ArgumentTypeError(f"not a file: {s}")`. Matches design D3.
`.is_file()` is slightly stricter than design's "existing file" wording (also
rejects directories) — semantically correct.

**Exit codes 0/1/2 (design D4):** Task 1.7 wraps body in
`try/except Exception → sys.exit(1)`; argparse errors → exit 2 (argparse
default); success → `print(str(task_id))` + implicit exit 0 (no explicit
`sys.exit(0)`, matching D4's note). Task 6.9 adds explicit exit-code tests.

**`argv` parameter (design D8):** Task 1.3 threads `argv` through
`_parse_submit_args`; task 1.7 specifies `submit(argv: list[str] | None = None)`;
task 6.10 adds argv-injection tests asserting no `patch("sys.argv")` coupling.

**`prog="yasubmit"` (design D9):** Task 1.3 specifies
`ArgumentParser(prog="yasubmit", description="Submit task to yascheduler via
AiiDA script")` — verbatim match.

**AiiDA stdout compatibility (design D5):** Task 1.7 specifies
`print(str(task_id))`; task 6.5 asserts `stdout == str(task_id)`. The "no
output-mode flags" commitment is captured indirectly (no `--json`/`--table` in
the argparse spec) but lacks a dedicated negative test — see 🟡 #7.

**FIXME drop (design D10):** Task 1.8 explicitly states "Do NOT carry the
FIXME". ✅ Verified the FIXME exists at `infra/cli/submit.py:20`.

**`entrypoints/cli/__init__.py` declarative edit (design D11):** Task 2.3
specifies declarative PURPOSE edit, keep SCOPE as "no re-exports", bump VERSION,
CHANGE_SUMMARY entry. Mirrors show_nodes D14 pattern. (Minor gap on LINKS field
— see 🟡 #4.)

**Knowledge graph (design D12, D13):**
- 4.1 deletes `<fn-submit>` from `M-CLI-COMMANDS`. ✅ Verified at
  `knowledge-graph.xml:94`.
- 4.2 adds `M-ENTRYPOINTS-CLI-SUBMIT` with correct TYPE/STATUS, `<purpose>`,
  `<path>`, `<depends>M-DI, M-CONFIG, M-SHARED</depends>` (matches proposal
  L129-131), and all 6 `<fn-*>` annotations.
- 4.3 adds `<CrossLink from="M-ENTRYPOINTS-CLI-SUBMIT" to="M-DI" ...>`.
- 4.4 AMENDS (not drops) the existing combined relation at
  `knowledge-graph.xml:957` — correctly preserves the daemon clause while
  dropping only the "CLI submit" clause. This precisely matches design D12's
  amend-not-drop decision and the Round 1 proposal review's 🟡 #5 resolution.
- 4.5 leaves `DF-SUBMIT` (`knowledge-graph.xml:901`) untouched (D13 YAGNI).

**Tests (proposal L141-162):** Task 6.1 deletes `test_submit_function_exists`
(✅ verified at `test_cli_smoke.py:65`). Task 6.2 deletes `TestSubmit` +
`submit_mod` import (✅ verified at `test_cli_behavioral.py:37, 119`). Tasks
6.3-6.10 create `test_cli_submit.py` covering argparse, happy path, validation,
webhook branches, helpers, exit codes, argv injection.

**Verification commands (AGENTS.md):** Tasks 7.1-7.7 cover all required checks
(pytest unit, ruff check, ruff format, lint-imports, zuban, grace_check,
openspec validate). Task 7.8 adds manual smoke for `yasubmit --help`.

**Spec scenario coverage (cli-commands/spec.md):** Cross-checked all 21
scenarios against tasks 6.3-6.10:
- Happy path → 6.5; script metadata parsing → 6.8; input files text/base64 →
  6.8; webhook present/absent/None → 6.7; `--help`/no-args/non-existent/extra/
  unknown → 6.4; prog in help/errors → 6.4; ENGINE missing/unknown → 6.6;
  exit 0/1/2 → 6.5/6.9; success prints task_id only → 6.5; failure stdout empty
  → 6.6.
- Two scenarios under-covered — see 🟡 #7 and 🟡 #8.

**Task granularity & dependency ordering:** Tasks are appropriately scoped
(task 1.7 is the densest but coherent — single function, mirrors show_nodes
7.1). Ordering is sound: new module (1.x) → delete old + update facades (2.x)
→ pyproject (3.x) → graph (4.x) → specs (5.x) → tests (6.x) → verify (7.x).
The delete-then-test ordering means tests can't be run mid-stream between 2.1
and 6.x, but verification (7.x) runs last — same pattern as show_nodes.

### 🟡 Addressed / minor (non-blocking)

**#1 — Task 2.2 line numbers and version bump are stale (post-show_nodes
state).** Task 2.2 says `from .submit import submit` is at "(line 27)" and
`"submit"` in `__all__` at "(line 34)", and directs "bump VERSION 2.2.0 →
2.3.0". Current actual state: import at L25, `__all__` entry at L31, VERSION
already 2.3.0 (show_nodes bumped it). Correct values: L25, L31, and bump
2.3.0 → 2.4.0. The line numbers are pre-show_nodes (when the file had 4
imports + 4 `__all__` entries). The MODULE_MAP reference "(line 12)" is wrong
too — actual is L11. All trivially locatable by content; non-blocking but
factually incorrect. Recommend: drop line numbers (use semantic identifiers
like show_nodes task 8.2 does) or correct them.

**#2 — Task 2.2 omits SCOPE update in `infra/cli/__init__.py` MODULE_CONTRACT.**
Current SCOPE (L5): "Re-exports 4 CLI command functions from per-command
submodules (init and show_nodes moved to entrypoints/cli/)." After submit drop
this is factually wrong on two counts ("4" → "3", and submit joins the moved
list). Show_nodes task 8.2 explicitly included "Update the SCOPE line in
MODULE_CONTRACT". Submit task 2.2 should mirror: "Re-exports 3 CLI command
functions from per-command submodules (init, show_nodes, and submit moved to
entrypoints/cli/)."

**#3 — Task 6.2 line numbers slightly off.** Says `submit_mod` import at
"(line 38)" and `TestSubmit` class at "(lines 121-210)". Actual: import at
L37, `class TestSubmit:` at L119, class body ends ~L209. Off-by-one/two;
trivially locatable. Same recommendation as #1.

**#4 — Task 2.3 omits LINKS field update in `entrypoints/cli/__init__.py`.**
Current LINKS (L7): "M-ENTRYPOINTS-CLI-INIT, M-ENTRYPOINTS-CLI-SHOW-NODES".
After submit, should append "M-ENTRYPOINTS-CLI-SUBMIT". Show_nodes task 10.1
explicitly handled the equivalent LINKS addition. Task 2.3 covers PURPOSE +
SCOPE + VERSION + CHANGE_SUMMARY but misses LINKS.

**#5 — Tasks 6.1 and 6.2 omit markup updates to the test files themselves.**
After dropping submit tests, both files carry stale markup:
- `test_cli_smoke.py`: PURPOSE "verify 5 CLI commands" → 4; SCOPE enumerates
  "submit/check_status/show_nodes/manage_node" → drop submit (and ideally fix
  the pre-existing stale "show_nodes" reference from show_nodes apply);
  MODULE_MAP "Smoke test each of the 5 CLI entry points" → 4; docstring
  "verify 5 CLI commands" → 4; VERSION 1.4.0 → 1.5.0; CHANGE_SUMMARY entry.
- `test_cli_behavioral.py`: SCOPE "submit, check_status, manage_node function
  body tests" → drop submit; MODULE_MAP "TestSubmit - ..." line → drop;
  VERSION 1.3.0 → 1.4.0; CHANGE_SUMMARY entry.
Show_nodes tasks 13.1/13.2 had the same gap, so this is a parallel precedent;
still a gap that `grace_check.py` may or may not catch (depends on whether it
validates count claims in PURPOSE/SCOPE).

**#6 — Tasks 5.1/5.2 framing is ambiguous on applying deltas to main specs.**
The deltas are frozen/written. Tasks say "Verify it is consistent with the
frozen design" but don't tell the implementer whether to (a) manually copy
delta content into `openspec/specs/cli-commands/spec.md` and
`openspec/specs/package-facades/spec.md` (what show_nodes tasks 11.1-11.3
explicitly did), or (b) rely on `openspec archive` to auto-apply during
archive. If (a), the apply step is missing; if (b), verify-only is correct.
Recommend either adding explicit "edit main spec" tasks (mirroring show_nodes
11.1-11.3) or a one-line note that "archive applies deltas; no manual
main-spec edit needed during apply phase".

**#7 — No structural test for "yasubmit does not add output-mode flags".** The
spec scenario "yasubmit does not add output-mode flags" (WHEN the argparse
parser is inspected, THEN it does NOT define `--json`/`--table`/etc.) has no
corresponding task in 6.3-6.10. A one-line structural assertion
(`inspect.getsource(submit_mod._parse_submit_args)` contains no `--json`/
`--table`/`add_argument` for output modes) would close this gap, mirroring
show_nodes task 14.19's structural-test pattern.

**#8 — No explicit "AiiDA plugin is unchanged" verification task.** The spec
scenario "AiiDA plugin is unchanged" has no task. Covered indirectly by 7.5
(zuban) and 7.6 (grace_check) which would flag accidental edits, and the
change doesn't touch `aiida_plugin.py`. Could be a `git diff --exit-code
entrypoints/aiida_plugin.py` check or a structural test. Low risk; minor.

**#9 — Task 7.x omits `pytest -m integration` sanity check.** Show_nodes task
15.2 ran integration tests to "verify no import-path breakage". Submit has no
equivalent. No integration test imports submit, so risk is low, but a one-line
sanity check would mirror the precedent and catch any surprise transitive
import.

**#10 — Task 1.7 failure-stdout assertion is partial.** Task 6.6 asserts
"stdout empty" for ENGINE-missing and engine-unknown cases. Task 6.9 (exit 1
on DB/config/unexpected) does not explicitly assert stdout empty for those
cases — only asserts exit code and stderr. The spec scenario "yasubmit failure
prints nothing to stdout" covers ALL failure modes. Recommend task 6.9 also
assert stdout is empty (not just exit 1 + stderr) for DB/config/unexpected
cases.

### 🔴 Outstanding (blocking — must be empty for freeze)

None.

All 🟡 items are precision, polish, or coverage-completeness issues the
implementer can resolve during apply by inspecting current state. None will
cause incorrect implementation — at worst they leave stale GRACE-lite markup
(🟡 #2, #4, #5) or an ambiguous workflow step (🟡 #6). The core implementation
guidance (tasks 1.x-4.x) is faithful to the frozen design D1-D13; the test
plan (6.x) covers all 21 spec scenarios with two minor gaps (🟡 #7, #8); the
verification suite (7.x) covers all required checks plus a manual smoke.

**tasks FREEZE READY.**
