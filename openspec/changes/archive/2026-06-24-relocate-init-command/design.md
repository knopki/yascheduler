## Context

`yainit` is the bootstrap CLI command that installs the systemd/sysv service
unit and applies the base DB schema. It lives at
`yascheduler/infra/cli/init.py` and is registered as the `yainit`
`console_script` in `pyproject.toml`. The archived `add-entrypoints-layer`
change created `yascheduler/entrypoints/` as the outermost hexagonal layer
and explicitly listed `infra/cli/` as deferred-for-migration;
`relocate-daemon-launchers` then moved `daemon_systemd.py` /
`daemon_sysv.py` into `entrypoints/daemon/`. `init.py` is the next resident
in the same family — it is a setup/bootstrap entrypoint, not an execution
command like the other 5 CLI commands.

Current `init()`:

```python
def init() -> None:
    install_path = Path(__file__).parent.parent.parent  # yascheduler/
    has_systemd = not os.system("pidof systemd")
    if has_systemd:
        _init_systemd(install_path)
    else:
        _init_sysv(install_path)
    _init_db()

def _init_db() -> None:
    config = Config.from_config_parser(CONFIG_FILE)
    apply_schema(config.db)
```

`_init_systemd` / `_init_sysv` read templates from `yascheduler/data/`,
substitute `%YASCHEDULER_DAEMON_FILE%` with
`install_path/"entrypoints/daemon/daemon_*.py"`, and write to
`/etc/systemd/system/yascheduler.service` or `/etc/init.d/yascheduler`.
Both use `if not path.is_file(): ... os.access(...) ... return` — a
write-protected silent-skip that returns exit 0 on failure (including when
the parent directory does not exist, because `os.access` returns False for
non-existent paths).

`schema.sql` is fully idempotent (`CREATE TABLE IF NOT EXISTS`,
`ALTER TABLE ADD COLUMN IF NOT EXISTS`), so re-running `apply_schema` on an
already-initialized DB succeeds. The `if "already exists" in str(e.args[0])`
branch in `postgres_schema.py` is dead code under normal re-init;
`DatabaseError` only fires on real failures (connection, auth, type mismatch).

## Goals / Non-Goals

**Goals:**

- Move `init.py` from `infra/cli/` to `entrypoints/cli/` as the next
  `entrypoints/` resident, mirroring the `entrypoints/daemon/` precedent.
- Reimplement `init()` with `argparse` exposing `--schema` and `--daemon`
  subset-selector flags (default unchanged: both run).
- Define and enforce a clear exit-code contract (`0` / `1` / `2`).
- Replace write-protected silent-skip with overwrite-if-exists and
  `OSError` → exit 1 (fixes the silent-fail-on-missing-parent bug).
- Replace `pidof systemd` detection with
  `Path("/run/systemd/system").is_dir()`.
- Preserve every public contract: `yainit` command name, default invocation
  behavior, console_script wiring, layer-direction compliance.

**Non-Goals:**

- Move the other 5 CLI commands (`submit`, `check_status`, `show_nodes`,
  `manage_node`, `daemonize`) — they are execution commands, not bootstrap.
- Touch `apply_schema` / `postgres_schema.py` (the dead "already exists"
  branch stays; touching it is a separate refactor).
- Add a `--apply-migrations` flag (that belongs to the `schema-migrations`
  change; `--schema` here applies the base `schema.sql` only).
- Add a `--force` / `--systemd` / `--sysv` service-type selector —
  auto-detect is the contract.
- Modify `[tool.importlinter]` or `[tool.setuptools.package-data]` in
  `pyproject.toml` — neither is affected.

## Decisions

### D1 — Real implementation at the new path, no compat shim

**Choice:** Move the real implementation to
`yascheduler/entrypoints/cli/init.py`; delete `yascheduler/infra/cli/init.py`;
drop `from .init import init` and `"init"` from `__all__` in
`yascheduler/infra/cli/__init__.py`; update `pyproject.toml` line 49 to
`yainit = "yascheduler.entrypoints.cli.init:init"`.

**Rationale:** A compat shim at `infra/cli/init.py` re-exporting from
`entrypoints/cli/init.py` would create an `infra → entrypoints` import,
inverting the layer direction (`entrypoints → infra → application → domain →
shared`) enforced by `import-linter`'s `layers` contract. The
`relocate-daemon-launchers` precedent established that entrypoint residents
are invoked by path / console_script, not re-exported from `infra/`. No deep
import of `from yascheduler.infra.cli.init import init` exists in the
codebase (verified by grep); the only consumer of `from yascheduler.infra.cli
import init` is `tests/unit/test_cli_smoke.py:77`, which is updated in this
change.

**Alternative rejected:** Keep a one-line shim at `infra/cli/init.py` for
"import path compat." Rejected because the layer violation is real and the
import-linter contract would need an `ignore_imports` entry to suppress it —
adding technical debt to preserve a path that no production code uses.

### D2 — `--schema` and `--daemon` are subset selectors, not mutually exclusive

