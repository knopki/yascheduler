## Context

`yascheduler` has a hexagonal / clean-architecture layout enforced by
`import-linter` via a `layers` contract in `pyproject.toml`. The current
contract is five layers:

```
yascheduler.entrypoints → yascheduler.infra → yascheduler.application → yascheduler.domain → yascheduler.shared
```

`add-entrypoints-layer` (archived 2026-06-24) introduced the `entrypoints`
layer and moved `client.py` into it as the first resident. It explicitly
deferred `aiida_plugin.py`, `di.py`, `daemon_*.py`, and `infra/cli/` to
follow-up changes. `relocate-aiida-plugin` (archived 2026-06-24) then retired
the same structural debt for `aiida_plugin.py` (flat file
`entrypoints/aiida_plugin.py`, no shim). This change does the same for the two
daemon launchers, leaving only `di.py` and `infra/cli/` pending.

The two daemon launchers are structurally simpler than the AiiDA plugin in one
respect (no pyproject entry-point registry, no DI stub, no test references)
and structurally more delicate in another: they are invoked **by path** from
the systemd unit file template (`yascheduler/data/yascheduler.service`,
`ExecStart=/usr/bin/python3 %YASCHEDULER_DAEMON_FILE%`) and the SysV init.d
template (`yascheduler/data/yascheduler.sh`,
`yascheduler=%YASCHEDULER_DAEMON_FILE%`). The placeholder
`%YASCHEDULER_DAEMON_FILE%` is substituted by `yascheduler/infra/cli/init.py`
(`_init_systemd` at L57 uses `install_path / "daemon_systemd.py"`,
`_init_sysv` at L72 uses `install_path / "daemon_sysv.py"`, with
`install_path = Path(__file__).parent.parent.parent` = the `yascheduler/`
package dir). Moving the files without updating `init.py` would leave
installed service files pointing at non-existent paths — the daemon would
fail to start on `systemctl start yascheduler` / `/etc/init.d/yascheduler
start`. This path-substitution update is the one runtime-impacting edit in the
change and is called out explicitly in the proposal.

Constraints:
- Public interface stability (AGENTS.md): `from yascheduler import
  Yascheduler`, `from yascheduler.client import Yascheduler` (shim), the
  AiiDA scheduler entrypoint (by *name*, not module path), and the CLI
  commands (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`, `yainit`,
  `yascheduler`) must remain stable. The daemon launchers are NOT in this
  list — they are operational entry points invoked by the init system via the
  substituted path, not a public Python API.
- `import-linter` layers contract: `yascheduler.entrypoints` is already layer
  1; the launchers import downward to `yascheduler.infra.cli.daemonize` and
  `yascheduler.shared`, so they are trivially R3-compliant in their new home
  — no contract change.
- GRACE-lite: knowledge graph and module contracts updated in the same
  change.
- No new dependencies. Python `>=3.9`.
- `CHANGELOG.md` is commitizen-managed (`update_changelog_on_bump`) — not
  touched.

## Goals / Non-Goals

**Goals:**
- Relocate `yascheduler/daemon_systemd.py` →
  `yascheduler/entrypoints/daemon/daemon_systemd.py` and
  `yascheduler/daemon_sysv.py` →
  `yascheduler/entrypoints/daemon/daemon_sysv.py` (subdirectory, per user
  instruction), with a thin `entrypoints/daemon/__init__.py` subpackage
  facade. No compat shim at the old paths. Drop the stale
  `# FIXME: move this module to adapters` comment from both moved files (the
  move target is `entrypoints`, not `adapters`).
- Convert the relative imports in both moved files
  (`from .infra.cli import daemonize`, `from .shared import LOG_FILE` /
  `PID_FILE`) to absolute facade paths
  (`from yascheduler.infra.cli import daemonize`,
  `from yascheduler.shared import LOG_FILE` / `PID_FILE`), matching the
  `entrypoints/client.py` absolute-import convention.
- Update `yascheduler/infra/cli/init.py` daemon-file path computation
  (`install_path / "daemon_systemd.py"` →
  `install_path / "entrypoints/daemon/daemon_systemd.py"`, and the same for
  sysv) so installed service files point at the new locations.
