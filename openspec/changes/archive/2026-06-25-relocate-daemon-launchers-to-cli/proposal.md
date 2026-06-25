## Why

`yascheduler/entrypoints/daemon/daemon_systemd.py` and
`yascheduler/entrypoints/daemon/daemon_sysv.py` are daemon *launcher* entry
points invoked by path from service templates (via `%YASCHEDULER_DAEMON_FILE%`
substitution produced by `yainit`). The archived `relocate-daemon-launchers`
change moved them from the package root into a dedicated `entrypoints/daemon/`
subpackage. That subpackage now hosts only these two launcher files and their
`__init__.py` facade — there is no other resident and no distinct "daemon"
concern separate from "CLI/entry-point" concerns. The four recent relocation
changes (`relocate-init-command`, `relocate-show-nodes-command`,
`relocate-submit-command`, `relocate-manage-node-command`) established
`entrypoints/cli/` as the single home for operator-facing entry points
(`yainit`, `yanodes`, `yasubmit`, `yasetnode`). The daemon launchers are the
same kind of operator entry point — they live in the same `entrypoints` layer
and import the same `yascheduler.infra.cli.daemonize` callable — and they do
not warrant their own subpackage. Collapsing `entrypoints/daemon/` into
`entrypoints/cli/` reduces the entrypoints subpackage count by one, removes a
needless indirection layer, and aligns with the established "one entrypoints
subpackage per concern family" pattern (CLI commands and daemon launchers are
both operator-facing entry points sharing the same dependency direction
`entrypoints → infra.cli`).

## What Changes

- Move `yascheduler/entrypoints/daemon/daemon_systemd.py` →
  `yascheduler/entrypoints/cli/daemon_systemd.py` (real move, not a shim).
  Update the `# FILE:` header path to the new location. Bump `VERSION`. Add
  a `START_CHANGE_SUMMARY` entry referencing this change (PREVIOUS_CHANGE
  stays as the v1.7.0 `relocate-daemon-launchers` entry). The
  `MODULE_CONTRACT PURPOSE`/`SCOPE`/`DEPENDS: M-CLI-COMMANDS, M-SHARED`/
  `LINKS: M-CLI-COMMANDS, M-SHARED` stay unchanged (the launcher still imports
  `daemonize` from `yascheduler.infra.cli` and `LOG_FILE` from
  `yascheduler.shared`). The `if __name__ == "__main__":` block body stays
  unchanged.
- Move `yascheduler/entrypoints/daemon/daemon_sysv.py` →
  `yascheduler/entrypoints/cli/daemon_sysv.py` (real move, not a shim).
  Update the `# FILE:` header path. Bump `VERSION`. Add a
  `START_CHANGE_SUMMARY` entry referencing this change (PREVIOUS_CHANGE stays
  as the v1.7.0 entry). The `MODULE_CONTRACT PURPOSE`/`SCOPE`/`DEPENDS:
  M-CLI-COMMANDS, M-SHARED`/`LINKS: M-CLI-COMMANDS, M-SHARED` stay unchanged.
  The `start_daemon` body (incl. `working_directory=os.path.dirname(__file__)`)
  and the argparse `__main__` block stay unchanged. The `working_directory`
  CWD side-effect shifts again (from `yascheduler/entrypoints/daemon/` to
  `yascheduler/entrypoints/cli/`); as established by
  `relocate-daemon-launchers`, the consumed paths (`CONFIG_FILE`, `LOG_FILE`,
  `PID_FILE`) are env-overridable absolute defaults, so the CWD shift is
  benign and accepted as-is (no `Path(__file__).parent.parent.parent`
  compensation).
- Delete `yascheduler/entrypoints/daemon/__init__.py` and remove the empty
  `yascheduler/entrypoints/daemon/` directory. No compat shim: the launchers
  are invoked by path from service templates (not imported across layers),
  and no `__init__.py` re-exports any symbol from the subpackage — there is
  nothing to re-export (the facade's own `MODULE_CONTRACT` SCOPE declares
  "no re-exports"). A re-export shim at the old subpackage path would also be
  unreachable by the service-template invocation mechanism (the templates
  substitute an absolute filesystem path, not an import path).
