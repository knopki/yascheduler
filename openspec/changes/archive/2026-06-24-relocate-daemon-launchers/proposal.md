## Why

`yascheduler/daemon_systemd.py` and `yascheduler/daemon_sysv.py` are driving
adapter entry points that live at the package root, outside the
`import-linter` layers contract — the same structural debt that
`add-entrypoints-layer` (archived 2026-06-24) set out to retire. That change
moved only `client.py` into `yascheduler.entrypoints/` and explicitly deferred
the daemon launchers to a follow-up; `relocate-aiida-plugin` (archived
2026-06-24) then retired the same debt for `aiida_plugin.py`. The
`package-facades` spec still carries the forward reference "Scheduled for
migration into `yascheduler.entrypoints` in follow-up changes; remain at the
package root in the interim." This change fulfills that deferred commitment
for the two daemon launchers, leaving only `di.py` and `infra/cli/` pending.

## What Changes

- Move `yascheduler/daemon_systemd.py` →
  `yascheduler/entrypoints/daemon/daemon_systemd.py` and
  `yascheduler/daemon_sysv.py` →
  `yascheduler/entrypoints/daemon/daemon_sysv.py` (new subpackage
  `entrypoints/daemon/`). Update `# FILE:` header paths, bump `VERSION`, add
  `START_CHANGE_SUMMARY` entries, and drop the stale `# FIXME: move this
  module to adapters` comment (the move target is `entrypoints`, not
  `adapters`). Convert the relative imports `from .infra.cli import
  daemonize` and `from .shared import LOG_FILE`/`PID_FILE` to absolute facade
  paths `from yascheduler.infra.cli import daemonize` and
  `from yascheduler.shared import LOG_FILE`/`PID_FILE` (matching the
  `entrypoints/client.py` absolute-import convention; relative imports would
  resolve inside the new subpackage and break). The
  `daemon_sysv.py` `start_daemon` body uses
  `working_directory=os.path.dirname(__file__)` as the post-fork CWD for the
  daemon context; after the move this resolves to
  `yascheduler/entrypoints/daemon/` instead of `yascheduler/`. The values it
  feeds (`CONFIG_FILE`, `LOG_FILE`, `PID_FILE` from `yascheduler.shared`) are
  env-derived absolute paths, so the CWD change is benign — accepted as-is
  (no compensation needed). **No compat shim** at the old paths: the old
  module paths cease to exist.
- Add `yascheduler/entrypoints/daemon/__init__.py` as a thin GRACE-lite
  subpackage facade (MODULE_CONTRACT + MODULE_MAP + CHANGE_SUMMARY, no
  re-exports — lazy-publication policy; the launchers are invoked by path from
  service templates, not imported).
- Update `yascheduler/infra/cli/init.py`: `_init_systemd` and `_init_sysv`
  compute the daemon file path as `install_path / "daemon_systemd.py"` and
  `install_path / "daemon_sysv.py"` where `install_path` is the `yascheduler/`
  package dir. Rewrite to `install_path / "entrypoints/daemon/daemon_systemd.py"`
  and `install_path / "entrypoints/daemon/daemon_sysv.py"`. This is the one
  runtime-impacting edit: the systemd unit file and SysV init.d script
  templates use `%YASCHEDULER_DAEMON_FILE%` substitution, so without this
  update installed services would point at non-existent paths and the daemon
  would fail to start. Bump VERSION and add a `START_CHANGE_SUMMARY` entry.
- Update `yascheduler/entrypoints/__init__.py`: revise the
  `START_CHANGE_SUMMARY` to name `client.py` and `aiida_plugin.py` as current
  flat residents and the new `daemon/` subpackage as a third resident, and to
  reflect that only `di.py` and `infra/cli/` remain deferred (fixes a stale
  comment that still lists `aiida_plugin.py` and `daemon_*.py` as pending, even
  though aiida moved in `relocate-aiida-plugin`). Bump VERSION. Do NOT
  re-export the daemon launchers from the facade (lazy-publication; invoked by
  path, not imported).
- Update `docs/knowledge-graph.xml`: `M-DAEMON-SYSTEMD` and `M-DAEMON-SYSV`
  `<path>` values → `yascheduler/entrypoints/daemon/daemon_systemd.py` and
  `yascheduler/entrypoints/daemon/daemon_sysv.py`. `<depends>` stays
  `M-CLI-COMMANDS, M-SHARED` for both (the launchers still import
  `yascheduler.infra.cli.daemonize` and `yascheduler.shared` constants).
  `<annotations>` unchanged (M-DAEMON-SYSV keeps `<fn-start_daemon>`).
- Rewrite affected requirements in
  `openspec/specs/package-facades/spec.md`: the outside-layer-set exemption
  list drops `yascheduler.daemon_systemd` and `yascheduler.daemon_sysv` (now in
  the entrypoints layer, no shim); the "Outside-set modules not flagged for
  layer direction" scenario enumeration drops both. The lazy-publication prose
  (L184 forward-reference sentence naming `daemon_*.py` as a pending
  follow-up) is updated to drop `daemon_*.py` (now migrated), leaving only
  `di.py` and `infra/cli/*` as pending. The "Empty facade is valid for future
  residents" scenario parenthetical "(e.g., CLI, daemon launchers)" (L200) is
  updated to drop "daemon launchers" (no longer a future resident), leaving
  "(e.g., CLI)" — keeping the two edits in the same requirement internally
  consistent. No `import-linter` contract change (the launchers import
  downward `infra.cli` + `shared`, trivially R3-compliant in their new home).
