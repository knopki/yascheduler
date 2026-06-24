## Context

`yasubmit` is the CLI command that parses an AiiDA script file, reads engine
input files, and submits a task via `CLIDeps.submit`. It lives at
`yascheduler/infra/cli/submit.py` (105 lines) and is registered as the
`yasubmit` `console_script` in `pyproject.toml` line 54. The archived
`add-entrypoints-layer` change created `yascheduler/entrypoints/` as the
outermost hexagonal layer and listed `infra/cli/` as deferred-for-migration;
the archived `relocate-init-command` change then moved `init.py` into
`yascheduler/entrypoints/cli/init.py` as the first resident, establishing
the `entrypoints/cli/` home and the relocation pattern (real move, no compat
shim, layer direction `entrypoints → infra` preserved, fresh GRACE-lite
markup, argparse-based reimplemented logic, `0`/`1`/`2` exit-code contract).
The in-progress `relocate-show-nodes-command` is the second resident
(execution-query precedent). `submit` is the third resident — the
execution-write counterpart — and follows after `relocate-show-nodes-
command` archives.

Current `submit()`:

```python
@to_sync
async def submit() -> None:
    parser = argparse.ArgumentParser(
        description="Submit task to yascheduler via AiiDA script"
    )
    parser.add_argument("script")
    args = parser.parse_args()
    script_file = Path(args.script)
    if not script_file.exists():
        raise ValueError("Script parameter is not a file name")
    logging.captureWarnings(True)
    log = logging.getLogger()
    log.setLevel(logging.WARN)
    config = Config.from_config_parser(CONFIG_FILE)
    deps = make_cli_deps(config)
    script_params = _parse_script_metadata(script_file.read_text())
    label = script_params.get("LABEL", "AiiDA job")
    metadata: dict[str, Any] = {"local_folder": os.getcwd()}
    engine_name = script_params.get("ENGINE")
    if not engine_name:
        raise ValueError("Script has not defined an engine")
    engine = config.engines.get(engine_name)
    if not engine:
        raise ValueError(f"Engine {engine_name} is not supported")
    metadata.update(_read_input_files(engine, metadata["local_folder"]))
    if "PARENT" in script_params and config.local.webhook_url:
        metadata["webhook_url"] = config.local.webhook_url
        metadata["webhook_custom_params"] = {"parent": script_params["PARENT"]}
    task_id = await deps.submit(label, dict(metadata), engine.name)
    print(str(task_id))
```

The script-parsing helpers `_parse_script_metadata` and `_read_input_files`
(lines 34-56) are already pure functions and move as-is. The AiiDA scheduler
plugin (`entrypoints/aiida_plugin.py:_parse_submit_output`) parses
`int(stdout.strip())` and treats `ValueError` as "no task id received" —
the success output MUST remain exactly `str(task_id)`.

`schema-migrations` (in progress) is adding a versioned migration system; it
does not touch `yasubmit` or any write path beyond what `submit_task` already
does, so this change and that one do not conflict.

## Goals / Non-Goals

**Goals:**
- Move `submit.py` from `infra/cli/` to `entrypoints/cli/` as the third
  resident, mirroring the `relocate-init-command` and
  `relocate-show-nodes-command` precedents (real move, no compat shim,
  layer direction preserved).
- Reimplement `submit()` with `argparse` exposing `prog="yasubmit"`, the
  `argv: list[str] | None = None` testability parameter, and the
  `type=_existing_path` file-existence validator (argparse-layer → exit 2).
- Define and enforce the `0`/`1`/`2` exit-code contract (mirrors `init` and
  `show_nodes`).
- Split the logic into private pure functions
  (`_existing_path`, `_parse_submit_args`, `_parse_script_metadata`,
  `_read_input_files`, `_build_metadata`) with the webhook branch
  encapsulated in `_build_metadata`.
- Preserve the AiiDA stdout compatibility contract exactly: success prints
  `str(task_id)` (no prefix, suffix, JSON, or decoration); failure prints
  nothing to stdout and an error message to stderr.
- Preserve every public contract: `yasubmit` command name, success-path
  output, `console_script` wiring, layer-direction compliance, no new
  dependencies.

**Non-Goals:**
- Move the other 3 CLI commands (`check_status`, `manage_node`, `daemonize`)
  — they stay in `infra/cli/` for follow-up changes. This change follows the
  execution-command relocation pattern; it does not prejudge the others.