- Update `yascheduler/entrypoints/cli/__init__.py` facade: bump `VERSION`;
  revise the `START_MODULE_CONTRACT PURPOSE`/`SCOPE` to add the daemon
  launchers alongside `init`, `show_nodes`, `submit`, `manage_node` as
  residents (the launchers are invoked by path from service templates, not
  re-exported — same lazy-publication stance as the four CLI commands); add
  `M-DAEMON-SYSTEMD` and `M-DAEMON-SYSV` to the `LINKS`; append a
  `START_CHANGE_SUMMARY` entry noting the daemon launchers are now sibling
  residents (moved from `entrypoints/daemon/` in this change). `__all__`
  stays `["Yascheduler"]` — no new re-exports (the launchers are not imported
  across layers; they are invoked by path).
- Update `yascheduler/entrypoints/__init__.py` facade: bump `VERSION`; revise
  the `START_CHANGE_SUMMARY LAST_CHANGE` entry to drop the
  `daemon/ subpackage resident` clause and add the
  `daemon_systemd.py`/`daemon_sysv.py` now residents of `entrypoints/cli/`
  clause. The `MODULE_CONTRACT PURPOSE`/`SCOPE`/`DEPENDS`/`LINKS` and the
  `MODULE_MAP` stay unchanged (the facade's public surface — re-exporting
  `Yascheduler` only — is unchanged; only the resident-set commentary in
  `CHANGE_SUMMARY` is updated).
- Update `yascheduler/entrypoints/cli/init.py` (the `yainit` installer):
  - In `_init_systemd` (L103): rewrite
    `daemon_file = install_path / "entrypoints/daemon/daemon_systemd.py"` →
    `daemon_file = install_path / "entrypoints/cli/daemon_systemd.py"`. The
    `install_path = Path(__file__).parent.parent.parent` computation (L60)
    stays unchanged — it still resolves to the `yascheduler/` package dir,
    which is the correct prefix for the new subpackage path. The
    `%YASCHEDULER_DAEMON_FILE%` substitution into `yascheduler/data/yascheduler.service`
    (`ExecStart=/usr/bin/python3 %YASCHEDULER_DAEMON_FILE%`) now produces the
    new absolute path.
  - In `_init_sysv` (L127): rewrite
    `daemon_file = install_path / "entrypoints/daemon/daemon_sysv.py"` →
    `daemon_file = install_path / "entrypoints/cli/daemon_sysv.py"`. The
    `%YASCHEDULER_DAEMON_FILE%` substitution into `yascheduler/data/yascheduler.sh`
    (`yascheduler=%YASCHEDULER_DAEMON_FILE%`) now produces the new absolute
    path.
  - Bump `VERSION` in the `# FILE:` header; append a `START_CHANGE_SUMMARY`
    entry noting the daemon-file path computation update
    (`entrypoints/daemon/daemon_*.py` → `entrypoints/cli/daemon_*.py` to track
    the relocated launchers). The `MODULE_CONTRACT PURPOSE`/`SCOPE`/`DEPENDS`/
    `LINKS` stay unchanged.
