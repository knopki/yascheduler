## Context

`yascheduler/entrypoints/daemon/daemon_systemd.py` (28 lines) and
`yascheduler/entrypoints/daemon/daemon_sysv.py` (52 lines) are the two daemon
launcher entry points. The archived `relocate-daemon-launchers` change moved
them from the package root into a dedicated `entrypoints/daemon/` subpackage,
converting their relative imports to absolute facade paths
(`from yascheduler.infra.cli import daemonize`,
`from yascheduler.shared import LOG_FILE` / `LOG_FILE, PID_FILE`). Each
launcher carries a full GRACE-lite `MODULE_CONTRACT`
(`DEPENDS: M-CLI-COMMANDS, M-SHARED`, `LINKS: M-CLI-COMMANDS, M-SHARED`),
`MODULE_MAP`, and `START_CHANGE_SUMMARY` (last entry v1.7.0). The subpackage
facade `yascheduler/entrypoints/daemon/__init__.py` re-exports nothing — its
SCOPE declares "no re-exports — the launchers are invoked by path from
service templates, not imported" (verified at
`yascheduler/entrypoints/daemon/__init__.py:5`).

The four recent `relocate-*-command` changes (`init`, `show_nodes`, `submit`,
`manage_node`) established `yascheduler/entrypoints/cli/` as the single home
for operator-facing entry points: each moved a CLI command from `infra/cli/`
into `entrypoints/cli/` with fresh GRACE-lite markup, an `argv`
testability parameter, and a `0`/`1`/`2` exit-code contract. The daemon
launchers are the same kind of operator-facing entry point — they live in the
same `entrypoints` layer, import the same `yascheduler.infra.cli.daemonize`
callable, and are invoked by path (not imported across layers). The
`entrypoints/daemon/` subpackage now hosts only the two launchers and their
empty facade — there is no distinct "daemon" concern separate from "CLI /
entry point" concerns. Collapsing it into `entrypoints/cli/` reduces the
entrypoints subpackage count by one and aligns the launchers with the
established "one entrypoints subpackage per concern family" pattern.

The `yainit` installer (`yascheduler/entrypoints/cli/init.py`) computes the
launcher filesystem path at install time and substitutes it into the service
templates (`yascheduler/data/yascheduler.service`,
`yascheduler/data/yascheduler.sh`) via the `%YASCHEDULER_DAEMON_FILE%`
placeholder. `_init_systemd` (L103) and `_init_sysv` (L127) each build
`daemon_file = install_path / "entrypoints/daemon/daemon_*.py"` where
`install_path = Path(__file__).parent.parent.parent` (L60) resolves to the
`yascheduler/` package dir. The launchers are NOT registered as
`console_script`s in `pyproject.toml` (verified: no `daemon_systemd` /
`daemon_sysv` entry in `[project.scripts]`); the only path-producing step is
`yainit`.

**Stakeholders:** operators running `yainit` to install the systemd unit /
SysV init.d script (must re-run `yainit` after upgrade); maintainers of the
`entrypoints/` and `entrypoints/cli/` packages; reviewers of the GRACE-lite
knowledge graph and the `package-facades` spec.

**Constraints:**
- Public interface stability (AGENTS.md): CLI command names, INI config
  format, DB schema. None of these are touched by the relocation.
- Layer direction (`import-linter`): `entrypoints → infra` only. The
  launchers stay in `yascheduler.entrypoints` (layer 1) and import downward
  to `yascheduler.infra.cli` (layer 2) and `yascheduler.shared` (layer 5);
  R3 stays satisfied.
- Python `>=3.9` (`pyproject.toml`); stdlib-only (no new dependencies).
- GRACE-lite markup required on the two moved governed files and the two
  touched facades; `grace_check.py` must exit 0.
- OpenSpec: `openspec validate --all --json` must pass after spec deltas
  land.