**Choice:** Two `store_true` flags. No flags = both run (default preserved).
Either flag = run only that subset. Both flags = both run (= default). No
`mutually_exclusive_group`.

**Rationale:** "Run subsets of the bootstrap" is naturally a partial-enable
model, not an either/or model. Both-present-equals-default means a caller
who sets both flags defensively gets the default behavior, not an error.
This matches the "do the right thing" principle and avoids an error case
that adds no value.

**Alternative rejected:** `mutually_exclusive_group(required=False)` so
`--schema --daemon` raises an argparse error (exit 2). Rejected: both
flags is not a *mistake*, it is the default — erroring on it would be
hostile to scripting.

### D3 — Exit codes `0` / `1` / `2`

**Choice:**
- `0` on success (including idempotent re-runs where `apply_schema`
  succeeds on an already-initialized DB).
- `1` on runtime failure: service file write failure, missing parent
  directory (`OSError`), `DatabaseError` from `apply_schema`, any other
  unexpected exception caught at the top level.
- `2` on argparse error (argparse default — unknown flag, bad value).

**Rationale:** `2` is the argparse default and what shell scripts expect
for usage errors; reusing it avoids fighting the framework. `1` for
runtime failures is the POSIX convention. The current code's silent-skip
/ silent-fail paths (exit 0 on write failure) are a latent bug — this
contract makes failures visible.

**Alternative rejected:** Use `sysexits.h` codes (`EX_UNAVAILABLE=70`,
`EX_TEMPFAIL=75`, etc.). Rejected: over-engineering for a bootstrap
command; `0/1/2` is the convention every other yascheduler CLI command
will follow, and this change sets the precedent.

### D4 — Service install: overwrite if exists; `OSError` → exit 1

**Choice:**
- If the service file (`/etc/systemd/system/yascheduler.service` or
  `/etc/init.d/yascheduler`) already exists, **overwrite it** (today:
  silent skip). This makes `yainit --daemon` idempotent and picks up
  template updates.
- Write via `path.write_text(...)` inside a `try/except OSError` block.
  On `OSError` (including missing parent directory, permission denied,
  disk full): print `f"Error: cannot write to {path}: {e}"` and
  `sys.exit(1)`.
- sysv: `os.chmod(startup_file, 0o755)` runs after a successful write
  (unchanged from today; chmod applies whether the file was newly written
  or overwritten).

**Rationale:** The current `os.access(path, os.W_OK)` precheck returns
`False` when the *parent directory* does not exist (e.g.
`/etc/systemd/system/` absent on a non-systemd box misdetected as systemd,
or on a stripped container), causing a silent exit-0 fail. Catching
`OSError` from the actual write distinguishes "wrote successfully" from
"could not write" and surfaces the real cause. Overwrite-if-exists makes
re-running `yainit --daemon` after a template update do the right thing
without forcing the operator to delete the old file first.

**Alternative rejected:** `path.parent.mkdir(parents=True, exist_ok=True)`
before writing. Rejected: `yainit` should not create `/etc/systemd/system/`
or `/etc/init.d/` — those are owned by the OS/systemd package and their
absence signals a misconfigured host. Failing loudly (exit 1) is correct.

### D5 — systemd detection via `Path("/run/systemd/system").is_dir()`

**Choice:** Replace `has_systemd = not os.system("pidof systemd")` with
`has_systemd = Path("/run/systemd/system").is_dir()`.

**Rationale:** `pidof systemd` depends on `pidof` being on `PATH` (not
guaranteed on minimal images) and on exit-code conventions. The
`/run/systemd/system/` directory is the documented, stable marker that
systemd is the active init on a host (it is created by systemd at boot).
`Path(...).is_dir()` is a single stdlib call with no subprocess.

**Alternative rejected:** `shutil.which("systemctl")`. Rejected:
`systemctl` can be installed on a non-systemd host (e.g. as a dead binary
in a container) — presence of the binary does not prove systemd is PID 1.
`/run/systemd/system/` is the stronger signal.

### D6 — `_init_db` → `_init_schema`; adapter untouched

**Choice:** Rename the internal helper `_init_db` to `_init_schema` to
align with the `--schema` flag name and the actual action (apply schema,
not "init DB"). The body is unchanged: `Config.from_config_parser(CONFIG_FILE)`
→ `apply_schema(config.db)`. `apply_schema` and `postgres_schema.py` are
not modified.

**Rationale:** The flag is `--schema`; the helper that runs when the flag
is set should be named to match. "DB" is broader than "schema" (DB init
could mean user creation, extension install, etc., none of which
`apply_schema` does). `apply_schema` is a shared adapter used by
`tests/integration/conftest.py:88` directly; changing its semantics would
break test setup. The dead "already exists" branch in
`postgres_schema.py:70-72` stays — removing it is a separate refactor.

### D7 — Drop the `# FIXME: split adapter and application layer` comment

**Choice:** Do not carry the FIXME to the new file.