- Extract a `submit_script` or `query_submit` use case into
  `yascheduler/application/` — YAGNI; no second consumer of the script-
  parsing logic exists (the AiiDA client submits via
  `queue_submit_task_async` with direct label/metadata/engine args, not via
  script files; the daemon does not submit). Promotion to
  `application/submit_script.py` awaits a second consumer and is recorded
  in the `_build_metadata` contract.
- Add `--json`, `--table`, or any output-mode flag — `submit` is a write
  command; the AiiDA stdout contract forbids decorating the success output;
  the `--json` convention established by `relocate-show-nodes-command`
  applies to query-oriented commands only.
- Touch `di.py`, `application/`, `domain/`, `infra/persistence/`,
  `entrypoints/aiida_plugin.py` — unchanged.

## Decisions

### D1 — Real implementation at the new path, no compat shim

**Choice:** Move the real implementation to
`yascheduler/entrypoints/cli/submit.py`; delete
`yascheduler/infra/cli/submit.py`; drop `from .submit import submit` and
`"submit"` from `__all__` in `yascheduler/infra/cli/__init__.py`; drop the
`submit - Re-exported from .submit` line from its `MODULE_MAP`; update
`pyproject.toml` line 54 to
`yasubmit = "yascheduler.entrypoints.cli.submit:submit"`.

**Rationale:** A compat shim at `infra/cli/submit.py` re-exporting from
`entrypoints/cli/submit.py` would create an `infra → entrypoints` import,
inverting the layer direction (`entrypoints → infra → application → domain →
shared`) enforced by `import-linter`'s `layers` contract. The
`relocate-init-command` and `relocate-show-nodes-command` precedents
established that entrypoint residents are invoked by path / console_script,
not re-exported from `infra/`. No deep import of
`from yascheduler.infra.cli.submit import submit` exists in production
code (verified by grep); the only consumers are
`yascheduler/infra/cli/__init__.py` (re-export), `pyproject.toml`
(console_script target), and two test files — all updated in this change.

**Alternative rejected:** Keep a one-line shim at `infra/cli/submit.py`
re-exporting from the new location. Rejected: the layer violation is real
and the import-linter contract would need an `ignore_imports` entry to
suppress it — adding technical debt to preserve a path that no production
code uses.

### D2 — In-module function splitting; no use-case extraction

**Choice:** Split the logic into private pure functions inside
`entrypoints/cli/submit.py`: `_existing_path(s)` (argparse type validator),
`_parse_submit_args(argv)` (argparse → Namespace), `_parse_script_metadata`
(moved as-is), `_read_input_files` (moved as-is), `_build_metadata(params,
config, local_folder)` (encapsulates the webhook block). Do NOT extract a
`submit_script` use case into `yascheduler/application/`.

**Rationale:** The `query_tasks` use case was extracted (in the archived
`client-query-uow` change) because the AiiDA client
(`yascheduler.entrypoints.client.Yascheduler.queue_get_tasks_async`) was a
real second consumer of the same query. No second consumer of the "parse
AiiDA script → build metadata → submit" flow exists: the AiiDA client
submits via `queue_submit_task_async` with direct label/metadata/engine
args (not via script files); the daemon does not submit. The script-parsing
logic is CLI-specific input shaping, not a business rule. Extracting a use
case now would create a module with a single caller and no prospect of a
second — the textbook YAGNI violation. The in-module split still achieves
the FIXME's intent (logic-vs-IO separation) at the appropriate granularity
(functions, not layers). The `_build_metadata` contract records that
promotion to `application/submit_script.py` awaits a second consumer.

**Alternative rejected:** Create `yascheduler/application/submit_script.py`
mirroring `submit_task.py`. Rejected: no second consumer; the script-parsing
is CLI input shaping, not business logic; produces a one-caller use case.

### D3 — `type=_existing_path` for file existence (argparse layer, exit 2)

**Choice:** Define a local `_existing_path(s: str) -> Path` callable that
returns `Path(s)` if `s` is an existing file or raises
`argparse.ArgumentTypeError(f"not a file: {s}")`. Pass it as
`type=_existing_path` on the positional `script` argument. Missing-file
becomes an argparse error (exit 2), not a body runtime error (exit 1).