- The two in-flight changes `relocate-check-status-command` and
  `relocate-manage-node-command` hold `## MODIFIED Requirements` deltas
  against the SAME R1 requirement in `openspec/specs/package-facades/spec.md`.
  OpenSpec replaces the full requirement body on delta application, so this
  change's R1 delta MUST be generated against the post-merge main spec (i.e.
  archived AFTER those two), OR restricted to the enumeration line only.
  See D6.

## Goals / Non-Goals

**Goals:**
- Move `daemon_systemd.py` and `daemon_sysv.py` from `entrypoints/daemon/`
  into `entrypoints/cli/` following the established relocation pattern
  (real move, no shim).
- Liquidate the `entrypoints/daemon/` subpackage (delete its `__init__.py`
  facade and the directory).
- Update `yainit` to compute the new launcher path
  (`entrypoints/cli/daemon_*.py`).
- Update the `entrypoints/cli/` facade (declarative PURPOSE/SCOPE + LINKS +
  CHANGE_SUMMARY edit; no new re-exports).
- Update the `entrypoints/` facade (declarative CHANGE_SUMMARY edit).
- Update the GRACE-lite knowledge graph (`M-DAEMON-SYSTEMD` /
  `M-DAEMON-SYSV` `<path>`; delete `M-ENTRYPOINTS-DAEMON`).
- Update the `package-facades` spec (R1 enumeration drop; daemon-launcher
  prose/scenario path updates).

**Non-Goals:**
- Migrate `daemonize` or `check_status` (separate follow-up changes:
  `relocate-check-status-command` is in-flight; a future
  `relocate-daemonize-command` will handle `daemonize`).
- Reimplement `daemonize`, add an `argv` parameter to it, or impose an
  exit-code contract on it — those belong to the future
  `relocate-daemonize-command` (mirroring the four CLI-command predecessors).
- Change the service templates (`yascheduler/data/yascheduler.service`,
  `yascheduler/data/yascheduler.sh`) — they still carry
  `%YASCHEDULER_DAEMON_FILE%`; only the install-time substitution changes.
- Add a `console_script` entry for the launchers (they are invoked by path).
- Touch `application/`, `domain/`, `infra/persistence/`,
  `infra/ssh/gateway.py`, `infra/cli/daemonize.py`, or `infra/cli/check_status.py`.
- DB schema migration.
- New dependencies.
- Change the launcher file names (`daemon_systemd.py` / `daemon_sysv.py`
  stay; renaming would add churn against the user's stated target without
  benefit, mirroring the archived `relocate-daemon-launchers` D1 that
  preserved filenames).

## Decisions

### D1 — Real move, no compat shim

**Choice:** Delete `yascheduler/entrypoints/daemon/{daemon_systemd.py,
daemon_sysv.py, __init__.py}`; do not add a re-export shim at the old path
and do not leave the `entrypoints/daemon/` directory behind.

**Rationale:** The launchers are invoked by filesystem path from service
templates (the `%YASCHEDULER_DAEMON_FILE%` substitution produces an absolute
path), not imported across layers. The old subpackage facade
(`entrypoints/daemon/__init__.py`) re-exports nothing — its SCOPE declares
"no re-exports" — so there is no public surface to preserve. A re-export
shim would be unreachable by the service-template invocation mechanism (the
templates substitute a path, not an import) AND would invert no layer
(because the facade was empty). Leaving the empty directory behind would
create a stale vestige that future readers must reason about. The four
`relocate-*-command` predecessors established the "real move, no shim"
pattern; this change follows it.

**Alternatives rejected:**
- *Compat shim re-exporting nothing from `entrypoints/daemon/__init__.py`* —
  an empty shim with no re-exports buys nothing (the invocation mechanism
  does not import it) and leaves a stale directory.
- *Keep `entrypoints/daemon/` as an empty subpackage for future daemon-
  specific entry points* — YAGNI; no such entry point is planned, and
  `entrypoints/cli/` is the established home for operator entry points.

### D2 — Move verbatim, markup-only edits