- Update `yascheduler/entrypoints/__init__.py` CHANGE_SUMMARY to name
  `client.py` and `aiida_plugin.py` as current flat residents and the new
  `daemon/` subpackage as a third resident, dropping the stale listing of
  `aiida_plugin.py` and `daemon_*.py` as pending. Do NOT re-export the daemon
  launchers from the facade (lazy publication; invoked by path, not
  imported).
- Update `docs/knowledge-graph.xml`: `M-DAEMON-SYSTEMD` and `M-DAEMON-SYSV`
  `<path>` values to the new subpackage paths; `<depends>` and
  `<annotations>` unchanged. Add a new `M-ENTRYPOINTS-DAEMON` module entry
  for the `entrypoints/daemon/__init__.py` subpackage facade (per GRACE-lite
  "module added → M- entry" rule; mirrors the existing `M-ENTRYPOINTS` entry
  for `entrypoints/__init__.py`).
- Rewrite affected requirements in `openspec/specs/package-facades/spec.md`:
  drop `yascheduler.daemon_systemd` and `yascheduler.daemon_sysv` from the
  outside-layer-set exemption list and the "Outside-set modules not flagged
  for layer direction" scenario enumeration; update the lazy-publication
  forward-reference sentence (L184) to drop `daemon_*.py` (leaving only
  `di.py` and `infra/cli/*` as pending); update the "Empty facade is valid for
  future residents" scenario parenthetical (L200) to drop "daemon launchers"
  (leaving "(e.g., CLI)").
