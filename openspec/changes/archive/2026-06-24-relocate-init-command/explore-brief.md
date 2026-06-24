# Explore Brief — relocate-init-command

## Problem

`yascheduler/infra/cli/init.py` (82 lines) is the `yainit` CLI command. It is
explicitly tracked as deferred-for-migration in the archived
`add-entrypoints-layer` change, which created `yascheduler/entrypoints/` as the
outermost hexagonal layer and listed `infra/cli/` as a follow-up. The
`relocate-daemon-launchers` change then moved `daemon_systemd.py` /
`daemon_sysv.py` into `entrypoints/daemon/`. `init.py` is the next resident
in the same family: it is a bootstrap/install entrypoint (service install +
schema apply), not an execution command like the other 5 CLI commands.

The current `init()` couples two operations with disjoint permissions, lifecycles,
owners, and failure modes: systemd/sysv service install (root, filesystem,
one-shot at install time, sysadmin-owned) and DB schema application (DB user,
repeatable on schema upgrades, DBA-owned). The file carries a
`# FIXME: split adapter and application layer` comment, but there is no
application-layer business logic to split — the coupling is operational
orchestration, not a hexagonal-boundary issue.

`schema-migrations` (in progress) is adding a versioned migration system
alongside `apply_schema`. `yainit` users will want to run "apply base schema"
as a distinct step; today that requires the whole `yainit` (which also writes
service files).

## Rejected alternatives

- **Move all 6 CLI commands to entrypoints/cli/.** Rejected for scope: the
  other 5 (`submit`, `check_status`, `show_nodes`, `manage_node`, `daemonize`)
  are execution commands, not bootstrap. They stay in `infra/cli/` for a
  follow-up if ever. `init` is the only bootstrap command — moving it alone
  creates temporary asymmetry but a clean semantic split (setup vs execution).
- **Keep a compat shim at `infra/cli/init.py`.** Rejected: any re-export from
  `infra/cli/__init__.py` to `entrypoints/cli/init.py` would create an
  `infra → entrypoints` import, violating the layer direction
  (`entrypoints → infra → application → domain → shared`) enforced by
  import-linter. The daemon-launchers precedent established that entrypoint
  residents are *not* re-exported from `infra/`; they are invoked by path.
  `yainit` follows the same pattern: the console_script target moves to the
  new module, no shim.
- **Make `--schema`/`--daemon` mutually exclusive.** Rejected in favor of
  subset selectors: no flags = both (default unchanged); either flag = run
  only that subset; both flags = both (= default). No error case, no
  argparse mutex group needed.
- **Force a service-type choice in `--daemon` (`--daemon systemd|sysv`).**
  Rejected: over-engineering. Auto-detect via `Path("/run/systemd/system")`
  is robust and matches "do the right thing."
- **Make `apply_schema` itself idempotent-friendly (swallow "already exists").**
  Rejected: `schema.sql` is already fully idempotent (`CREATE TABLE IF NOT
  EXISTS`, `ALTER TABLE ADD COLUMN IF NOT EXISTS`), so the "already exists"
  branch in `postgres_schema.py:70-72` is dead code under normal re-init.
  `DatabaseError` only fires on real failures (connection, auth, wrong type).
  Idempotency is already a property of the adapter; no special handling in
  `init()`. Touching `apply_schema` is out of scope.
- **Carry the `# FIXME: split adapter and application layer` comment to the
  new file.** Rejected: the FIXME does not apply to the new location. The new
  implementation does operational orchestration (service install + schema
  apply delegation); there is no application-layer business logic to split.

## Final approach — labels / dimensions / mapping tables

### Flag matrix

| invocation                    | --schema | --daemon | action                                  | exit |
| ----------------------------- | -------- | -------- | --------------------------------------- | ---- |
| `yainit`                      | absent   | absent   | install service + apply schema         | 0/1  |
| `yainit --schema`             | present  | absent   | apply schema only                       | 0/1  |
| `yainit --daemon`             | absent   | present  | install service only                    | 0/1  |
| `yainit --schema --daemon`     | present  | present  | install service + apply schema (= default) | 0/1  |
| `yainit --help`               | n/a      | n/a      | argparse help screen, exit 0            | 0    |
| `yainit --bogus`              | n/a      | n/a      | argparse error                          | 2    |

`store_true` flags; no `mutually_exclusive_group`. Both-present equals
neither-present semantically (both run).

### Exit code contract

| code | meaning                              | source                          |
| ---- | ------------------------------------ | ------------------------------- |
| 0    | success (incl. idempotent re-runs)  | normal completion              |
| 1    | runtime failure                      | service write fail, missing parent dir, DB error, any unexpected exception |
| 2    | argparse error                       | argparse default (unknown flag, bad value) |

### Service install behavior (per init-style)