- Update `docs/knowledge-graph.xml`:
  - Update `M-DAEMON-SYSTEMD <path>` (L117) from
    `yascheduler/entrypoints/daemon/daemon_systemd.py` →
    `yascheduler/entrypoints/cli/daemon_systemd.py`. The
    `<depends>M-CLI-COMMANDS, M-SHARED</depends>` and the empty
    `<annotations>` stay unchanged.
  - Update `M-DAEMON-SYSV <path>` (L125) from
    `yascheduler/entrypoints/daemon/daemon_sysv.py` →
    `yascheduler/entrypoints/cli/daemon_sysv.py`. The
    `<depends>M-CLI-COMMANDS, M-SHARED</depends>` and the
    `<fn-start_daemon ...>` annotation stay unchanged.
  - Delete the `M-ENTRYPOINTS-DAEMON` module element (L132-138). Per GRACE-lite
    "module removed → drop M- entry" rule. The element has no inbound
    `CrossLink` and no `DF-*` reference (verified: only its own block
    references the ID), so deletion is graph-safe.
  - Confirm `DF-DAEMON-START` (L929:
    `M-DAEMON-SYSTEMD / M-DAEMON-SYSV -> M-CLI-COMMANDS`) stays unchanged (it
    references the launcher M-IDs, not the subpackage facade).
- Update `openspec/specs/package-facades/spec.md`:
  - R1 requirement: drop `yascheduler.entrypoints.daemon` from the
    enumeration of subpackages subject to within-package relative-import R1
    (the subpackage no longer exists; the launchers are now siblings inside
    `yascheduler.entrypoints.cli` and are covered by the existing
    `yascheduler.entrypoints.cli` clause).
  - "Entrypoints layer facade" requirement: revise the prose that references
    `entrypoints/daemon/daemon_systemd.py` and
    `entrypoints/daemon/daemon_sysv.py` to the new paths
    `entrypoints/cli/daemon_systemd.py` and `entrypoints/cli/daemon_sysv.py`.
    The "Daemon launchers are not re-exported by the entrypoints facade"
    scenario is updated to reference the new paths and the new location
    (`entrypoints/cli/`). The "Daemon launchers are layer-checked after
    migration" scenario is updated to reference the new module paths
    (`yascheduler.entrypoints.cli.daemon_systemd` and
    `yascheduler.entrypoints.cli.daemon_sysv`).
  - No layer-direction or facade-content requirement changes. The "Outside-
    layer-set exemptions" requirement is unchanged (the daemon launchers were
    never in the outside-set; they remain under `yascheduler.entrypoints`).
- **BREAKING** (re-install): the `yainit` installer now writes a service unit
  file / init.d script that points at the new launcher path
  (`entrypoints/cli/daemon_*.py`). Operators running `yainit` against an
  already-installed service must re-run `yainit` after upgrading so the unit
  file / init.d script picks up the new path. The old `entrypoints/daemon/`
  directory is removed; a service still pointing at the old path will fail to
  start (`ExecStart` references a non-existent file). This is a one-time
  re-install step, documented in the change. No code-level **BREAKING** change:
  no public import path changes (the launchers are invoked by filesystem path,
  not imported), no CLI command name changes, no config format change, no DB
  schema change.
- Tests:
  - Update `tests/unit/test_cli_init.py::TestServiceInstall` assertions at
    L241 and L257: `"daemon_systemd.py" in content` and
    `"daemon_sysv.py" in content` stay unchanged (the basename is preserved
    by the move). No test currently asserts the full
    `entrypoints/daemon/daemon_systemd.py` path inside the rendered service
    file (verified: only the basename is asserted), so no test needs to be
    rewritten to reference `entrypoints/cli/daemon_systemd.py`. If any test
    inspects the full path, it is updated to the new path.

### Out of scope (explicit, deferred to follow-up changes)

- The remaining `infra/cli/` residents (`check_status`, `daemonize`) and the
  `di.py` composition root remain at the package root / `infra/cli/`; their
  migration into `entrypoints/cli/` is tracked by
  `relocate-check-status-command` and a future `relocate-daemonize-command`.
- No `daemonize` reimplementation, no `daemonize` exit-code contract, no
  `daemonize` `argv` parameter — those belong to the future
  `relocate-daemonize-command` (mirroring the four CLI-command predecessors).
- No service-template (`yascheduler/data/yascheduler.service`,
  `yascheduler/data/yascheduler.sh`) content changes — the templates still
  carry `%YASCHEDULER_DAEMON_FILE%` and the install-time substitution is the
  only path-producing step.
