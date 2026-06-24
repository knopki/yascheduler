# Review Log — relocate-show-nodes-command

## proposal Round 1 — 2026-06-24 (k-reviewer)

### ✅ Captured
- All 17 brief commitments verified present: problem statement, 6 rejections (compat shim / query_nodes YAGNI / move-all-5 / sort / multi-row / rich-tabulate), full flag matrix with correct subset/mutex semantics, exit-code contract, table+JSON formats with display transformations, _NodeView private DTO, module shape (6 private functions, no use-case extraction), no sorting, one-row-per-node, FIXME drop rationale, GRACE-lite fresh markup, files table (10 entries), capabilities (cli-commands + package-facades modified, none new), out-of-scope (7 items), knowledge-graph (M-CLI-COMMANDS loses fn-show_nodes; new M-ENTRYPOINTS-CLI-SHOW-NODES + CrossLink).
- AGENTS.md constraints respected: yanodes command name preserved, INI/DB schema/AiiDA entrypoint untouched, no new deps, Python >=3.9 ok.

### 🟡 Addressed / minor (fixed in round 1 → 2 transition)
- (a) "one UoW read" phrasing ambiguous — brief says TWO reads within one UoW; could mislead implementer. Fixed: changed to "two reads within one UoW — uow.nodes.list_all() + uow.tasks.list_by_status({RUNNING}) — then O(n+m) in-memory join".
- (b) Missing `--cloud ""` rejection rationale — the only one of 7 brief rejections not surfaced. Fixed: added rejection note inline at the `--cloud NAME` definition.
- (c) `prog="yanodes"` argparse detail dropped (brief specified it; init precedent uses `prog="yainit"`). Fixed: added to the argparse flag section.

### 🔴 Outstanding
- None.

## proposal Round 2 — 2026-06-24 (k-reviewer-fast)

### ✅ Fixed
- (b) `--cloud ""` rejection — RESOLVED (proposal lines 48–50).
- (c) `prog="yanodes"` — RESOLVED (proposal lines 57–58).

### 🟡 Addressed / minor
- (a) "one UoW read" — STILL PRESENT after round-1 fix attempt (the edit only touched --cloud/prog area). Flagged again.

### 🔴 Outstanding
- None blocking, but (a) required a one-line wording fix before freeze.

## proposal Round 3 — 2026-06-24 (k-reviewer-fast, applied fix then declared freeze)

### ✅ Fixed
- (a) "one UoW read" — RESOLVED. Line 89 now reads "two reads within one UoW — uow.nodes.list_all() + uow.tasks.list_by_status({RUNNING}) — then an O(n+m) in-memory join via a tasks_by_ip dict built once". Matches brief clarifying language.

### 🔴 Outstanding
- None.

**FREEZE READY.** proposal.md frozen. Proceeding to design + specs batch.

## design + specs Round 1 — 2026-06-24 (k-reviewer-fast)

### ✅ Captured
- design.md D1–D14 all match proposal exactly (no shim / in-module split + YAGNI / subset+mutex flags / --no-cloud / exit 0-1-2 + no explicit sys.exit(0) / table stdlib-only with display transformations / JSON raw values / _NodeView private / no sort / one-row-per-node / argv param / prog=yanodes / fresh GRACE-lite + FIXME drop / facade unchanged).
- D15 Risks/Trade-offs (6 items) + Migration Plan (deploy + rollback) present and consistent.
- D16 all 7 explore-brief rejections reflected (compat shim / query_nodes YAGNI / move-all-5 / sort / multi-row / --cloud "" / rich-tabulate).
- specs/cli-commands: MODIFIED "Entry points updated" (yainit + yanodes new locations, other 4 stay, 3 scenarios); ADDED 7 new requirements (yanodes lists nodes, parses flags via argparse, exit code contract, default table format, --json format, in-memory join O(n+m), --json convention forward-looking) — all scenarios use exactly 4 hashtags, each requirement has ≥1 scenario.
- specs/package-facades: MODIFIED R1 (infra/cli scenario lists only check_status/daemonize/manage_node/submit, drops init AND show_nodes; entrypoints/cli scenario notes show_nodes NOT re-exported; other scenarios unchanged).
- Cross-cutting: no new capability folders; AGENTS.md respected (yanodes name preserved, INI/DB/AiiDA untouched, no new deps, Python >=3.9 ok with from __future__ import annotations); spec format valid (#### scenarios, MODIFIED includes full content, header names match existing main spec).

### 🟡 Addressed / minor
- None.

### 🔴 Outstanding
- None.

**FREEZE READY.** design.md + specs frozen. Proceeding to tasks batch.

## tasks Round 1 — 2026-06-24 (k-reviewer-fast)

### ✅ Captured
- All implementation steps from D1-D14 + spec requirements covered: module scaffolding (1.1-1.2), _NodeView (2.1), _parse_nodes_args with 7 flags + mutex + prog (2.2), _fetch_nodes_view O(n+m) join + promotion note (3.1), _filter_rows AND composition (4.1), _render_nodes_table stdlib + transformations (5.1), _render_nodes_json raw values (6.1), show_nodes @to_sync + argv + exit 1 + no sys.exit(0) (7.1), delete old (8.1), update infra/cli/__init__.py (8.2), pyproject line 50 (9.1), entrypoints/cli facade declarative (10.1), specs MODIFIED+ADDED (11.1-11.3), knowledge graph (12.1-12.3), test removal (13.1-13.2), 20 new tests (14.1-14.20), verification (15.1-15.8).
- 20 test tasks cover all spec scenarios: default table, order preservation, empty exit 0, --help, --bogus exit 2, mutex exit 2, --enabled+--disabled=default, --busy+--free=default, AND composition, each individual filter, JSON raw values, JSON empty=[], exit 1 on DB/config error, no external deps, O(n+m) structural.
- Task format valid: all checkboxes `- [ ] X.Y`, grouped under `## N.` headings, ordered by dependency, each ≤2h.
- AGENTS.md respected: no pyproject version hand-edit, no new deps, no DB schema change, public interface stability (yanodes name preserved), Conventional Commits referenced.

### 🟡 Addressed / minor
- None.

### 🔴 Outstanding
- None.

**FREEZE READY.** tasks.md frozen. All artifacts complete — change is apply-ready.