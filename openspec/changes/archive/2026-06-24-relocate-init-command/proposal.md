## Why

`yainit` lives in `yascheduler/infra/cli/init.py` but is a bootstrap/install
entrypoint (service install + schema apply), not an execution command. It was
explicitly tracked as deferred-for-migration into the `entrypoints/` layer by
the archived `add-entrypoints-layer` change. Its `init()` also couples two
operations with disjoint permissions, owners, and lifecycles (systemd/sysv
service install vs DB schema application), forcing operators to run both even
when only one is needed — e.g. re-applying the base schema after a migration
should not rewrite the service unit.

## What Changes

- Move `yascheduler/infra/cli/init.py` →
  `yascheduler/entrypoints/cli/init.py` (real implementation, not a shim).
  This is the next resident of `entrypoints/cli/`, mirroring
  `entrypoints/daemon/` from `relocate-daemon-launchers`. `init` is the only
  bootstrap command; the other 5 CLI commands (execution commands) stay in
  `infra/cli/`.
- Add `yascheduler/entrypoints/cli/__init__.py` as the subpackage facade
  (mirrors `entrypoints/daemon/__init__.py`).
- Delete `yascheduler/infra/cli/init.py`. Drop `from .init import init` and
  `"init"` from `__all__` in `yascheduler/infra/cli/__init__.py`. No compat
  shim: any `infra → entrypoints` re-export would invert the layer direction
  (`entrypoints → infra`) enforced by `import-linter`. The daemon-launchers
  precedent established entrypoint residents are not re-exported from `infra/`.
- Update `pyproject.toml` `[project.scripts]`:
  `yainit = "yascheduler.entrypoints.cli.init:init"`.
- Reimplement `init()` with `argparse`:
  - `--schema` (`store_true`): run only schema application.
  - `--daemon` (`store_true`): run only service install.
  - No flags = both (default behavior preserved). Both flags = both
    (= default). Subset selectors, not mutually exclusive — no
    `mutually_exclusive_group`.
  - `--help` shows the standard argparse help screen (argparse default).
- Exit code contract:
  - `0` on success (including idempotent re-runs where `apply_schema`
    succeeds on an already-initialized DB).
  - `1` on runtime failure: service file write failure, missing parent
    directory (`/etc/systemd/system/` or `/etc/init.d/`), `DatabaseError`
    from `apply_schema`, any other unexpected exception.
  - `2` on argparse error (argparse default — unknown flag, bad value).
- Service install: **overwrite if exists** (today: silent skip when the file
  already exists; new behavior: overwrite so re-running `yainit --daemon`
  picks up template updates). Write failures and missing parent dirs are
  caught (`OSError`) → message + `sys.exit(1)` (today: silent fail with
  exit 0 via `os.access` precheck that returns False for non-existent
  parent dirs).
- systemd detection: `Path("/run/systemd/system").is_dir()` (replaces
  `not os.system("pidof systemd")`, which depends on `pidof` and exit-code
  conventions).
- Rename the internal helper `_init_db` → `_init_schema` to align with the
  `--schema` flag name and the actual action (apply schema, not "init DB").
  `apply_schema(config.db)` is still called as today; the adapter stays
  untouched (the "already exists" branch in `postgres_schema.py` is dead code
  because `schema.sql` is fully idempotent via `IF NOT EXISTS`; `DatabaseError`
  only fires on real failures — connection, auth, type mismatch).
- Drop the `# FIXME: split adapter and application layer` comment from the
  new file: the new implementation does operational orchestration, not
  application-layer business logic; the FIXME does not apply.
- Do not carry GRACE-lite markup verbatim: the new file gets fresh
  `MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`, function contracts, and
  block anchors appropriate to the reimplemented logic.
- Update `openspec/specs/package-facades/spec.md`: drop `init` from the R1
  example that lists `infra/cli/__init__.py` submodules (`check_status`,
  `daemonize`, `init`, `manage_node`, `show_nodes`, `submit`).
- Update `openspec/specs/cli-commands/spec.md`:
  - R1 ("CLI commands call use cases via DI"): soften the "init is an
    exception" wording — `init` is a bootstrap entrypoint, not a DI command.
  - R2 ("yainit uses apply_schema adapter"): update the module path
    `infra/cli/init.py` → `entrypoints/cli/init.py`; add scenarios for
    `--schema`, `--daemon`, both, none, `--help`, exit codes, and service
    overwrite.