**Choice:** Move both launcher files verbatim (no logic change). The only
edits to the moved files are: `# FILE:` header path → new location;
`VERSION` bump; append `START_CHANGE_SUMMARY` entry referencing this change
(LAST_CHANGE → PREVIOUS_CHANGE promotion, mirroring the L17-18 pattern in
both files). The `MODULE_CONTRACT PURPOSE`/`SCOPE`/`DEPENDS`/`LINKS`, the
`MODULE_MAP`, the imports (`from yascheduler.infra.cli import daemonize`,
`from yascheduler.shared import …`), the `if __name__ == "__main__":`
blocks, and the `daemon_sysv.py` `start_daemon` body (incl.
`working_directory=os.path.dirname(__file__)`) stay byte-for-byte unchanged.

**Rationale:** This is a pure relocation — the launcher behavior is
unchanged, the dependencies are unchanged, and the imports are already
absolute facade paths (the archived `relocate-daemon-launchers` converted
them). The four `relocate-*-command` predecessors each REIMPLEMENTED their
subject (fresh argparse, `argv`, exit codes); this change does NOT
reimplement the launchers — they are thin path-invoked shims with no
argument parsing of their own beyond the `daemon_sysv.py` `argparse`
`-p`/`-l` block (which stays unchanged). Reimplementation would conflate two
changes (relocation + `daemonize` modernization); the latter is explicitly
deferred to `relocate-daemonize-command` (Non-Goals).

**Alternatives rejected:**
- *Reimplement the launchers with fresh `argv` / exit-code contract* —
  conflates with `relocate-daemonize-command` (out of scope); the launchers
  are thin shims and the modernization belongs to the `daemonize` move.

### D3 — `working_directory` CWD shift accepted as-is (no compensation)

**Choice:** `daemon_sysv.py:38` `working_directory=os.path.dirname(__file__)`
stays unchanged. The post-fork CWD shifts from
`yascheduler/entrypoints/daemon/` to `yascheduler/entrypoints/cli/`.

**Rationale:** Same call as the archived `relocate-daemon-launchers` D6:
the consumed paths (`CONFIG_FILE`, `LOG_FILE`, `PID_FILE`) are
env-overridable absolute defaults
(`yascheduler/shared/variables.py:24-26`:
`CONFIG_FILE=/etc/yascheduler/yascheduler.conf`,
`LOG_FILE=/var/log/yascheduler.log`, `PID_FILE=/var/run/yascheduler.pid`),
so the CWD does not affect resolution. The CWD is only relevant if a
relative path leaks into the daemon's consumption — verified by the
archived change's review to be benign. The second relocation shifts the
CWD by one directory (`daemon/` → `cli/`), but the same substrate
(absolute env-overridable defaults) makes the shift benign. No
`Path(__file__).parent.parent.parent` compensation is added.

**Alternatives rejected:**
- *Compensate with `Path(__file__).parent.parent.parent` to pin CWD at
  `yascheduler/`* — adds complexity for no behavioral benefit; the archived
  change already established the benign-CWD-shift precedent and the
  substrate (absolute env-overridable defaults) is unchanged.

### D4 — Facade edits are declarative-only

**Choice:**
- `yascheduler/entrypoints/cli/__init__.py`: bump VERSION; revise
  `MODULE_CONTRACT PURPOSE`/`SCOPE` to add the daemon launchers alongside
  `init`, `show_nodes`, `submit`, `manage_node` as residents (the launchers
  are invoked by path from service templates, not re-exported — same lazy-
  publication stance as the four CLI commands); add `M-DAEMON-SYSTEMD` and
  `M-DAEMON-SYSV` to the `LINKS`; append `CHANGE_SUMMARY` entry. `__all__`
  stays `["Yascheduler"]` (no new re-exports).
- `yascheduler/entrypoints/__init__.py`: bump VERSION; revise the
  `CHANGE_SUMMARY LAST_CHANGE` entry to drop the
  `daemon/ subpackage resident` clause and add the
  `daemon_systemd.py`/`daemon_sysv.py` now residents of `entrypoints/cli/`
  clause. `MODULE_CONTRACT PURPOSE`/`SCOPE`/`DEPENDS`/`LINKS`/`MODULE_MAP`
  stay unchanged.