| condition                              | old behavior                      | new behavior                              |
| -------------------------------------- | --------------------------------- | ----------------------------------------- |
| systemd detected, unit file missing    | write file                        | write file (unchanged)                    |
| systemd detected, unit file exists      | silent skip (return, exit 0)      | **overwrite** file                         |
| systemd detected, `/etc/systemd/system/` missing | `os.access` returns False → silent fail (exit 0) | **try write, catch OSError → message + exit 1** |
| sysv detected, init.d script missing  | write file + chmod 0755           | write file + chmod 0755 (unchanged)        |
| sysv detected, init.d script exists     | silent skip (exit 0)              | **overwrite** + chmod 0755                 |
| sysv detected, `/etc/init.d/` missing  | silent fail (exit 0)              | **try write, catch OSError → message + exit 1** |

Detection: `Path("/run/systemd/system").is_dir()` (replaces
`not os.system("pidof systemd")`).

### Schema apply behavior

`init()` → `_init_schema()` → `Config.from_config_parser(CONFIG_FILE)` →
`apply_schema(config.db)`. `DatabaseError` from `apply_schema` propagates as
exit 1 (caught at top level, printed, `sys.exit(1)`). No "already exists"
special-case in `init()` — `schema.sql` is idempotent via `IF NOT EXISTS`.

## Cross-module data flows

### Call path (after change)

```
yainit (console_script)
  → yascheduler.entrypoints.cli.init.init()
      → argparse: parse --schema / --daemon
      → if daemon requested:
          → if Path("/run/systemd/system").is_dir():
              → _init_systemd(install_path)
                  → read yascheduler/data/yascheduler.service
                  → substitute %YASCHEDULER_DAEMON_FILE% with
                    install_path/"entrypoints/daemon/daemon_systemd.py"
                  → write /etc/systemd/system/yascheduler.service (overwrite)
                  → OSError → message + sys.exit(1)
          → else:
              → _init_sysv(install_path)
                  → read yascheduler/data/yascheduler.sh
                  → substitute %YASCHEDULER_DAEMON_FILE% with
                    install_path/"entrypoints/daemon/daemon_sysv.py"
                  → write /etc/init.d/yascheduler (overwrite) + chmod 0755
                  → OSError → message + sys.exit(1)
      → if schema requested:
          → _init_schema()
              → Config.from_config_parser(CONFIG_FILE)
              → apply_schema(config.db)   # from yascheduler.infra.persistence
              → DatabaseError → message + sys.exit(1)
      → sys.exit(0)
```

`install_path = Path(__file__).parent.parent.parent` — same 3-level walk as
today; `entrypoints/cli/init.py` is 3 levels below `yascheduler/`, identical
to `infra/cli/init.py`. Path computation unchanged.

### Layer direction (verified)

```
yascheduler.entrypoints.cli.init
  → yascheduler.infra.persistence.apply_schema   (entrypoints → infra ✓)
  → yascheduler.config.Config                     (entrypoints → config, outside-layer-set ✓)
  → yascheduler.shared.CONFIG_FILE                (entrypoints → shared ✓)
```

`import-linter` `layers` contract stays green:
`["yascheduler.entrypoints", "yascheduler.infra", "yascheduler.application",
"yascheduler.domain", "yascheduler.shared"]`. `ignore_imports` stays `[]`.
No new `ignore_imports` entries needed.

### Files added / removed / modified

| action   | path                                              | note                                                       |
| -------- | ------------------------------------------------- | ---------------------------------------------------------- |
| add      | `yascheduler/entrypoints/cli/__init__.py`         | subpackage facade (mirrors `entrypoints/daemon/__init__.py`) |
| add      | `yascheduler/entrypoints/cli/init.py`             | real implementation                                        |
| remove   | `yascheduler/infra/cli/init.py`                   | moved, not shimmed                                         |
| modify   | `yascheduler/infra/cli/__init__.py`              | drop `from .init import init` + `"init"` from `__all__`    |
| modify   | `pyproject.toml` line 49                          | `yainit = "yascheduler.entrypoints.cli.init:init"`         |
| modify   | `openspec/specs/package-facades/spec.md` R1 example | drop `init` from infra/cli submodule list (line ~103)     |
| modify   | `openspec/specs/cli-commands/spec.md`            | soften "exception" wording; add flag scenarios; update path |
| modify   | `docs/knowledge-graph.xml`                        | drop `M-CLI-COMMANDS` `<fn-init>` + CrossLink; add `M-ENTRYPOINTS-CLI-INIT` node + CrossLink |
| modify   | `tests/unit/test_cli_smoke.py`                   | delete `test_init_function_exists`                         |
| add      | `tests/unit/test_cli_init.py`                    | real unit tests (new file)                                 |

## Open questions

None. All decisions captured above. Ready to write proposal.