- Point-edit `docs/ARCHITECTURE.md` §1 diagram, §2 Component Reference
  table (the `entrypoints/` row's resident list), and §4 Project Structure
  tree to move the daemon launchers from "deferred → entrypoints" /
  outside-set into the `entrypoints/daemon/` subpackage.

**Non-Goals:**
- Migrate `di.py` or `infra/cli/` into `entrypoints/`. Remain at the package
  root, tracked separately.
- Rename the launcher modules (keep `daemon_systemd.py` /
  `daemon_sysv.py` filenames — minimizes churn and matches the user's stated
  `entrypoints/daemon` target).
- Add a compat shim at `yascheduler/daemon_*.py` (the only consumers are the
  service templates, whose path substitution is being updated; no known
  external deep-path importer).
- Add tests for the daemon launchers or the `init.py` path-substitution
  edit. No test currently references `daemon_*`; a dedicated unit test for
  the generated service file path is deferred to a separate testing change.
- Touch `CHANGELOG.md`.
- Promote the daemon launchers to the `entrypoints` facade (lazy
  publication: invoked by path from service templates, not imported).
- Compensate the `daemon_sysv.py` `start_daemon`
  `working_directory=os.path.dirname(__file__)` CWD change (post-fork CWD
  shifts from `yascheduler/` to `yascheduler/entrypoints/daemon/`, but the
  consumed paths `CONFIG_FILE` / `LOG_FILE` / `PID_FILE` are env-derived
  absolute paths — benign, accepted as-is).

## Decisions

### D1. Target path: subpackage `entrypoints/daemon/`

**Choice:** `yascheduler/entrypoints/daemon/daemon_systemd.py` and
`yascheduler/entrypoints/daemon/daemon_sysv.py`, with a thin
`entrypoints/daemon/__init__.py` subpackage marker.

**Rationale:** The user explicitly requested `entrypoints/daemon`
(subcategory), not the flat-file treatment used for `client.py` and
`aiida_plugin.py`. The two launchers form a natural pair (systemd vs sysv
init systems for the same daemon), so grouping them under a `daemon/`
subpackage signals the pairing without adding ceremony. A thin
`__init__.py` carries the GRACE-lite MODULE_CONTRACT for the subpackage
facade and re-exports nothing (lazy-publication; the launchers are invoked by
path, not imported across layers).

**Alternatives considered:**
- `entrypoints/daemon_systemd.py` + `entrypoints/daemon_sysv.py` (flat files,
  matching the `aiida_plugin.py` precedent) — rejected: user explicitly
  asked for the `daemon/` subpackage; flat files would scatter the two
  launchers among the other entrypoints residents and lose the pairing
  signal.
- `entrypoints/daemon/__main__.py` (single module invoked via
  `python -m yascheduler.entrypoints.daemon`) — rejected: the service
  templates invoke a specific `.py` file via `%YASCHEDULER_DAEMON_FILE%`
  substitution, not `python -m`; restructuring to `-m` invocation would
  require changing the templates and the init.py substitution mechanism, a
  larger change than the user asked for.

### D2. No compat shim at the old paths

**Choice:** `yascheduler/daemon_systemd.py` and `yascheduler/daemon_sysv.py`
cease to exist; no shim.

**Rationale:** The only consumers of the file *paths* (not the importable
surface) are the service templates `yascheduler/data/yascheduler.service` and
`yascheduler/data/yascheduler.sh`, whose `%YASCHEDULER_DAEMON_FILE%`
placeholder is substituted by `init.py` — and `init.py` is being updated to
the new paths in this same change. The launchers have no importable public
surface beyond `__main__` blocks and `start_daemon`, which are invoked by
path (via `ExecStart=/usr/bin/python3 <path>` and `$yascheduler -p ... -l
...`), not via `import`. No known external caller uses
`from yascheduler.daemon_systemd import …` or
`from yascheduler.daemon_sysv import …`, and the project does not commit to
preserving those deep paths (unlike `yascheduler.client`, which has an
explicit shim requirement in `package-facades`). A shim would be dead weight
serving no consumer.

**Alternatives considered:**
- Mirror the `yascheduler/client.py` shim treatment — rejected: `client.py`
  has an explicit spec-grounded shim requirement (external downstream
  consumers use `from yascheduler.client import Yascheduler`); the daemon
  launchers have no such requirement and no known external importer.
- Keep the old files as re-export shims that `from yascheduler.entrypoints.daemon.daemon_systemd import *` — rejected: same lack of consumer, and would keep stale files at the package root indefinitely.

### D3. Relative → absolute imports in the moved files

**Choice:** Convert `from .infra.cli import daemonize` →
`from yascheduler.infra.cli import daemonize` and
`from .shared import LOG_FILE` / `PID_FILE` →
`from yascheduler.shared import LOG_FILE` / `PID_FILE` in both moved files.

**Rationale:** Inside `entrypoints/daemon/`, the relative `.infra` would
resolve to `yascheduler.entrypoints.daemon.infra` (non-existent) and `.shared`
to `yascheduler.entrypoints.daemon.shared` (non-existent) — both would break
at import time. Two-dots-up relative (`from ..infra.cli import daemonize`)
would work but is less readable and inconsistent with the `entrypoints/client.py`
convention, which uses absolute facade paths throughout
(`from yascheduler.application import query_tasks`,
`from yascheduler.config import Config`, `from yascheduler.di import …`,
`from yascheduler.domain import …`, `from yascheduler.shared import …`).
Absolute paths match the established entrypoints convention and are
self-documenting.

**Alternatives considered:**
- `from ..infra.cli import daemonize` (two-dots-up relative) — rejected:
  works but is less readable and breaks the entrypoints-layer
  absolute-import convention.
- Keep `from .infra.cli import daemonize` and rely on the subpackage
  `__init__.py` to re-export — rejected: the subpackage `__init__.py` is a
  facade, not a name rebinder; relative `.infra` from inside `daemon/` does
  not reach `yascheduler.infra`.

### D4. `init.py` daemon-file path computation update

**Choice:** In `yascheduler/infra/cli/init.py`, rewrite
`_init_systemd`'s `daemon_file = install_path / "daemon_systemd.py"` →
`daemon_file = install_path / "entrypoints/daemon/daemon_systemd.py"` and
`_init_sysv`'s `daemon_file = install_path / "daemon_sysv.py"` →
`daemon_file = install_path / "entrypoints/daemon/daemon_sysv.py"`. Leave the
`install_path = Path(__file__).parent.parent.parent` computation unchanged
(it still resolves to the `yascheduler/` package dir, which is the correct
prefix for the new subpackage path).

**Rationale:** This is the one runtime-impacting edit. The systemd unit file
template (`yascheduler/data/yascheduler.service`) uses
`ExecStart=/usr/bin/python3 %YASCHEDULER_DAEMON_FILE%`, and the SysV init.d
template (`yascheduler/data/yascheduler.sh`) uses
`yascheduler=%YASCHEDULER_DAEMON_FILE%`. `_init_systemd` / `_init_sysv`
read the template, substitute `%YASCHEDULER_DAEMON_FILE%` with the computed
`daemon_file` absolute path, and write the result to `/lib/systemd/system/
yascheduler.service` / `/etc/init.d/yascheduler`. Without the path update,
newly-installed services would point at the old (now non-existent) paths and
the daemon would fail to start.

Operators who previously ran `yainit` have service files at the old paths on
disk; those keep working until the package upgrade removes the old
`yascheduler/daemon_*.py` files, at which point the on-disk service files
point at non-existent paths and `systemctl start yascheduler` /
`/etc/init.d/yascheduler start` fails. `init.py` does NOT auto-migrate
existing service files: `_init_systemd` (L53) and `_init_sysv` (L68) gate the
write on `if not unit_file.is_file():` / `if not startup_file.is_file():`, so
re-running `yainit` while the old service file exists silently skips the
write. Operators must therefore **remove the existing service file**
(`rm /lib/systemd/system/yascheduler.service`, `rm /etc/init.d/yascheduler` —
typically after `systemctl stop yascheduler && systemctl disable yascheduler`
or the SysV equivalent) before re-running `yainit` to regenerate it with the
new path. This is consistent with the existing `init.py` behavior (it never
overwrites an existing service file).

**Alternatives considered:**
- Make `init.py` compute the path dynamically via
  `import yascheduler.entrypoints.daemon.daemon_systemd as m; Path(m.__file__)`
  — rejected: adds an import side-effect dependency to a CLI installer that
  currently only does string substitution; the static path is simpler and
  equally correct.
- Add a migration step to `init.py` that rewrites existing
  `/lib/systemd/system/yascheduler.service` and `/etc/init.d/yascheduler`
  files to the new path — rejected: out of scope (the proposal commits to no
  behavioral change beyond the path); operators remove the existing service
  file then re-run `yainit` to regenerate it with the new path, which is the
  existing model (`init.py` never overwrites an existing service file).

### D5. `entrypoints/__init__.py` CHANGE_SUMMARY revision

**Choice:** Revise the `START_CHANGE_SUMMARY` to name `client.py` and
`aiida_plugin.py` as current flat residents and the new `daemon/` subpackage
as a third resident; reflect that only `di.py` and `infra/cli/` remain
deferred. Bump VERSION. Do NOT re-export the daemon launchers from the
facade (`__all__` stays `["Yascheduler"]`).

**Rationale:** The current CHANGE_SUMMARY (VERSION 1.0.0, from
`add-entrypoints-layer`) says "only client.py resident. di.py,
aiida_plugin.py, daemon_*.py, infra/cli/ migrate in follow-up changes." This
is now stale on two counts: `aiida_plugin.py` already moved (in
`relocate-aiida-plugin`), and `daemon_*.py` is moving in THIS change. The
revision brings the comment current and leaves only `di.py` and `infra/cli/`
as the pending follow-ups. The lazy-publication policy (per
`package-facades`) means the facade re-exports only what a cross-layer
consumer needs; the daemon launchers have no such consumer (invoked by path),
so they are not re-exported.

**Alternatives considered:**
- Re-export `start_daemon` from the facade for symmetry — rejected:
  `start_daemon` is invoked by the sysv `__main__` block via `python
  <path>`, not imported; adding it to the facade widens the public surface
  for no consumer, violating lazy-publication.

### D6. `daemon_sysv.py` post-fork CWD change accepted as-is

**Choice:** The `start_daemon` body uses
`working_directory=os.path.dirname(__file__)` as the post-fork CWD for the
`daemon.DaemonContext`. After the move, `__file__` resolves to
`yascheduler/entrypoints/daemon/daemon_sysv.py`, so the CWD shifts from
`yascheduler/` to `yascheduler/entrypoints/daemon/`. Accept this change
without compensation.

**Rationale:** The CWD only matters for *relative* path resolution. The
paths consumed inside the daemon context — `pid_file` and `log_file`
arguments, plus `CONFIG_FILE` / `LOG_FILE` / `PID_FILE` from
`yascheduler.shared` — are env-overridable absolute-path defaults
(`YASCHEDULER_CONF_PATH` / `YASCHEDULER_LOG_PATH` / `YASCHEDULER_PID_PATH`
in `shared/variables.py`). Absolute paths do not depend on CWD. The shift is
therefore benign. Compensating with
`Path(__file__).parent.parent.parent` would preserve the old CWD but add
fragile parent-walking tied to directory depth; accepting the new CWD is
simpler and behaviorally equivalent for the absolute paths actually in use.

**Alternatives considered:**
- Pin `working_directory` to the package root via
  `Path(__file__).parent.parent.parent` — rejected: adds depth-coupled
  fragility for no behavioral benefit (no relative path is consumed).

### D7. ARCHITECTURE.md point edits, not full refresh

**Choice:** Point-edit `docs/ARCHITECTURE.md` §1 diagram, §2 Component
Reference table (`entrypoints/` row's resident list), and §4 Project
Structure tree to move the daemon launchers from "deferred → entrypoints" /
outside-set into the `entrypoints/daemon/` subpackage. Do NOT full-refresh
the file.

**Rationale:** Unlike `relocate-aiida-plugin` (which full-refreshed
ARCHITECTURE.md because the file had drifted across several past changes),
the only daemon-related drift here is the "deferred → entrypoints" framing
itself — which is exactly what this change retires. Point edits are
sufficient and lower-risk than a full rewrite. In the §1 diagram, the two
daemon lines currently live at L97-98 inside the "COMPOSITION ROOT /
OUTSIDE-LAYER-SET" box; the point-edit moves them out of that box and adds a
`daemon/` entry to the "PRESENTATION (`yascheduler.entrypoints`)" box (L22)
as a third resident. The §2 Component Reference table's `entrypoints/` row
already lists `client.py` and `aiida_plugin.py` and only needs `daemon/`
added. The §4 tree already shows the `entrypoints/` subtree and only needs
the `daemon/` subpackage added. No stale "uses Yascheduler client" claim, no
stale `make_aiida()` reference, no stale §6/§7 to delete here.

**Alternatives considered:**
- Full refresh matching `relocate-aiida-plugin` — rejected: no comparable
  drift to correct; a full refresh would risk introducing new inaccuracies
  for no benefit.

## Risks / Trade-offs

- **Risk:** Operators with previously-installed service files at the old
  `yascheduler/daemon_systemd.py` / `yascheduler/daemon_sysv.py` paths find
  the daemon fails to start after a package upgrade that moves the files,
  because their on-disk service files still point at the old paths.
  → **Mitigation:** The old files are removed in the same change, so the
  breakage is real. `init.py` does NOT auto-migrate existing service files:
  `_init_systemd` (L53) and `_init_sysv` (L68) gate the write on
  `if not <file>.is_file():`, so re-running `yainit` while the old service
  file exists silently skips the write. Operators must remove the existing
  service file (`rm /lib/systemd/system/yascheduler.service` or
  `rm /etc/init.d/yascheduler`, after stopping/disabling the service) before
  re-running `yainit` to regenerate it with the new path. The release notes
  must call out this manual removal step. Accepted as the existing
  operational model (the installer has never overwritten existing service
  files).
- **Risk:** Downstream code pins `from yascheduler.daemon_systemd import …`
  or `from yascheduler.daemon_sysv import …`.
  → **Mitigation:** No such external caller is known; the modules have no
  importable public surface beyond `__main__` / `start_daemon`, which are
  invoked by path. Accepted as **BREAKING** for the (unknown, likely empty)
  set of deep-path importers.
- **Risk:** The `daemon_sysv.py` post-fork CWD change (from `yascheduler/`
  to `yascheduler/entrypoints/daemon/`) breaks a hidden relative-path
  consumer.
  → **Mitigation:** Verified the paths consumed inside the daemon context
  (`pid_file`, `log_file`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`) are all
  env-derived absolute paths; no relative path is consumed. Accepted as
  benign (D6).
- **Risk:** ARCHITECTURE.md point edits miss a daemon-related reference
  elsewhere in the file.
  → **Mitigation:** A stale-reference sweep
  (`rg -n "daemon_systemd|daemon_sysv" docs/ARCHITECTURE.md`) is in the
  verification tasks to catch any remaining mentions.
- **Risk:** `entrypoints/daemon/__init__.py` becomes a maintenance burden.
  → **Mitigation:** The subpackage facade is a thin GRACE-lite
  MODULE_CONTRACT + MODULE_MAP + CHANGE_SUMMARY with no re-exports; it
  updates only when the subpackage's resident set changes (low frequency).

## Migration Plan

This is a source-level relocation; no runtime data migration is needed.

1. Apply the two file moves, the new `entrypoints/daemon/__init__.py`, the
   relative→absolute import conversion in both moved files, the `init.py`
   daemon-file path computation update, the `entrypoints/__init__.py`
   CHANGE_SUMMARY revision, the knowledge graph path updates, the
   package-facades spec rewrites, and the ARCHITECTURE.md point edits in one
   change.
2. Reinstall the package (`uv pip install -e .` or `uv sync`) so the old
   `yascheduler/daemon_*.py` module paths are no longer in the installed
   metadata.
3. Verify the moved modules import cleanly:
   `python -c "import yascheduler.entrypoints.daemon.daemon_systemd; import yascheduler.entrypoints.daemon.daemon_sysv; print('import OK')"`.
4. Verify the `init.py` path computation produces the new paths:
   `python -c "from pathlib import Path; install_path = Path('yascheduler/infra/cli/init.py').resolve().parent.parent.parent; print(install_path / 'entrypoints/daemon/daemon_systemd.py'); print(install_path / 'entrypoints/daemon/daemon_sysv.py')"`
   — confirm both paths exist after the move.
5. Run `uv run pytest -m unit`, `uv run lint-imports`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run zuban check`,
   `python3 scripts/grace_check.py`, `openspec validate --all --json`.
6. Stale-reference sweep:
   `rg -n "yascheduler\.daemon_systemd\b|yascheduler\.daemon_sysv\b" --glob '!openspec/changes/archive/**' --glob '!*.egg-info/**'`
   — confirm zero references to the old deep paths in non-archived,
   non-egg-info files (the only acceptable hits are inside archived
   OpenSpec change proposals, which are historical, and this change's own
   propositional artifacts describing the old→new transition).
7. Release notes should call out: "operators who previously ran `yainit`
   must first remove the existing service file
   (`rm /lib/systemd/system/yascheduler.service` for systemd, or
   `rm /etc/init.d/yascheduler` for SysV — after `systemctl stop
   yascheduler` / the SysV equivalent), then re-run `yainit` to regenerate
   the service file with the new daemon file path. Re-running `yainit` while
   the old service file exists silently skips the write (`init.py` never
   overwrites existing service files)."

**Rollback:** Revert the change commit. The old files reappear at the
package root; the old `init.py` path computation is restored; installed
service files (which were never auto-rewritten) keep pointing at the old
paths and work again. No data migration, no schema change.

## Open Questions

None remaining. All resolved during exploration:

- Shim or no shim → no shim (D2).
- Subpackage or flat files → subpackage (D1, per user instruction).
- Relative or absolute imports in moved files → absolute (D3).
- `init.py` path computation update → static path prefix update (D4).
- `daemon_sysv.py` post-fork CWD change → accept as-is, benign (D6).
- ARCHITECTURE.md framing → point edits, not full refresh (D7).
- Test coverage for `init.py` path substitution → out of scope (deferred
  to a separate testing change).
- CHANGELOG → not touched.
- Change name → `relocate-daemon-launchers` (matches
  `relocate-aiida-plugin` precedent).