
## proposal Round 1 — 2026-06-24

### 🟡 Addressed

Recommend addressing before freeze (non-blocking precision/polish):

1. **ARCHITECTURE.md §2 table wording (proposal L66-71).** §2 Component Reference table has no daemon rows — only an `entrypoints/` row (L126) listing residents. Proposal's "move daemon_*.py from deferred/outside-set box into PRESENTATION" implies a daemon row exists in §2 to move. Reword: the §2 edit is updating the `entrypoints/` row's resident list to add `daemon/`, not relocating a daemon row.

2. **Spec L200 stale parenthetical (proposal L58-65 spec-rewrite commitment).** `package-facades/spec.md` L200 "Empty facade is valid for future residents" scenario uses "(e.g., CLI, daemon launchers)". After this change, daemon launchers are no longer "future" — proposal should commit to dropping "daemon launchers" from this parenthetical (same requirement as L184, which IS committed). Avoids internal inconsistency within an already-touched requirement.

3. **daemon_sysv.py working_directory side-effect unacknowledged (proposal L21-30).** L39 `working_directory=os.path.dirname(__file__)` silently changes the daemon's post-fork CWD from `yascheduler/` to `yascheduler/entrypoints/daemon/` after the move. CONFIG_FILE/LOG_FILE/PID_FILE are absolute, so likely benign — but proposal should either commit to preserving old CWD (`Path(__file__).parent.parent.parent`) or explicitly justify accepting the new one.

4. **Quote drift (proposal L11-12).** Quotes spec forward reference as "remains" (singular); actual spec L252 uses "remain" (plural, one bullet covers both modules). Align for verbatim accuracy.


## proposal Round 2 — 2026-06-24

### 🟢 Confirmed

All 4 Round 1 🟡 items are properly addressed in the current `proposal.md`. No new 🔴 issues introduced.

1. **ARCHITECTURE.md §2 table wording (proposal L82-86).** ✅ Now explicitly states "the table has no standalone daemon rows to relocate" and limits the §2 edit to appending `daemon/` to the existing `entrypoints/` row's resident list. Matches the actual `ARCHITECTURE.md` shape.

2. **Spec L200 stale parenthetical (proposal L72-76).** ✅ Now commits to editing BOTH the L184 forward-reference sentence (drop `daemon_*.py`) AND the L200 scenario parenthetical (drop "daemon launchers", leaving "(e.g., CLI)"). Verified both target lines exist verbatim in `package-facades/spec.md` L183-185 and L199-201. Internal-consistency note ("keeping the two edits in the same requirement internally consistent") is sound — both sit under the "Entrypoints layer facade" requirement.

3. **daemon_sysv.py working_directory CWD side-effect (proposal L30-37).** ✅ Now explicitly acknowledges post-fork CWD changes `yascheduler/` → `yascheduler/entrypoints/daemon/` and justifies acceptance. Verified `daemon_sysv.py:39` `working_directory=os.path.dirname(__file__)`. Verified the benign-claim substrate in `yascheduler/shared/variables.py:24-26`: `CONFIG_FILE=/etc/yascheduler/yascheduler.conf`, `LOG_FILE=/var/log/yascheduler.log`, `PID_FILE=/var/run/yascheduler.pid` — all env-overridable but with absolute defaults, so CWD does not affect resolution.

4. **Quote drift "remains" vs "remain" (proposal L10-12).** ✅ Now quotes "remain at the package root in the interim" (plural), matching `package-facades/spec.md:252` verbatim.

### 🟢 Cross-verified claims

- **init.py path-substitution (proposal L42-50):** `infra/cli/init.py:39` `install_path = Path(__file__).parent.parent.parent` resolves to `yascheduler/`; L57 `install_path / "daemon_systemd.py"` and L72 `install_path / "daemon_sysv.py"` confirmed. The proposed rewrite to `install_path / "entrypoints/daemon/daemon_*.py"` is the correct runtime-impacting edit (templates substitute `%YASCHEDULER_DAEMON_FILE%`).
- **Relative-import conversion (proposal L24-29):** `daemon_sysv.py:31-32` uses `from .infra.cli import daemonize` and `from .shared import LOG_FILE, PID_FILE` — these would resolve inside the new `entrypoints/daemon/` subpackage post-move; absolute facade paths are the correct fix.
- **Knowledge-graph updates (proposal L59-64):** `docs/knowledge-graph.xml:118-133` confirms `M-DAEMON-SYSTEMD` (`<depends>M-CLI-COMMANDS, M-SHARED</depends>`, empty annotations) and `M-DAEMON-SYSV` (`<depends>M-CLI-COMMANDS, M-SHARED</depends>`, `<fn-start_daemon>` annotation). Proposal's "annotations unchanged / depends stays" claim matches.