**Rationale:** The two facades' public surfaces are unchanged — the
launchers are not imported across layers and were never re-exported by
either facade. The edits only update the resident-set commentary
(`PURPOSE`/`SCOPE`/`LINKS`/`CHANGE_SUMMARY`) to reflect the new
residency. This is declarative content (would not cause an implementer to
write different code; it documents the resident set), so it is allowed
under the soft-freeze rule if a later batch needed to touch these facades.
The `__all__` of `entrypoints/cli/__init__.py` stays `["Yascheduler"]` —
note: `entrypoints/cli/__init__.py` currently has NO `__all__` (it only has
a docstring); the proposal's reference to `__all__ = ["Yascheduler"]` is
the `entrypoints/__init__.py` facade's `__all__`. The `entrypoints/cli/`
facade adds no `__all__` (consistent with its current state).

**Alternatives rejected:**
- *Re-export `start_daemon` from `entrypoints/cli/__init__.py`* — the
  launchers are invoked by path, not imported; re-exporting would create a
  false public surface and violate lazy publication.

### D5 — `yainit` path rewrite is the one runtime-impacting edit

**Choice:** In `yascheduler/entrypoints/cli/init.py`:
- `_init_systemd` L103: `install_path / "entrypoints/daemon/daemon_systemd.py"`
  → `install_path / "entrypoints/cli/daemon_systemd.py"`.
- `_init_sysv` L127: `install_path / "entrypoints/daemon/daemon_sysv.py"`
  → `install_path / "entrypoints/cli/daemon_sysv.py"`.
- Bump VERSION; append `CHANGE_SUMMARY` entry.
- `install_path = Path(__file__).parent.parent.parent` (L60) stays
  unchanged — it resolves to `yascheduler/`, which is the correct prefix
  for the new subpackage path (`entrypoints/cli/daemon_*.py`).
- `MODULE_CONTRACT PURPOSE`/`SCOPE`/`DEPENDS`/`LINKS` stay unchanged.

**Rationale:** The path computation is the single runtime-impacting edit:
the `%YASCHEDULER_DAEMON_FILE%` substitution into
`yascheduler/data/yascheduler.service`
(`ExecStart=/usr/bin/python3 %YASCHEDULER_DAEMON_FILE%`) and
`yascheduler/data/yascheduler.sh` (`yascheduler=%YASCHEDULER_DAEMON_FILE%`)
now produces `…/entrypoints/cli/daemon_*.py` instead of
`…/entrypoints/daemon/daemon_*.py`. This is the source of the
**BREAKING (re-install)** flag: a service file installed before the
upgrade points at the now-removed `entrypoints/daemon/` path and will fail
to start; operators MUST re-run `yainit` after upgrade. The
`install_path` computation is unchanged because `init.py` is itself a
resident of `entrypoints/cli/` (it was moved there by
`relocate-init-command`), so `Path(__file__).parent.parent.parent` still
resolves to `yascheduler/` (the parent of `entrypoints/`).

**Alternatives rejected:**
- *Change the service templates to hardcode the new path* — the templates
  use a placeholder precisely so the install-time path can change without
  template edits; hardcoding would couple the templates to the install
  layout.
- *Compute `install_path` from the launcher's own location* — the
  launcher is not imported by `init.py`; computing from `init.py`'s own
  `__file__` is correct and unchanged.

### D6 — Spec delta restricted to the enumeration line for R1; full
scenario-path updates for the "Entrypoints layer facade" requirement