**Rationale:** The FIXME was attached to a file that lived in `infra/cli/`
alongside `submit.py` (which carries the same FIXME). In `infra/cli/submit`,
there is arguably an application-layer concern to split (DI wiring vs.
argparse). In `init`, there is not — `init` does operational orchestration
(service install + schema apply delegation); the only "adapter" it touches
is `apply_schema`, which is already a clean infra adapter. Carrying the
FIXME to the new home would mark a resolved concern as still open.

### D8 — `install_path = Path(__file__).parent.parent.parent` is invariant

**Choice:** Keep the 3-level parent walk in the new file.

**Rationale:** `yascheduler/infra/cli/init.py` and
`yascheduler/entrypoints/cli/init.py` are both 3 directory levels below
`yascheduler/` (`<pkg>/cli/init.py`). `Path(__file__).parent.parent.parent`
resolves to `yascheduler/` in both cases. The daemon-file paths
(`install_path/"entrypoints/daemon/daemon_systemd.py"` and
`.../daemon_sysv.py`) and the service-template paths
(`install_path/"data/yascheduler.service"` and `.../"data/yascheduler.sh"`)
are unchanged by the move. No path computation needs adjustment.

### D9 — Fresh GRACE-lite markup at the new path

**Choice:** The new `entrypoints/cli/init.py` gets fresh `MODULE_CONTRACT`,
`MODULE_MAP`, `CHANGE_SUMMARY`, function contracts (for `init`,
`_init_systemd`, `_init_sysv`, `_init_schema`), and block anchors
(`VALIDATE_FLAGS`, `DETECT_INIT_SYSTEM`, `INSTALL_SERVICE`, `APPLY_SCHEMA`,
`HANDLE_FAILURE`) appropriate to the reimplemented logic. The
`entrypoints/cli/__init__.py` facade gets a `MODULE_CONTRACT` mirroring
`entrypoints/daemon/__init__.py`.

**Rationale:** GRACE-lite requires governed files to carry markup; the
reimplementation has different control flow (argparse dispatch, subset
selection, try/except) than the original, so the markup is written for
the new shape, not copied.

## Risks / Trade-offs

- **[Risk] Operators with scripts that run `yainit` repeatedly and rely on
  exit 0 after the first run.** → Mitigation: default invocation behavior is
  unchanged for the schema half (`schema.sql` is idempotent, `apply_schema`
  succeeds on re-run → exit 0). The service half changes from silent-skip
  (exit 0) to overwrite (exit 0 on success). The only behavior change that
  could affect an operator is the missing-parent-dir case (was exit 0
  silent fail, now exit 1 with a message) — but that case was already a
  *broken* install, so surfacing it is a fix, not a regression.
- **[Risk] `--schema` / `--daemon` semantics misread as mutex.** →
  Mitigation: `--help` documents both flags; both-present = default is
  the least surprising behavior for a "run subsets" model. Spec scenarios
  cover all four combinations.
- **[Risk] Overwriting a service unit that an operator hand-edited.** →
  Mitigation: the unit file is generated from a template with a single
  `%YASCHEDULER_DAEMON_FILE%` substitution; hand-editing is discouraged
  and the overwrite ensures the file matches the installed package
  version. Operators who need custom edits should override via systemd
  drop-ins (`/etc/systemd/system/yascheduler.service.d/*.conf`), which
  `yainit` does not touch.
- **[Risk] `DatabaseError` exit code change for operators who grep'd
  stderr for "Database already initialized!" and treated it as success.**
  → Mitigation: that branch is dead code under normal re-init (schema.sql
  is idempotent); the message only appears on a real failure, which
  should not be treated as success. The new exit-1 contract is correct.
- **[Trade-off] Temporary asymmetry: 1 of 6 CLI commands in `entrypoints/`,
  5 in `infra/cli/`.** → Accepted: `init` is the only bootstrap command,
  and the semantic split (setup vs execution) is clean. The other 5 may
  follow in a separate change if the team decides execution commands
  belong in `entrypoints/` too; this change does not prejudge that.

## Migration Plan

**Deploy:**
1. Install the new package version (contains
   `yascheduler/entrypoints/cli/init.py`; no longer contains
   `yascheduler/infra/cli/init.py`).
2. `yainit` console_script now resolves to
   `yascheduler.entrypoints.cli.init:init` (via updated `pyproject.toml`).
   Re-install the package (or `pip install -e .` / `uv sync`) to refresh
   the entrypoint.
3. No DB migration, no config change, no service file migration needed.
   Re-running `yainit` (default) on an already-initialized host
   overwrites the service unit (picks up any template update) and
   re-applies `schema.sql` (idempotent → exit 0).

**Rollback:**
1. Revert to the previous package version (restores
   `yascheduler/infra/cli/init.py`, restores `pyproject.toml` line 49).
2. Re-install the package to refresh the entrypoint.
3. The overwritten service unit, if any, is functionally identical to
   the previous one (the template and daemon-file path are unchanged by
   this change); no service file cleanup needed.

**Open Questions:** None. All decisions captured in D1–D9.