### 🔴 Outstanding

None. Batch is frozen.

## design+specs Round 1 — 2026-06-24

Combined batch review of `design.md` + `specs/package-facades/spec.md` delta.

### 🔴 Outstanding

1. **Migration narrative contradicts `init.py` overwrite-skipping behavior (design.md D4 L222-223, Risks L324-328, Migration Plan L379-381).** D4 and the Migration Plan claim operators can "re-run `yainit` to regenerate" existing service files with the new daemon path. This is factually wrong: `infra/cli/init.py:53` (`_init_systemd`) and `:68` (`_init_sysv`) guard the *entire* write block with `if not unit_file.is_file():` / `if not startup_file.is_file():` — i.e. `yainit` ONLY writes when the target file does NOT exist; if the service file already exists from a prior `yainit`, re-running `yainit` silently skips it (the write at L61/L76 is unreachable). The design even self-contradicts: Risks L325 correctly notes "the installer only writes when the target doesn't exist", while D4 L222 ("the next `yainit` run regenerates them with the new path") and Migration L379 ("must re-run `yainit` ... to regenerate") say the opposite. Net operational effect: an operator following the documented guidance keeps a stale service file pointing at the now-deleted `yascheduler/daemon_*.py` → daemon fails to start on `systemctl start` / `/etc/init.d/yascheduler start`. **Fix:** align D4/Migration/Risks to state the operator must first REMOVE the existing service file (`rm /lib/systemd/system/yascheduler.service`, `rm /etc/init.d/yascheduler` — typically after `systemctl stop/disable`) before re-running `yainit`, because `init.py` never overwrites an existing unit/init script. Note the frozen `proposal.md` L137-140 carries the same inaccuracy; correcting the design will diverge from the proposal on this point — treat the design's corrected Migration Plan as authoritative and the proposal's one-line summary as imprecise.

### 🟡 Addressed

Recommend addressing before freeze (non-blocking precision/polish):

1. **§1 diagram box reference is wrong (design.md D7 L303-304).** D7 refers to "the §1 diagram's 'ENTRY POINTS & LEGACY WRAPPERS' box" — no such box exists in `docs/ARCHITECTURE.md`. The actual §1 boxes are "PRESENTATION (yascheduler.entrypoints)" (L22) and "COMPOSITION ROOT / OUTSIDE-LAYER-SET" (L90, which currently holds the daemon files at L97-98). Name them correctly: the point-edit moves the two daemon lines OUT of the COMPOSITION ROOT box and adds a `daemon/` entry to the PRESENTATION box.

2. **New knowledge-graph module entry for the subpackage facade is not committed (design.md Goals L79-81).** The design commits to creating `entrypoints/daemon/__init__.py` as a governed GRACE-lite facade (MODULE_CONTRACT + MODULE_MAP + CHANGE_SUMMARY) but the knowledge-graph update section only covers updating the two existing `M-DAEMON-*` `<path>` values. Per GRACE-lite rules ("module added → M- entry") and the precedent that `entrypoints/__init__.py` itself has an `M-ENTRYPOINTS` entry (`docs/knowledge-graph.xml:51`), the new subpackage facade warrants a new `M-ENTRYPOINTS-DAEMON` (or similar) entry. Add this so the knowledge-graph update is complete (Migration step 5 runs `grace_check.py`, which would surface the gap at implementation time anyway).

3. **Spec scenario over-attributes `start_daemon` to daemon_systemd.py (spec delta L43-45).** The new "Daemon launchers are not re-exported by the entrypoints facade" scenario lists "`start_daemon` and any `__main__`-level symbols from `entrypoints/daemon/daemon_systemd.py` and `entrypoints/daemon/daemon_sysv.py`". Only `daemon_sysv.py` defines `start_daemon` (`daemon_systemd.py` has only a `__main__` guard at L25). Tighten the enumeration, e.g. "`start_daemon` (sysv) and the `__main__` blocks of both launchers".

4. **`# FIXME: move this module to adapters` drop not surfaced in design (design.md Goals/Decisions).** The frozen `proposal.md` L22-24 commits to dropping the stale `# FIXME: move this module to adapters` comment from both files (verified at `daemon_systemd.py:20`, `daemon_sysv.py:20`). The design's Goals/Decisions don't mention this edit. Add a one-line note for implementation completeness.