**Choice:** Two requirements in `openspec/specs/package-facades/spec.md` are
modified:
- **R1 ("Within-package relative imports")**: the delta is restricted to
  dropping `yascheduler.entrypoints.daemon` from the enumeration
  (`yascheduler.infra.cli`, `yascheduler.infra.persistence`,
  `yascheduler.entrypoints.daemon`, `yascheduler.entrypoints.cli`, and all
  other subpackages → `yascheduler.infra.cli`,
  `yascheduler.infra.persistence`, `yascheduler.entrypoints.cli`, and all
  other subpackages). The R1 scenarios (`infra/cli/__init__.py uses
  relative imports`, `entrypoints/cli/__init__.py uses relative imports`,
  `Domain modules use relative imports`, `No parent-traversal relative
  imports anywhere`) are NOT touched by this change's delta — they are
  owned by the in-flight `relocate-check-status-command` /
  `relocate-manage-node-command` deltas which edit the
  `infra/cli/__init__.py` scenario's resident list and the
  `entrypoints/cli/__init__.py` scenario's resident list. This change's
  R1 delta body is regenerated at archive time against the post-merge
  (post-in-flight-archive) main-spec scenarios verbatim, so it does not
  clobber the in-flight scenario edits; the delta alters ONLY the
  enumeration line (dropping `yascheduler.entrypoints.daemon`).
- **"Entrypoints layer facade"**: the delta updates the daemon-launcher
  prose (L186-193: `entrypoints/daemon/daemon_systemd.py` →
  `entrypoints/cli/daemon_systemd.py`, `entrypoints/daemon/daemon_sysv.py`
  → `entrypoints/cli/daemon_sysv.py`) and the two daemon scenarios
  ("Daemon launchers are not re-exported by the entrypoints facade" at
  L207-209; "Daemon launchers are layer-checked after migration" at
  L283-285) to reference the new module paths
  (`yascheduler.entrypoints.cli.daemon_systemd`,
  `yascheduler.entrypoints.cli.daemon_sysv`).

**Rationale:** The two in-flight changes both rewrite R1 wholesale (their
`## MODIFIED Requirements` deltas replace the full requirement body). If
this change's delta also rewrote R1 wholesale, the three deltas would
collide textually on archive (each `## MODIFIED` replaces the entire
requirement body). By restricting this change's R1 delta to the
enumeration line only (regenerating the delta body at archive time against
the post-merge main-spec scenarios verbatim), the three deltas compose:
the in-flight changes own the scenario edits (the `infra/cli/__init__.py`
and `entrypoints/cli/__init__.py` resident lists), and this change owns the
enumeration-line drop. The
"Entrypoints layer facade" requirement is NOT touched by the in-flight
changes (verified: their `specs/package-facades/spec.md` deltas only
modify R1), so its daemon-launcher prose/scenario path updates are safe to
include in full.

**Sequencing note:** This change MUST be archived AFTER
`relocate-check-status-command` and `relocate-manage-node-command` (so its
R1 enumeration-line drop is generated against the post-merge main spec).
If archived before them, the in-flight changes' R1 deltas would need to be
rebased against the post-this-change main spec (dropping
`yascheduler.entrypoints.daemon` from their enumeration too). Either
sequencing is resolvable; the recommendation is archive-after to minimize
rebase work.

**Alternatives rejected:**
- *Rewrite R1 wholesale in this change's delta* — collides with the two
  in-flight R1 deltas on archive; risks clobbering the scenario edits.
- *Defer the R1 enumeration drop to a separate change* — adds a change for
  a one-line edit; the enumeration drop is a direct consequence of the
  subpackage removal and belongs in this change.
- *Touch the R1 scenarios in this change's delta* — would clobber the
  in-flight edits to those scenarios (the `infra/cli/__init__.py` /
  `entrypoints/cli/__init__.py` resident lists).

### D7 — Knowledge graph: update paths, delete the subpackage-facade node

**Choice:** In `docs/knowledge-graph.xml`:
- `M-DAEMON-SYSTEMD <path>` (L117): `yascheduler/entrypoints/daemon/daemon_systemd.py`
  → `yascheduler/entrypoints/cli/daemon_systemd.py`. `<depends>` and
  `<annotations>` unchanged.
- `M-DAEMON-SYSV <path>` (L125): `yascheduler/entrypoints/daemon/daemon_sysv.py`
  → `yascheduler/entrypoints/cli/daemon_sysv.py`. `<depends>` and
  `<fn-start_daemon ...>` annotation unchanged.