**Rationale:** Argparse-layer validation owns argument *shape* (the path
exists and is a file); body-layer validation owns *content* (the script's
ENGINE key is present; the engine name is known to config). Moving file
existence to argparse gives the missing-file case the standard usage-error
exit code (2) with a clean argparse message, instead of the current exit 1
with a Python traceback. This is the natural argparse split and matches
shell-script expectations (`2` = usage error, `1` = runtime failure). The
AiiDA scheduler plugin treats any `retval != 0` as a failed submission
(`int(stdout.strip())` fails on empty stdout → logs "Submitting failed, no
task id received"), so changing exit 1 → 2 for the missing-file case is
AiiDA-compatible (still `!= 0`).

**Behavior change:** missing-file currently raises `ValueError("Script
parameter is not a file name")` → uncaught exception → traceback on stderr,
exit 1. After this change, missing-file is an argparse `type` error → clean
argparse message on stderr, exit 2. This is a deliberate improvement
within the reimplementation scope, AiiDA-compatible.

**Alternative rejected (a):** Keep file-existence validation in the body
via `if not script_file.exists(): raise ValueError(...)`, exit 1. Rejected:
mixes shape and content validation; usage errors should be exit 2.
**Alternative rejected (b):** Use `type=argparse.FileType("r")`. Rejected:
`FileType` opens the file at parse time and returns a file object, not a
`Path`; the body needs a `Path` (it reads text via `script_file.read_text()`
and uses `Path` operations elsewhere). `_existing_path` returns a `Path`
and defers reading to the body, preserving the current read shape.

### D4 — Exit codes `0` / `1` / `2`

**Choice:**
- `0` on success: `print(str(task_id))`, normal completion (the function
  returns; the process exits 0).
- `1` on runtime failure: ENGINE key missing in script, engine name
  unknown to config, DB error, config parse error, any unexpected exception
  caught at the top level (`except Exception as e: print(f"Error: {e}",
  file=sys.stderr); sys.exit(1)`).
- `2` on argparse error: argparse default (missing script arg, file not
  found via `type=_existing_path`, extra positional, unknown flag).

**Rationale:** Mirrors the `relocate-init-command` D3 and
`relocate-show-nodes-command` D5 precedents exactly. `2` is the argparse
default that shell scripts expect for usage errors; reusing it avoids
fighting the framework. `1` for runtime failures is the POSIX convention.
The current code has no exit-code contract (it returns on success and
propagates exceptions as tracebacks with Python's default uncaught-
exception exit code 1); this contract makes failures visible, scriptable,
and AiiDA-compatible (still `!= 0` on failure).

**Note on `sys.exit(0)`:** `submit` does NOT call `sys.exit(0)` explicitly
on success — the function returns normally and the process exits 0. Only
the failure path calls `sys.exit(1)`. argparse's `--help`/error path calls
`sys.exit(0)`/`sys.exit(2)` internally before reaching the body. This
differs slightly from `init`, which calls `sys.exit(0)` explicitly because
`init`'s body has no other terminal point; `submit` returns from the body
normally after `print(str(task_id))`. (Same as `show_nodes`.)

**Alternative rejected:** Use `sysexits.h` codes. Rejected: over-
engineering; `0/1/2` is the convention every other yascheduler CLI command
follows.

### D5 — AiiDA stdout compatibility contract (the distinguishing constraint)

**Choice:** The success path MUST print exactly `str(task_id)` to stdout —
no prefix, no suffix, no JSON envelope, no decoration. The failure path
MUST print nothing to stdout and an error message to stderr. This change
does NOT add `--json`, `--table`, or any output-mode flag.

**Rationale:** The AiiDA scheduler plugin
(`entrypoints/aiida_plugin.py:_parse_submit_output`) does
`int(stdout.strip())` and treats `ValueError` as "no task id received":
```python
output = stdout.strip()
try:
    int(output)
except ValueError:
    self.logger.error("Submitting failed, no task id received")
return output
```
`_get_submit_command` returns `f"{_CMD_PREFIX}yasubmit {submit_script}"`,
so AiiDA executes `yasubmit` as a subprocess and parses its stdout. Any
decoration of the success output (`"Task 42 submitted"`, `{"task_id": 42}`,
`42\nDone`) breaks `int(output)`. This is the key constraint that
distinguishes `submit` from `show_nodes` (which had no machine consumer of
its output and could freely change format from `key=value` to table/JSON).
For `submit`, the success format is fixed by an external consumer.

**Alternative rejected:** Add a `--json` flag for machine-readable output.
Rejected: `submit` is a write command, not a query command; the `--json`
convention from `relocate-show-nodes-command` applies to query-oriented
commands. The AiiDA consumer needs `str(task_id)`, not JSON. Adding
`--json` would either break AiiDA (if it changed the success format) or be
dead code (if it were ignored on success).

### D6 — `_build_metadata` encapsulates the webhook branch

**Choice:** Extract the current webhook block (lines 100-102) into a
private pure function `_build_metadata(script_params, config, local_folder)
-> dict[str, Any]` that assembles the full metadata dict:
- `local_folder` always set.
- Input files merged via `_read_input_files(engine, local_folder)`.
- If `"PARENT" in script_params and config.local.webhook_url`: add
  `webhook_url` and `webhook_custom_params = {"parent": script_params["PARENT"]}`.

**Rationale:** The current webhook block is inline in `submit()`,
mixing metadata assembly with submission orchestration. Encapsulating it in
`_build_metadata` makes the function pure (no I/O, no side effects), testable
in isolation (the webhook branch is the most conditional logic in the
module), and documents the metadata shape in one place. The logic is
preserved exactly — only the location changes (inline → private function).
No behavior change.

**Alternative rejected:** Keep the webhook block inline in `submit()`.
Rejected: leaves the most conditional logic in the orchestration function;
the in-module split (D2) calls for logic/display separation, and the
webhook branch is logic.

### D7 — `_parse_script_metadata` and `_read_input_files` moved as-is

**Choice:** Move the two existing helpers (lines 34-56) to the new module
unchanged. `_parse_script_metadata(script_text)` parses `key=value` lines
into a dict (malformed lines ignored via the `try/except ValueError: pass`
on `.split("=")`). `_read_input_files(engine, local_folder)` reads each
file in `engine.input_files`, falling back to base64 on
`UnicodeDecodeError`.

**Rationale:** Both functions are already pure (no I/O beyond reading the
script text / input files, no global state, no side effects). Their logic
is correct and tested by the existing behavioral tests. Moving them as-is
preserves behavior and minimizes the diff. The `UnicodeDecodeError →
base64` fallback in `_read_input_files` is a deliberate binary-file
accommodation and stays.

**Alternative rejected:** Rewrite both for clarity. Rejected: no behavior
change is wanted in these helpers; rewriting risks regressions for no
benefit.

### D8 — `argv: list[str] | None = None` testability parameter

**Choice:** `submit(argv: list[str] | None = None) -> None` passes `argv`
through to `_parse_submit_args(argv)` and thence to
`parser.parse_args(argv)`. The `argv=None` default means the console_script
entrypoint (which calls `submit()` with no args) reads `sys.argv` — the
standard argparse convention; tests pass an explicit list.

**Rationale:** Mirrors `entrypoints/cli/init.py:init(argv=None)` and
`entrypoints/cli/show_nodes.py:show_nodes(argv=None)`. Makes the argparse
path unit-testable without `patch("sys.argv", ...)` (the current behavioral
tests use `patch("sys.argv", ...)`, which is fragile and couples tests to
global state). The `init` and `show_nodes` precedents established this
pattern; `yasubmit` follows it.

**Alternative rejected:** Read `sys.argv` inside the function via
`parse_args()` with no argument. Rejected: forces tests to patch
`sys.argv` (a global), which the `init` and `show_nodes` reimplementations
already moved away from.

### D9 — `prog="yasubmit"` for argparse

**Choice:** `argparse.ArgumentParser(prog="yasubmit", description="Submit task
to yascheduler via AiiDA script")`.

**Rationale:** `--help` and error screens show the command name the user
typed. Mirrors `entrypoints/cli/init.py`'s `prog="yainit"` and
`entrypoints/cli/show_nodes.py`'s `prog="yanodes"`. Without `prog`, argparse
derives the program name from `sys.argv[0]`, which for a console_script is
the script path, not the command name.

### D10 — Fresh GRACE-lite markup; drop the FIXME

**Choice:** The new `entrypoints/cli/submit.py` gets fresh
`MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`, function contracts (for
`submit` and the private helpers as appropriate), and block anchors
appropriate to the reimplemented logic. Do NOT carry the
`# FIXME: split adapter and application layer` comment to the new file.

**Rationale:** GRACE-lite requires governed files to carry markup; the
reimplementation has different control flow (argparse dispatch,
`_existing_path` validation, `_build_metadata` encapsulation, try/except
exit handling) than the original, so the markup is written for the new
shape. The FIXME is dropped because (a) its framing ("adapter and
application layer") is stale at the new home — `entrypoints/` is not the
adapter layer; and (b) the in-module function split (D2) resolves the
concern at the appropriate granularity: the "logic" lives in
`_parse_submit_args`/`_parse_script_metadata`/`_read_input_files`/
`_build_metadata`, the "orchestration" in `submit`, all private to the
module. Carrying the FIXME would mark a resolved concern as still open,
with a stale framing. (This adapts `relocate-show-nodes-command` D13's
reasoning: there the FIXME was dropped because the in-module split
resolved the concern; here it is dropped for the same reason, plus the
stale-framing issue specific to submit's move out of the adapter layer.)

### D11 — `entrypoints/cli/__init__.py` facade declarative edit

**Choice:** Make a declarative PURPOSE edit to
`yascheduler/entrypoints/cli/__init__.py` to add `submit` (assuming
`relocate-show-nodes-command` has already generalized the PURPOSE from
"init CLI entry point" to "init and show_nodes CLI entry points"; otherwise
this change generalizes from "init CLI entry point" to "init, show_nodes,
submit CLI entry points" or a generic equivalent). The facade's content (no
re-exports) does not change — `submit` is invoked by console_script, not
imported across layers.

**Rationale:** The facade exists to be the subpackage boundary; its content
(no re-exports) does not change because `submit` is also invoked by
console_script. The `init` and `show_nodes` precedents did not add re-
exports to the facade; `submit` does not add one either. The PURPOSE wording
edit is declarative (generalizes the description to cover the third
resident), not a decision-level change. Mirrors `relocate-show-nodes-
command` D14.

**Alternative rejected:** Leave the PURPOSE as "init CLI entry point".
Rejected: stale wording after two more residents moved in; declarative
generalization keeps the contract accurate.

### D12 — `M-CLI-COMMANDS → M-DI` CrossLink amended, not dropped

**Choice:** The existing
`<CrossLink from="M-CLI-COMMANDS" to="M-DI" relation="uses make_cli_deps for
CLI submit; make_daemon for daemon entry" />` covers both `submit` AND
`daemon` in one relation string. This change amends the relation to drop
only the "CLI submit" clause, leaving "uses make_daemon for daemon entry"
(because `daemonize` still remains in `infra/cli/` and still uses `make_daemon`
via `M-CLI-COMMANDS`). The new edge
`<CrossLink from="M-ENTRYPOINTS-CLI-SUBMIT" to="M-DI" relation="uses
make_cli_deps for CLI submit" />` takes over the submit clause.

**Rationale:** Dropping the whole `M-CLI-COMMANDS → M-DI` edge would
incorrectly remove the daemon relationship, which still applies. Amending
the relation string preserves the daemon clause while removing the stale
submit clause. This is a new precision issue specific to `submit` —
`relocate-show-nodes-command` had no analogous combined edge to edit
(`show_nodes` was not in the `M-CLI-COMMANDS → M-DI` relation string).

**Alternative rejected:** Drop the whole edge and add a new
`M-CLI-COMMANDS → M-DI relation="uses make_daemon for daemon entry"`.
Rejected: amending the relation string is a smaller edit than
drop-and-re-add and preserves the edge identity.

### D13 — `DF-SUBMIT` untouched (YAGNI)

**Choice:** Do NOT modify the existing `DF-SUBMIT` data-flow element, which
describes the client API path:
`<DF-SUBMIT NAME="Submit task">M-ENTRYPOINTS-CLIENT -> M-DI ->
M-APPLICATION-SUBMIT -> M-APPLICATION-UOW -> M-DOMAIN-PORTS</DF-SUBMIT>`.

**Rationale:** The CLI submit path is trivially
`M-ENTRYPOINTS-CLI-SUBMIT → M-DI → M-APPLICATION-SUBMIT → ...` (it rejoins
the client path at `M-DI`). Adding a parallel `/` alternative to `DF-SUBMIT`
would mix two different entry points (the Python/CLI client API vs the
`yasubmit` console_script) in one flow element, obscuring both. The new
`M-ENTRYPOINTS-CLI-SUBMIT` node + CrossLink (D12) makes the CLI path
discoverable in the graph without bloating `DF-SUBMIT`. Per user decision
(YAGNI).

**Alternative rejected:** Add `M-ENTRYPOINTS-CLI-SUBMIT -> M-DI` as a `/`
alternative in `DF-SUBMIT`. Rejected: mixes entry points; the new graph
node already makes the CLI path visible.

## Risks / Trade-offs

- **[Risk] Missing-file exit code changes from 1 to 2.** → Mitigation: the
  AiiDA scheduler plugin treats any `retval != 0` as a failed submission
  (logs "Submitting failed, no task id received" when `int(stdout.strip())`
  fails on empty stdout), so the change from 1 to 2 is AiiDA-compatible.
  Shell scripts that check `if yasubmit ...; then` (success = 0) are
  unaffected; scripts that check `== 1` specifically would see a change,
  but no such consumer is known (verified by grep — no caller matches the
  `ValueError` traceback output).
- **[Risk] Operators relying on the traceback for debugging lose it.** →
  Mitigation: the new `except Exception as e: print(f"Error: {e}",
  file=sys.stderr); sys.exit(1)` path prints the exception message (not the
  full traceback) to stderr. For ENGINE-key and unsupported-engine errors,
  the message is the same `ValueError` text. For unexpected exceptions, the
  message is `str(e)`. If debugging requires the full traceback, setting
  `LOGLEVEL=DEBUG` or running under a debugger restores it; the contract
  trades traceback noise for a clean, scriptable error message.
- **[Risk] `_existing_path` raises `ArgumentTypeError`, not `ValueError`.**
  → Mitigation: argparse catches `ArgumentTypeError` from `type=` callables
  and converts it to a usage error (exit 2) with the message formatted as
  `argument script: <message>`. The error message text is `not a file: <s>`,
  which is clearer than the current `Script parameter is not a file name`.
  Tests assert the exit code (2) and the stderr pattern, not the exact
  message shape.
- **[Trade-off] Temporary asymmetry: 3 of 6 CLI commands in `entrypoints/`,
  3 in `infra/cli/`.** → Accepted: `init` (bootstrap), `show_nodes`
  (execution-query), and `submit` (execution-write) are relocated; the
  other 3 execution commands (`check_status`, `manage_node`, `daemonize`)
  may follow in separate changes. This change completes the relocation
  pattern for the three commands with the clearest entrypoint
  characterization.
- **[Trade-off] In-module function split (D2) instead of a use case.** →
  Accepted: a `submit_script` use case would have one caller and no prospect
  of a second; the in-module split achieves logic/orchestration separation
  at the right granularity. The contract records the promotion condition so
  a future second consumer triggers extraction rather than duplication.
- **[Trade-off] `DF-SUBMIT` does not reflect the CLI path.** → Accepted:
  the new `M-ENTRYPOINTS-CLI-SUBMIT` node + CrossLink makes the CLI path
  discoverable; adding it to `DF-SUBMIT` would mix two entry points (client
  API vs console_script) in one flow element, obscuring both. YAGNI per user
  decision.

## Migration Plan

**Deploy:**
1. Install the new package version (contains
   `yascheduler/entrypoints/cli/submit.py`; no longer contains
   `yascheduler/infra/cli/submit.py`).
2. `yasubmit` console_script now resolves to
   `yascheduler.entrypoints.cli.submit:submit` (via updated `pyproject.toml`).
   Re-install the package (`uv sync` or `pip install -e .`) to refresh the
   entrypoint.
3. No DB migration, no config change, no service file change needed.
   `yasubmit` is a write command but uses the existing `submit_task` use
   case and DB schema; no schema migration is required.

**Rollback:**
1. Revert to the previous package version (restores
   `yascheduler/infra/cli/submit.py`, restores `pyproject.toml` line 54,
   restores the `infra/cli/__init__.py` re-export).
2. Re-install the package to refresh the entrypoint.
3. No data or state to clean up — `yasubmit` inserts via `submit_task`; any
   tasks submitted by the new version are normal rows in the existing
   schema.

**Open Questions:** None. All decisions captured in D1–D13.