5. **D6 "CONFIG_DIR-style" phrasing is loose (design.md L279).** D6 says "the `shared` constants use `CONFIG_DIR`-style env-derived prefixes". There is no `CONFIG_DIR` env var; the actual overrides are `YASCHEDULER_CONF_PATH` / `YASCHEDULER_LOG_PATH` / `YASCHEDULER_PID_PATH` (`shared/variables.py:24-26`). Rephrase to "env-overridable (`YASCHEDULER_*_PATH`) absolute-path defaults" for precision. Conclusion (benign CWD change) is unaffected.

Batch is NOT frozen — one 🔴 outstanding (migration narrative must be corrected before freeze).

## design+specs Round 2 — 2026-06-24

Confirmation round covering the unfreeze-and-refix of `proposal.md` (Impact /
External API paragraph) plus `design.md` (D4, D6, D7, Risks, Migration Plan
step 7, Goals) and `specs/package-facades/spec.md` (the "Daemon launchers are
not re-exported" scenario).

### 🟢 Confirmed

**🔴 migration-narrative fix — consistent across proposal + design:**

1. **`init.py` guard semantics verified.** `infra/cli/init.py:53`
   (`if not unit_file.is_file():`) gates the *entire* `_init_systemd` write
   block (L54-61, including the `daemon_file` computation at L57 and the write
   at L61); `:68` (`if not startup_file.is_file():`) gates the *entire*
   `_init_sysv` write block (L69-77, including L72 and L76). `yainit` only
   writes when the target does NOT exist; re-running while the old service file
   exists silently skips. The fix's guard description is accurate.

2. **`proposal.md` L141-149** now states `init.py` does NOT auto-migrate, the
   `is_file()` guard silently skips, operators must `rm` the existing service
   file (after stop/disable) before re-running `yainit`, and release notes must
   call out the manual removal. ✅ The stale "keep working until the next
   `yainit` run regenerates them" sentence is replaced — no residue.

3. **`design.md` D4 L227-240** states the same remove-then-rerun sequence with
   the L53/L68 guard citation. ✅

4. **`design.md` Risks L333-347** (first risk) states the same, including the
   release-notes call-out. ✅ The round-1 internal contradiction (Risks vs D4)
   is resolved — both now agree on skip → remove → re-run.

5. **`design.md` Migration Plan step 7 L398-405** rewritten to the
   remove-then-rerun sequence with explicit `rm` commands and the
   "never overwrites existing service files" parenthetical. ✅

6. **Proposal ↔ design consistency.** Both now agree operationally: breakage is
   real (old files removed in-change), `yainit` will not overwrite, manual `rm`
   + re-run is required, release notes must say so. No divergence remains.

**🟡 fixes verified:**

1. **D7 ARCHITECTURE.md box names (`design.md` L316-319).** ✅ Now names the
   real boxes "COMPOSITION ROOT / OUTSIDE-LAYER-SET" (verified
   `docs/ARCHITECTURE.md:90`, holding the daemon files at L97-98) and
   "PRESENTATION (`yascheduler.entrypoints`)" (verified
   `docs/ARCHITECTURE.md:22`). The non-existent "ENTRY POINTS & LEGACY
   WRAPPERS" reference is gone.

2. **M-ENTRYPOINTS-DAEMON committed (`design.md` Goals L83-86).** ✅ Goals now
   commits to adding a new `M-ENTRYPOINTS-DAEMON` module entry for the
   `entrypoints/daemon/__init__.py` subpackage facade, citing the GRACE-lite
   "module added → M- entry" rule and the `M-ENTRYPOINTS` precedent.

3. **Spec scenario `start_daemon` attribution (`spec.md` L45).** ✅ Now reads
   "`start_daemon` (from `entrypoints/daemon/daemon_sysv.py`) and the
   `__main__` blocks of both ...". Verified `daemon_sysv.py:35` defines
   `start_daemon`; `daemon_systemd.py` has no `start_daemon` (only a `__main__`
   guard). Attribution tightened correctly.

4. **FIXME drop committed (`design.md` Goals L62-64).** ✅ Goals now explicitly
   commits to dropping `# FIXME: move this module to adapters` from both moved
   files. Verified the FIXME exists at `daemon_systemd.py:20` and
   `daemon_sysv.py:20`.

5. **D6 env-var phrasing (`design.md` L291-293).** ✅ Now says "env-overridable
   absolute-path defaults (`YASCHEDULER_CONF_PATH` / `YASCHEDULER_LOG_PATH` /
   `YASCHEDULER_PID_PATH` in `shared/variables.py`)". Verified all three
   env-var names at `shared/variables.py:24-26`. The loose "CONFIG_DIR-style"
   phrasing is gone; the benign-CWD-change conclusion is unaffected.

**No new 🔴 introduced.** A full `rg` sweep for "regenerate" / "keeps working
until" across the change folder found every remaining "regenerate" instance
(D4 L238, Risks L344, Migration L402, proposal L147) paired with the
remove-then-rerun requirement, and the one "keep working until" (D4 L228)
correctly describes old service files working until the *package upgrade*
removes the `.py` files — not the flagged residue.

### 🟡 Outstanding

Non-blocking; one wording residue inside a rejected-alternative paragraph.

1. **D4 Alternative #2 shorthand re-introduces "re-run to regenerate"
   (`design.md` L251).** The rejected-alternative rationale says "operators
   re-run `yainit` to regenerate service files, which is the existing model" —
   the same re-run-to-regenerate shorthand the 🔴 fix corrected in D4's main
   body, Risks, Migration step 7, and the proposal. Context rescues it (the D4
   main body two paragraphs above spells out the remove-then-rerun sequence),
   so it is non-blocking; but in isolation the sentence re-states the
   imprecision. Optional tighten, e.g. "operators remove the existing service
   file and re-run `yainit` to regenerate it (the existing model)".

Batch is frozen. No 🔴 outstanding — `proposal.md` (re-frozen),
`design.md` (frozen), and `specs/package-facades/spec.md` (frozen) are
confirmed.

## tasks Round 1 — 2026-06-24

### 🟢 Confirmed

All 8 task groups (28 tasks: 1.1-1.3, 2.1-2.2, 3.1-3.3, 4.1, 5.1-5.4,
6.1-6.3, 7.1-7.4, 8.1-8.10) fully cover the frozen `proposal.md`,
`design.md` (D1-D7, Goals, Migration Plan), and
`specs/package-facades/spec.md` delta. No out-of-scope work implemented;
structural format correct. Batch is apply-ready.

**Source-line references verified against actual files:**

- `infra/cli/init.py`: L39 `install_path = Path(__file__).parent.parent.parent`,
  L48 `_init_systemd`, L57 `daemon_file = install_path / "daemon_systemd.py"`,
  L64 `_init_sysv`, L72 `daemon_file = install_path / "daemon_sysv.py"`,
  L53/L68 `if not <file>.is_file():` guards, VERSION 2.0.2, LAST_CHANGE
  v2.0.2 rename-adapters-to-infra. Tasks 3.1/3.2/3.3 cite correctly.
- `daemon_systemd.py`: L2 FILE header, L3 VERSION 1.6.2, L8-9 DEPENDS/LINKS
  M-CLI-COMMANDS/M-SHARED, L17-18 CHANGE_SUMMARY, L20 `# FIXME: move this
  module to adapters`, L25-29 `__main__` with `from .infra.cli import
  daemonize` + `from .shared import LOG_FILE`. Task 1.2 preserves all.
- `daemon_sysv.py`: L2/L3 headers, L8-9 DEPENDS/LINKS, L17-18 CHANGE_SUMMARY,
  L20 FIXME, L25-29 stdlib/daemon imports, L31-32 relative imports, L35
  `start_daemon`, L39 `working_directory=os.path.dirname(__file__)`, L46-53
  argparse `__main__`. Task 1.3 preserves all; task 2.2 D6 CWD-acceptance
  note accurate.
- `entrypoints/__init__.py`: L2 VERSION 1.0.0, L14-16 CHANGE_SUMMARY (single
  LAST_CHANGE, no PREVIOUS_CHANGE — task 4.1's "move v1.0.0 to
  PREVIOUS_CHANGE" is a valid add), L15 verbatim stale comment, L20
  `from .client import Yascheduler`, L22 `__all__ = ["Yascheduler"]`. Task
  4.1 quotes L15 verbatim, preserves L22.
- `docs/knowledge-graph.xml`: L118-124 M-DAEMON-SYSTEMD (path L120, depends
  L121, empty annotations), L126-133 M-DAEMON-SYSV (path L128, depends L129,
  fn-start_daemon L131), L49-56 M-ENTRYPOINTS precedent (NAME/TYPE/
  STATUS/purpose/path/depends/annotations). Tasks 5.1/5.2/5.3 cite
  correctly; 5.3's M-ENTRYPOINTS-DAEMON mirrors L49-56 structure.
- `docs/ARCHITECTURE.md`: L22 PRESENTATION box, L90 COMPOSITION ROOT /
  OUTSIDE-LAYER-SET box, L97-98 daemon lines, L99 footer, L126 §2
  entrypoints row, L414-434 §4 tree. Tasks 7.1/7.2/7.3 cite correctly.
- Live `package-facades/spec.md`: L183-185 forward-reference prose, L199-201
  "(e.g., CLI, daemon launchers)" parenthetical, L252 daemon bullet, L258
  scenario enumeration. Tasks 6.2/6.3 line cites verified.

**Frozen delta confirmation tasks (6.1-6.3) match the frozen delta:**
"Daemon launchers are not re-exported" scenario (frozen spec L43-45)
attributes `start_daemon` only to `daemon_sysv.py`; "Daemon launchers are
layer-checked after migration" scenario (frozen L80-83) worded correctly;
both MODIFIED requirements carry full content (header + description + all
scenarios, `####` headers). Task 6.1 confirms structural form.

**Out-of-Scope items NOT implemented as tasks:** no di.py/infra/cli
migration, no rename, no compat shim, no launcher tests (8.1 explicitly
defers), no CHANGELOG, no init.py auto-migration.

**Structural correctness:** all 28 tasks are `- [ ]` checkboxes grouped
under `## N.` headings; dependency-ordered (move → import → init.py →
facade → graph → spec-confirm → docs → verify); each well under one
session. Task 8.10 stale-reference sweep correctly adds a 3rd glob
(`!openspec/changes/relocate-daemon-launchers/**`) refining the design's
2-glob sweep and documents pre-sync live spec lines as acceptable hits.

**Prior-round fixes carried into tasks:** task 2.2 cites D6 (CWD accepted
as-is); tasks 7.1/7.2/7.3 use correct box names (PRESENTATION L22,
COMPOSITION ROOT L90) per design Round 1; tasks 1.2/1.3 commit the FIXME
drop; task 5.3 adds M-ENTRYPOINTS-DAEMON per design Round 1.

### 🟡 Outstanding

Non-blocking polish; batch may freeze as-is.

1. **Migration-narrative operator guidance not surfaced in tasks.** Frozen
   proposal (Impact L148-149: "Release notes must call out this manual
   removal step") and design (D4 L235-240, Risks L342-345, Migration Plan
   step 7 L398-406) commit to telling operators they must `rm` the existing
   service file before re-running `yainit` (the L53/L68 `if not
   <file>.is_file():` guard silently skips otherwise). No task carries this
   forward. Consistent with CHANGELOG being Out of Scope and the commitment
   being release-notes (no `RELEASE_NOTES.md` exists in the repo), but a
   one-line note in task 3.3 would close the loop so the apply phase doesn't
   treat its absence as an oversight.

2. **Package reinstall step (Migration Plan step 2) implicit only.** Design
   L382-384 commits to `uv pip install -e .` / `uv sync` so old
   `yascheduler/daemon_*.py` paths leave installed metadata. Verification
   tasks 8.8/8.9 assume the reinstall (8.8's import smoke check would fail
   against stale installed metadata) but don't state it. Add a note on 8.8
   or a prerequisite 8.0.

3. **Version-bump numbers imprecise in tasks 1.2, 1.3, 3.3.** These say
   "Bump VERSION" without the target number, while task 4.1 pins "Bump
   VERSION to 2.0.0" explicitly. Implementer can infer patch bumps
   (1.6.2→1.6.3, 2.0.2→2.0.3) from the PREVIOUS_CHANGE shuffle, but pinning
   the numbers would match 4.1's precision.

4. **Task 4.1 bump magnitude (1.0.0 → 2.0.0) heavier than convention.**
   init.py uses patch bumps (2.0.1→2.0.2) for similar relocate/import edits;
   the entrypoints facade's public surface is unchanged (only CHANGE_SUMMARY
   commentary moves, `__all__` stays `["Yascheduler"]`). A 1.0.0→1.1.0 /
   1.0.1 bump would be more consistent. The 2.0.0 embeds in the
   CHANGE_SUMMARY narrative as a "subpackage resident added" milestone, so
   defensible — worth a second look.

5. **Task 7.1 silent on PRESENTATION box footer.** Task 7.1 correctly notes
   the COMPOSITION ROOT footer (L99 "outside layers contract; may import
   downward") stays, but is silent on the PRESENTATION box footer (L25
   "depends on: infra, application, domain, shared"). Footer is a
   layer-level annotation unaffected by the resident add; a symmetric
   one-line note would make the point-edit scope fully explicit.

Batch is frozen. No 🔴 outstanding — `tasks.md` is apply-ready.