- Delete the `M-ENTRYPOINTS-DAEMON` element (L132-138). Per GRACE-lite
  "module removed → drop M- entry" rule.
- `DF-DAEMON-START` (L929: `M-DAEMON-SYSTEMD / M-DAEMON-SYSV -> M-CLI-COMMANDS`)
  stays unchanged — it references the launcher M-IDs (not the subpackage
  facade).
- No new `M-ENTRYPOINTS-CLI-DAEMON` node is added — the launchers are
  siblings inside `entrypoints/cli/`, not a sub-package; their M-IDs
  (`M-DAEMON-SYSTEMD`, `M-DAEMON-SYSV`) stay as-is (the M-ID namespace is
  not path-derived; renaming the M-IDs would be churn against the
  existing `LINKS:` references and the `DF-DAEMON-START` edge).

**Rationale:** `M-ENTRYPOINTS-DAEMON` has NO inbound `CrossLink` and NO
`DF-*` reference (verified by grep: only its own block references the ID,
via the deleted `entrypoints/daemon/__init__.py:7` `LINKS:` self-reference),
so deletion is graph-safe. The launcher M-IDs stay (their identity is
stable across relocations, matching the precedent that
`M-ENTRYPOINTS-CLI-INIT` did not get renamed when `init.py` moved from
`infra/cli/` to `entrypoints/cli/`).

**Alternatives rejected:**
- *Rename `M-DAEMON-SYSTEMD` → `M-ENTRYPOINTS-CLI-DAEMON-SYSTEMD`* — the
  M-ID is a stable identity, not a path; renaming forces a `LINKS:` /
  `CrossLink` / `DF-*` sweep with no semantic gain. The four
  `relocate-*-command` predecessors did NOT rename their M-IDs on
  relocation (e.g. `M-ENTRYPOINTS-CLI-INIT` was created fresh because the
  module was new to the graph; but the launcher M-IDs already exist and
  are referenced by `DF-DAEMON-START`).

## Risks / Trade-offs

| Risk | Mitigation |
| --- | --- |
| Operators running an upgraded package without re-running `yainit` have a service file pointing at the removed `entrypoints/daemon/daemon_*.py` path; `ExecStart` fails with `python3: can't open file …`. | Documented as **BREAKING (re-install)** in `proposal.md`. The upgrade procedure MUST include a `yainit` re-run (or `yainit --daemon`). This is a one-time step; subsequent upgrades that do not move the launchers do not require it. |
| The two in-flight `relocate-*-command` changes' R1 deltas collide with this change's R1 delta on archive. | D6 restricts this change's R1 delta to the enumeration line only (reproducing the current scenarios verbatim), so the three deltas compose. Sequencing note: archive this change AFTER the two in-flight ones. |
| `working_directory=os.path.dirname(__file__)` shifts CWD again (`daemon/` → `cli/`); a relative path leaks into the daemon's consumption. | D3 accepts the shift as-is, relying on the archived `relocate-daemon-launchers` D6 precedent and the absolute env-overridable defaults in `yascheduler/shared/variables.py:24-26`. If a relative path is discovered during implementation, a follow-up change addresses it; this change does not compensate. |
| The knowledge-graph deletion of `M-ENTRYPOINTS-DAEMON` leaves a dangling `LINKS:` reference in some other module's `MODULE_CONTRACT`. | Verified by grep: `M-ENTRYPOINTS-DAEMON` appears ONLY in `docs/knowledge-graph.xml:132-138` (its own block) and `yascheduler/entrypoints/daemon/__init__.py:7` (its own LINKS, being deleted). `grace_check.py` validates graph integrity and would surface any dangling reference at implementation time. |
| A test asserts the full `entrypoints/daemon/daemon_*.py` path inside the rendered service file and would break. | Verified by grep: `tests/unit/test_cli_init.py:241,257` assert the basename only (`"daemon_systemd.py" in content`, `"daemon_sysv.py" in content`); no test asserts the full path. The basename is preserved by the move. |
| Reviewer/implementation drift on the verbatim-move commitment. | The tasks checklist enumerates the exact byte-level edits (`# FILE:`, `VERSION`, `START_CHANGE_SUMMARY`) and the exact unchanged substrings (imports, `if __name__ == "__main__":`, `start_daemon` body, `working_directory`). |
| The `entrypoints/cli/__init__.py` facade currently has NO `__all__`; the proposal mentions `__all__` in the context of the `entrypoints/__init__.py` facade. | D4 clarifies: `entrypoints/cli/__init__.py` adds no `__all__` (consistent with its current state — only a docstring); the `__all__ = ["Yascheduler"]` reference is the `entrypoints/__init__.py` facade's. |