- Update `docs/knowledge-graph.xml`:
  - `M-CLI-COMMANDS`: drop the `<fn-init>` annotation and the
    `CrossLink from="M-CLI-COMMANDS" to="M-PERSISTENCE-SCHEMA"` (init no
    longer lives in `M-CLI-COMMANDS`).
  - Add a new module node `M-ENTRYPOINTS-CLI-INIT`
    (`path: yascheduler/entrypoints/cli/init.py`,
    `depends: M-PERSISTENCE-SCHEMA, M-CONFIG, M-SHARED`).
  - Add `CrossLink from="M-ENTRYPOINTS-CLI-INIT" to="M-PERSISTENCE-SCHEMA"
    relation="calls apply_schema for DB schema initialization"`.
- Tests:
  - Delete `tests/unit/test_cli_smoke.py::test_init_function_exists` (low-
    value smoke test that only checks the function exists and is sync).
  - Add `tests/unit/test_cli_init.py` with real unit tests: flag parsing
    (`--schema`, `--daemon`, both, none), dispatch (mock `apply_schema` and
    filesystem), exit codes (`0`/`1`/`2`), `--help` screen, systemd-vs-sysv
    auto-detect, service overwrite behavior, missing parent dir → exit 1.

### Out of scope (explicit, deferred to follow-up changes)

- The other 5 CLI commands (`submit`, `check_status`, `show_nodes`,
  `manage_node`, `daemonize`) remain in `yascheduler/infra/cli/`; their
  migration into `entrypoints/cli/` is tracked separately (if ever — they
  are execution commands, not bootstrap, so the semantic case is weaker).
- `apply_schema` and `postgres_schema.py` — unchanged. The dead
  "already exists" branch stays (touching it is a separate refactor).
- `schema-migrations` change — unaffected; `yainit --schema` applies the
  base `schema.sql` via `apply_schema` and does not run migrations. A
  future `--apply-migrations` flag (if added) is a separate concern and a
  separate change.
- `di.py`, `aiida_plugin.py` — unchanged.
- `[tool.importlinter]` configuration in `pyproject.toml` — unchanged
  (`layers` contract stays green; `entrypoints → infra` is the allowed
  direction; `ignore_imports` stays `[]`).
- `[tool.setuptools.package-data]` — unchanged (`schema.sql` stays in
  `infra/persistence/sql/`; service templates stay in `yascheduler/data/`).

## Capabilities

### New Capabilities

_None._ The relocation and flag split are structural/operational concerns.
No new spec capability is introduced: the `yainit` command already exists
under `cli-commands`, and its requirements are modified (below) rather than
replaced.

### Modified Capabilities

- `cli-commands`: the `yainit` command gains `--schema` / `--daemon`
  subset-selector flags, a documented exit-code contract, service-overwrite
  behavior, and a new module path (`entrypoints/cli/init.py`). R1's
  "init is an exception" wording is softened; R2's module path is updated;
  new scenarios cover the flag matrix, exit codes, `--help`, and service
  overwrite.
- `package-facades`: the R1 example listing `infra/cli/__init__.py`
  submodules drops `init` (it has moved to `entrypoints/cli/`). No layer-
  direction or facade-content requirement changes — `entrypoints/cli/` is
  a new resident of the existing `entrypoints` layer, not a new layer.

## Impact

- **Code**: `yascheduler/entrypoints/cli/` (2 new files); `yascheduler/infra/cli/init.py` removed;
  `yascheduler/infra/cli/__init__.py` loses the `init` re-export.
- **CLI**: `yainit` behavior: default unchanged (service + schema); new
  `--schema` / `--daemon` subset flags; `--help` works; service files are
  overwritten if present (was: silent skip); missing parent dir and write
  failures exit `1` (was: silent fail with exit `0`); `DatabaseError` exits
  `1` (was: traceback, already non-zero). No **BREAKING** change to the
  command name or the default invocation.
- **Config**: `pyproject.toml` line 49 (console_script target) updated.
  `[tool.importlinter]` unchanged.
- **Tests**: `tests/unit/test_cli_smoke.py` loses one test method;
  `tests/unit/test_cli_init.py` added with focused unit tests for the new
  dispatch logic. `tests/integration/conftest.py` unchanged (it calls
  `apply_schema` directly, not via `init`).
- **Specs**: `openspec/specs/cli-commands/spec.md` and
  `openspec/specs/package-facades/spec.md` modified.
- **Knowledge graph**: `docs/knowledge-graph.xml` — `M-CLI-COMMANDS` loses
  `<fn-init>` and a `CrossLink`; new `M-ENTRYPOINTS-CLI-INIT` node +
  `CrossLink` added.
- **Docs**: `README.md:39` and `docs/ARCHITECTURE.md:250,386,473` reference
  the `yainit` command name only — unchanged.
- **Dependencies**: none added or removed.