- Refresh `docs/ARCHITECTURE.md`: §1 diagram and §4 Project Structure tree —
  move `daemon_systemd.py` and `daemon_sysv.py` from the "deferred →
  entrypoints" / outside-set box into the PRESENTATION
  (`yascheduler.entrypoints`) block as residents of a new `entrypoints/daemon/`
  subpackage. §2 Component Reference table: the existing `entrypoints/` row's
  resident list is updated to add the `daemon/` subpackage (the table has no
  standalone daemon rows to relocate). No full refresh (unlike
  `relocate-aiida-plugin`, which had broader drift) — point edits limited to
  daemon-related lines.

### Out of scope

- Migrating `di.py` or `infra/cli/` into `entrypoints/` — remain at the package
  root, tracked separately.
- Renaming the launcher modules (keeping `daemon_systemd.py` /
  `daemon_sysv.py` filenames minimizes churn and matches the user's stated
  `entrypoints/daemon` target).
- Adding a compat shim at `yascheduler/daemon_*.py` (the only consumers are the
  service templates, whose path substitution is being updated; no known
  external deep-path importer).
- Adding tests for the daemon launchers (no test currently references
  `daemon_*`; the `init.py` path-substitution edit is behavioral but is covered
  by the existing init flow — a dedicated unit test for the generated service
  file path is deferred to a separate testing change).
- Touching `CHANGELOG.md` (commitizen owns it via `update_changelog_on_bump`).

## Capabilities

### New Capabilities

_None._ The relocation is a structural concern whose requirements (layer
membership, outside-set composition) are expressed as modifications to
existing capabilities.

### Modified Capabilities

- `package-facades`: Outside-layer-set exemption list drops
  `yascheduler.daemon_systemd` and `yascheduler.daemon_sysv` (relocated into
  the `entrypoints/daemon/` subpackage, no shim); the "Outside-set modules not
  flagged for layer direction" scenario enumeration drops both; the
  lazy-publication prose is updated to reflect the `daemon/` subpackage as an
  entrypoints resident.

## Impact

- **Code**: `yascheduler/daemon_systemd.py` and `yascheduler/daemon_sysv.py`
  move to `yascheduler/entrypoints/daemon/`; new
  `yascheduler/entrypoints/daemon/__init__.py`; imports in both moved files
  converted to absolute facade paths; `yascheduler/infra/cli/init.py` daemon
  file path computation updated; `yascheduler/entrypoints/__init__.py`
  CHANGE_SUMMARY revised.
- **Config**: `pyproject.toml` unchanged (`[project.scripts]` points at
  `yascheduler.infra.cli.daemonize:daemonize`, not at the daemon_*.py files;
  `[tool.importlinter]` layers contract unchanged — `entrypoints` is already
  layer 1, and the launchers import downward to `infra`/`shared`).
- **External API**: `from yascheduler import Yascheduler` unchanged. The
  daemon launchers are invoked by path from the systemd unit file and SysV
  init.d script (via `%YASCHEDULER_DAEMON_FILE%` substitution produced by
  `yainit`), not via the Python import system or console scripts. Operators
  who previously ran `yainit` have service files pointing at the old
  `yascheduler/daemon_systemd.py` / `yascheduler/daemon_sysv.py` paths; after
  the package upgrade removes those files, the on-disk service files point at
  non-existent paths and `systemctl start yascheduler` /
  `/etc/init.d/yascheduler start` fails. `init.py` does NOT auto-migrate
  existing service files (`_init_systemd` / `_init_sysv` gate the write on
  `if not <file>.is_file():`, so re-running `yainit` while the old service
  file exists silently skips the write) — operators must remove the existing
  service file (`rm /lib/systemd/system/yascheduler.service` or
  `rm /etc/init.d/yascheduler`, after stopping/disabling the service) before
  re-running `yainit` to regenerate it with the new path. This is consistent
  with the existing `init.py` behavior (it never overwrites existing service
  files). Release notes must call out this manual removal step. **BREAKING**
  only for downstream code that pinned
  `from yascheduler.daemon_systemd import …` or
  `from yascheduler.daemon_sysv import …` (no such caller is known; the modules
  have no importable public surface beyond `__main__` / `start_daemon`, which
  are invoked by path).
- **Specs**: `openspec/specs/package-facades/spec.md` rewritten in the
  affected requirements (outside-set exemption + scenario enumeration +
  lazy-publication prose).
- **Knowledge graph**: `docs/knowledge-graph.xml` `M-DAEMON-SYSTEMD` and
  `M-DAEMON-SYSV` `<path>` updates.
- **Docs**: `docs/ARCHITECTURE.md` point edits (§1 diagram, §2 table, §4 tree)
  for daemon-related lines.
- **Dependencies**: none added or removed.