## Migration Plan

**Deployment:** single PR; **requires a `yainit` re-run on upgrade** for any
deployment that installed the service via `yainit` (systemd or SysV). No DB
migration, no config migration, no persistent state.

**Order of operations within the change:**
1. Move `yascheduler/entrypoints/daemon/daemon_systemd.py` →
   `yascheduler/entrypoints/cli/daemon_systemd.py` (verbatim; update
   `# FILE:`, `VERSION`, `START_CHANGE_SUMMARY`).
2. Move `yascheduler/entrypoints/daemon/daemon_sysv.py` →
   `yascheduler/entrypoints/cli/daemon_sysv.py` (verbatim; update
   `# FILE:`, `VERSION`, `START_CHANGE_SUMMARY`).
3. Delete `yascheduler/entrypoints/daemon/__init__.py` and the
   `yascheduler/entrypoints/daemon/` directory.
4. Update `yascheduler/entrypoints/cli/__init__.py` (PURPOSE/SCOPE + LINKS +
   CHANGE_SUMMARY; bump VERSION).
5. Update `yascheduler/entrypoints/__init__.py` (CHANGE_SUMMARY; bump
   VERSION).
6. Update `yascheduler/entrypoints/cli/init.py` (the two `daemon_file`
   path rewrites at L103/L127; bump VERSION; CHANGE_SUMMARY).
7. Update `docs/knowledge-graph.xml` (`M-DAEMON-SYSTEMD`/`M-DAEMON-SYSV`
   `<path>`; delete `M-ENTRYPOINTS-DAEMON`).
8. Update `openspec/specs/package-facades/spec.md` (R1 enumeration drop;
   "Entrypoints layer facade" daemon-launcher prose/scenario paths).
9. Run the verification ladder (`pytest -m unit`, `zuban check`,
   `ruff check`, `ruff format --check`, `lint-imports`, `grace_check.py`,
   `openspec validate --all --json`); smoke-check `yainit --daemon` (or
   the default) produces a service file pointing at
   `entrypoints/cli/daemon_systemd.py` (or the sysv variant).

**Rollback:** revert the PR. No DB migration, no config migration, no
persistent state. The old `entrypoints/daemon/daemon_*.py` files are
restored from git. Operators who re-ran `yainit` against the new path must
re-run `yainit` again after rollback so the service file points at the
restored `entrypoints/daemon/` path.

**Sequencing against in-flight changes:** archive this change AFTER
`relocate-check-status-command` and `relocate-manage-node-command` (so its
R1 enumeration-line drop is generated against the post-merge main spec, per
D6). If the in-flight changes are still in `openspec/changes/` when this
change is implemented, the implementation touches only the main
`openspec/specs/package-facades/spec.md` (the in-flight deltas are
re-applied on their own archive).

## Open Questions

None. All decisions closed during the explore phase and captured above.
Specifically resolved:
- Subpackage liquidation vs. empty-shell retention — liquidation (D1).
- Verbatim move vs. reimplementation — verbatim (D2).
- `working_directory` CWD compensation — accept shift (D3).
- Facade edits declarative-only vs. re-exports — declarative-only (D4).
- `install_path` recomputation vs. unchanged — unchanged (D5).
- R1 delta scope vs. full-rewrite — enumeration-line only (D6).
- M-ID renaming vs. stable identity — stable (D7).
- Sequencing against in-flight changes — archive-after (D6, Migration Plan).