- No `application/`, `domain/`, `infra/persistence/`, `infra/ssh/gateway.py`
  changes.
- No DB schema migration.
- No new dependencies.

## Capabilities

### New Capabilities

_None._ The relocation is a structural concern for existing launcher entry
points. No new spec capability is introduced: the daemon launchers already
exist and their invocation contract (path-based, via `%YASCHEDULER_DAEMON_FILE%`)
is unchanged. Their requirements are modified (below) rather than replaced.

### Modified Capabilities

- `package-facades`: the R1 "Within-package relative imports" requirement
  drops `yascheduler.entrypoints.daemon` from the enumeration of subpackages
  subject to R1 (the subpackage is removed). The "Entrypoints layer facade"
  requirement's daemon-launcher prose is updated to the new paths
  (`entrypoints/cli/daemon_*.py`). The "Daemon launchers are not re-exported
  by the entrypoints facade" and "Daemon launchers are layer-checked after
  migration" scenarios are updated to reference the new module paths
  (`yascheduler.entrypoints.cli.daemon_systemd`,
  `yascheduler.entrypoints.cli.daemon_sysv`). No layer-direction or
  facade-content requirement changes.

## Impact

- **Code**: `yascheduler/entrypoints/cli/daemon_systemd.py` and
  `yascheduler/entrypoints/cli/daemon_sysv.py` (2 new files, moved verbatim
  with `# FILE:` header / `VERSION` / `START_CHANGE_SUMMARY` updates);
  `yascheduler/entrypoints/daemon/daemon_systemd.py`,
  `yascheduler/entrypoints/daemon/daemon_sysv.py`, and
  `yascheduler/entrypoints/daemon/__init__.py` removed; the
  `yascheduler/entrypoints/daemon/` directory removed;
  `yascheduler/entrypoints/cli/__init__.py` gets a declarative PURPOSE/SCOPE
  + CHANGE_SUMMARY edit; `yascheduler/entrypoints/__init__.py` gets a
  declarative CHANGE_SUMMARY edit; `yascheduler/entrypoints/cli/init.py`
  gets the two `daemon_file = install_path / "…"` path rewrites + a
  CHANGE_SUMMARY entry.
- **CLI**: no command-name change; `yainit --daemon` (and the default) now
  produce service files pointing at `entrypoints/cli/daemon_systemd.py` /
  `entrypoints/cli/daemon_sysv.py`. **BREAKING** (re-install): operators must
  re-run `yainit` after upgrade so the installed service file reflects the
  new launcher path; a stale service pointing at the old
  `entrypoints/daemon/` path will fail to start. No code-level breaking
  change to any documented public interface.
- **Config**: `pyproject.toml` unchanged (no console_script entry for the
  daemon launchers — they are invoked by filesystem path from service
  templates, not registered as console_scripts). `[tool.importlinter]`
  unchanged (the `layers` contract already covers
  `yascheduler.entrypoints` as layer 1; the launchers remain inside that
  layer and remain R3-compliant).
- **Tests**: `tests/unit/test_cli_init.py` assertions at L241/L257 stay
  valid (basename-only). No test currently asserts the full
  `entrypoints/daemon/` path inside the rendered service file (verified); if
  any path-specific assertion is found during implementation, it is updated
  to `entrypoints/cli/daemon_*.py`.
- **Specs**: `openspec/specs/package-facades/spec.md` modified (R1
  enumeration + daemon-launcher prose/scenario paths).
- **Knowledge graph**: `docs/knowledge-graph.xml` — `M-DAEMON-SYSTEMD` and
  `M-DAEMON-SYSV` `<path>` values updated; `M-ENTRYPOINTS-DAEMON` element
  deleted (no inbound edges).
- **Docs**: no references to update in `docs/ARCHITECTURE.md` (verified: no
  `daemon_systemd`/`daemon_sysv`/`entrypoints/daemon` hits in `docs/`
  outside `knowledge-graph.xml`).
- **Dependencies**: none added or removed.