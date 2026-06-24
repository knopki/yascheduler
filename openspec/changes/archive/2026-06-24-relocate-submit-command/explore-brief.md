# Explore Brief — relocate-submit-command

## Problem

`yascheduler/infra/cli/submit.py` (105 lines) is the `yasubmit` CLI command —
parses an AiiDA script file, reads engine input files, and submits a task via
`CLIDeps.submit`. It was explicitly listed as deferred-for-migration into the
`entrypoints/` layer by the archived `add-entrypoints-layer` change. The
archived `relocate-init-command` change moved `init.py` into
`yascheduler/entrypoints/cli/init.py` as the first resident, establishing the
`entrypoints/cli/` home and the relocation pattern (real move, no compat shim,
layer direction `entrypoints → infra` preserved, fresh GRACE-lite markup,
argparse-based reimplemented logic, `0`/`1`/`2` exit-code contract). The
in-progress `relocate-show-nodes-command` is the second resident (execution-
command precedent). `submit` is the third resident, following after
`relocate-show-nodes-command` archives (per user decision: this change runs
after that one).

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

Issues with the current shape, in scope for this change:
- No `prog="yasubmit"`: `--help`/error screens derive the program name from
  `sys.argv[0]` (the console_script path), not the command name the user
  typed.
- No `argv` testability parameter: tests must `patch("sys.argv", ...)`, which
  is fragile and couples tests to global state. The `init` and `show_nodes`
  precedents moved away from this via `argv: list[str] | None = None`.
- No exit-code contract: `ValueError` (missing file, missing engine,
  unsupported engine) propagates as a traceback with Python's default
  uncaught-exception exit code (1, but non-deterministic in shape — traceback
  noise on stderr, no clean error message). DB/config errors similarly
  propagate as tracebacks. AiiDA's `_parse_submit_output` treats retval != 0
  as a failed submission (logs "Submitting failed, no task id received" when
  `int(stdout.strip())` fails), so the current behavior happens to be
  AiiDA-compatible, but the exit code is incidental rather than contracted.
- File-existence validation done in the body via
  `if not script_file.exists(): raise ValueError(...)`, which makes a
  usage-shaped error (missing required input file) surface as a runtime exit
  1 instead of an argparse exit 2.
- `# FIXME: split adapter and application layer` carried from the `infra/cli/`
  template. The FIXME's framing ("adapter and application layer") is
  stale at the new home (`entrypoints/` is not the adapter layer), and the
  in-module function split resolves the concern at the appropriate
  granularity (same reasoning as `relocate-show-nodes-command` D13, adapted
  for submit's two existing helpers).

## Rejected alternatives

- **Pure relocation (move only, no reimplementation).** Rejected by the user:
  "Нет, не надо вот придумывать какие-то pure relocation. Переносишь и
  реимплементируешь." This change follows the `relocate-init-command` /
  `relocate-show-nodes-command` pattern (move + reimplement with argparse,
  exit codes, `argv` parameter, in-module split, fresh GRACE-lite markup).
- **Move all remaining CLI commands (`check_status`, `manage_node`,
  `daemonize`) to `entrypoints/cli/` in one change.** Rejected for scope:
  each command has its own redesign surface. `submit` is scoped here; the
  others may follow in separate changes. This change is the third resident
  and follows the established execution-command relocation pattern.
- **Keep a compat shim at `infra/cli/submit.py` re-exporting from
  `entrypoints/cli/submit.py`.** Rejected: any `infra → entrypoints`
  re-export inverts the layer direction
  (`entrypoints → infra → application → domain → shared`) enforced by
  import-linter's `layers` contract. The `relocate-init-command` precedent
  established that entrypoint residents are invoked by path / console_script,
  not re-exported from `infra/`. No deep import of
  `from yascheduler.infra.cli.submit import submit` exists in production
  code (verified by grep); the only consumers are
  `yascheduler/infra/cli/__init__.py` (re-export), `pyproject.toml`
  (console_script target), and two test files — all updated in this change.
- **Add `--json` / `--table` / output-mode flags to `submit`.** Rejected:
  `submit` is not a query command. The AiiDA scheduler plugin
  (`entrypoints/aiida_plugin.py:_parse_submit_output`) parses `stdout` as
  the task ID (`int(stdout.strip())`), so the success output MUST remain
  exactly `str(task_id)` — no prefixes, no JSON envelope, no decoration.
  Adding output-mode flags would either break AiiDA (if they changed the
  success format) or be dead code (if they were ignored on success). The
  `--json` convention established by `relocate-show-nodes-command` applies to
  query-oriented commands; `submit` is a write command.
- **Add a `query_submit` use case into `yascheduler/application/`.** Rejected
  as YAGNI: no second consumer of the script-parsing + metadata-building
  logic exists. The AiiDA client submits via `queue_submit_task_async` (a
  different entry point that takes label/metadata/engine directly, not a
  script file); the daemon does not submit. The script-parsing logic is CLI-
  specific input shaping, not business logic. The resolution is in-module
  splitting into private pure functions; the contract records that
  promotion to `application/` awaits a second consumer.
- **Sort or transform the stdout output.** Rejected: AiiDA's contract is
  `int(stdout.strip())`; any transformation (prefix, suffix, JSON wrapping,
  pretty-printing) breaks the consumer. The success path MUST print exactly
  `str(task_id)`.

## Final approach — labels / dimensions / mapping tables

### Argparse shape

| invocation                       | positional | --help | action                              | exit |
| -------------------------------- | --------- | ------ | ----------------------------------- | ---- |
| `yasubmit`                       | -         | -      | argparse error: missing script arg  | 2    |
| `yasubmit script.in`             | script.in | -      | parse script, submit, print task_id | 0/1  |
| `yasubmit script.in extra.in`     | -         | -      | argparse error: extra positional    | 2    |
| `yasubmit --help`                | n/a       | yes    | argparse help screen                | 0    |
| `yasubmit --bogus`               | -         | -      | argparse error: unknown flag       | 2    |
| `yasubmit /nonexistent.in`        | (missing) | -      | argparse error: file does not exist | 2    |
| `yasubmit script.in` (no ENGINE) | script.in | -      | body validation: exit 1, stderr     | 1    |
| `yasubmit script.in` (bad ENGINE) | script.in | -      | body validation: exit 1, stderr     | 1    |

Argparse details:
- `prog="yasubmit"` — `--help`/error screens show the command name (mirrors
  `init`'s `prog="yainit"` and `show_nodes`'s `prog="yanodes"`).
- One positional `script` with `type=existing_path`, where `existing_path`
  is a local callable: `def _existing_path(s: str) -> Path: p = Path(s); if
  not p.is_file(): raise argparse.ArgumentTypeError(f"not a file: {s}"); return p`.
  This makes missing-file a usage error (exit 2) at the argparse layer, not
  a runtime error (exit 1) in the body. Mirrors the argparse-layer / body-
  layer validation split: argparse owns argument *shape* (file exists); the
  body owns *content* validation (ENGINE key present, engine known to
  config).
- `argv: list[str] | None = None` passed through to `parser.parse_args(argv)`.
  The `argv=None` default means the console_script entrypoint (which calls
  `submit()` with no args) reads `sys.argv` — the standard argparse
  convention; tests pass an explicit list. Mirrors `init` and `show_nodes`.
- `--help` shows the standard argparse help screen (argparse default).

### Validation split

| validation                  | layer    | error                                      | exit |
| --------------------------- | -------- | ------------------------------------------ | ---- |
| script argument present     | argparse | missing-argument error                     | 2    |
| script path is an existing file | argparse | `type=existing_path` raises ArgumentTypeError | 2    |
| no extra positional args    | argparse | argparse error                             | 2    |
| ENGINE key present in script | body     | `ValueError("Script has not defined an engine")` | 1    |
| engine name known to config | body     | `ValueError(f"Engine {name} is not supported")` | 1    |
| engine input files readable | body     | `UnicodeDecodeError` → base64 fallback (current behavior preserved) | — (handled) |
| DB / config / unexpected    | body     | `Exception` caught → stderr message        | 1    |

Behavior change note: missing-file currently raises `ValueError` → exit 1
(traceback). After this change, missing-file is an argparse `type` error →
exit 2 (clean argparse error message, no traceback). This is a deliberate
improvement within the reimplementation scope: usage errors get exit 2, only
runtime errors get exit 1. The AiiDA scheduler plugin treats any retval != 0
as a failed submission (`int(stdout.strip())` fails on empty stdout → logs
"Submitting failed, no task id received"), so changing exit 1 → 2 for the
missing-file case is AiiDA-compatible (still != 0).

### Exit code contract

| code | meaning                              | source                                                       |
| ---- | ------------------------------------ | ------------------------------------------------------------ |
| 0    | success                              | `print(str(task_id))`, normal completion                      |
| 1    | runtime failure                      | ENGINE-key missing, unsupported engine, DB error, config parse error, any unexpected exception |
| 2    | argparse error                       | argparse default (missing script arg, file not found, extra positional, unknown flag, `--help` exits 0 internally) |

Mirrors the `relocate-init-command` / `relocate-show-nodes-command`
precedent. `2` is the argparse default that shell scripts expect for usage
errors; reusing it avoids fighting the framework. `1` for runtime failures
is the POSIX convention. `0` on success preserves the AiiDA stdout
contract.

Note: `submit` does NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits 0. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the body. (Same as `show_nodes`;
`init` calls `sys.exit(0)` explicitly because its body has no other terminal
point.)

### Output contract (AiiDA compatibility — preserved)

| path         | stdout              | stderr              | exit |
| ------------ | ------------------- | ------------------- | ---- |
| success      | `str(task_id)`      | (empty)             | 0    |
| ENGINE missing | (empty)           | `Error: Script has not defined an engine` | 1 |
| engine unknown | (empty)           | `Error: Engine {name} is not supported` | 1 |
| DB/config error | (empty)          | `Error: {exception}` | 1    |
| argparse error | (empty)           | argparse usage message | 2    |
| `--help`     | argparse help       | (empty)             | 0    |

The success path MUST print exactly `str(task_id)` — no prefix, no suffix,
no decoration. AiiDA's `entrypoints/aiida_plugin.py:_parse_submit_output`
does `int(stdout.strip())` and treats failure as "no task id received".
Any decoration breaks the consumer. This is the key constraint that
distinguishes `submit` from `show_nodes` (which had no machine consumer of
its output and could freely change format).

### Module shape (in-module splitting, no use-case extraction)

```
entrypoints/cli/submit.py
  _existing_path(s)              # pure: argparse type validator → Path (raises ArgumentTypeError if not a file)
  _parse_submit_args(argv)       # pure: argparse → Namespace (prog="yasubmit", positional script with type=existing_path)
  _parse_script_metadata(text)   # pure: key=value lines → dict  (already exists, moved as-is)
  _read_input_files(engine, folder) # pure: Engine × str → dict  (already exists, moved as-is, UnicodeDecodeError→base64 fallback preserved)
  _build_metadata(params, config, local_folder) # pure: assemble metadata dict, encapsulate webhook branch
  submit(argv=None)              # @to_sync: parse → config → deps → validate ENGINE → build metadata → submit → print(str(task_id))
```

`_build_metadata` encapsulates the current webhook block (lines 100-102):
if `"PARENT" in script_params and config.local.webhook_url`, adds
`webhook_url` and `webhook_custom_params`. The current logic is preserved
exactly; only the location changes (in-line → private function). No
behavior change.

`_parse_script_metadata` and `_read_input_files` are moved as-is (their
logic is already pure and correct).

Do NOT extract a `submit_script` or `query_submit` use case into
`yascheduler/application/` — YAGNI: no second consumer of the script-parsing
logic exists (the AiiDA client submits via `queue_submit_task_async` with
direct label/metadata/engine args, not via script files; the daemon does
not submit). The contract records that promotion to `application/` awaits a
second consumer. (Mirrors `relocate-show-nodes-command` D2 reasoning.)

### FIXME drop

Do NOT carry the `# FIXME: split adapter and application layer` comment to
the new file. Rationale (mirrors `relocate-show-nodes-command` D13, adapted):
the FIXME's framing ("adapter and application layer") is stale at the new
home — `entrypoints/` is not the adapter layer, and the in-module function
split (`_parse_submit_args`, `_parse_script_metadata`, `_read_input_files`,
`_build_metadata`) resolves the logic-vs-IO separation at the appropriate
granularity (functions, not layers). Carrying the FIXME would mark a
resolved concern as still open, with a stale framing. (Per user decision 1.)

## Cross-module data flows

### Call path (after change)

```
yasubmit (console_script)
  → yascheduler.entrypoints.cli.submit.submit()
      → _parse_submit_args(argv)            # argparse: prog="yasubmit", positional script (type=existing_path)
      → Config.from_config_parser(CONFIG_FILE)
      → make_cli_deps(config)
      → try:
          script_text = script_file.read_text()   # script_file from Namespace
          script_params = _parse_script_metadata(script_text)
          engine_name = script_params.get("ENGINE")
          if not engine_name: raise ValueError("Script has not defined an engine")
          engine = config.engines.get(engine_name)
          if not engine: raise ValueError(f"Engine {engine_name} is not supported")
          metadata = _build_metadata(script_params, config, os.getcwd())
          task_id = await deps.submit(label, dict(metadata), engine.name)
          print(str(task_id))
          → implicit exit 0
        except Exception as e:
          print(f"Error: {e}", file=sys.stderr); sys.exit(1)
```

Note: `submit` does NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits 0. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the body.

### Layer direction (verified)

```
yascheduler.entrypoints.cli.submit
  → yascheduler.config.Config                     (entrypoints → config, outside-layer-set ✓)
  → yascheduler.di.make_cli_deps                  (entrypoints → di, outside-layer-set ✓ — same as init, show_nodes)
  → yascheduler.shared.CONFIG_FILE, to_sync       (entrypoints → shared ✓)
```

`import-linter` `layers` contract stays green:
`["yascheduler.entrypoints", "yascheduler.infra", "yascheduler.application",
"yascheduler.domain", "yascheduler.shared"]`. `ignore_imports` stays `[]`.
No new `ignore_imports` entries needed. (`make_cli_deps` lives in
`yascheduler/di.py` which is outside the layered set — same pattern `init.py`
and `show_nodes.py` already use; `check_status.py` in `infra/cli/` already
imports `make_cli_deps` the same way.)

### AiiDA consumer (preserved, not touched)

```
entrypoints/aiida_plugin.py:_get_submit_command
  → returns f"{_CMD_PREFIX}yasubmit {submit_script}"
  → AiiDA executes via SSH transport
  → _parse_submit_output(retval, stdout, stderr):
       stdout.strip() → int() → task_id
       stderr.strip() → logger.warning
       retval != 0 or int() fails → logger.error("Submitting failed, no task id received")
```

This change does NOT touch `aiida_plugin.py`. The stdout contract
(`str(task_id)` on success, empty on failure) is preserved exactly.

### Files added / removed / modified

| action   | path                                                | note                                                                  |
| -------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| add      | `yascheduler/entrypoints/cli/submit.py`             | real implementation (reimplemented)                                   |
| remove   | `yascheduler/infra/cli/submit.py`                   | moved, not shimmed                                                    |
| modify   | `yascheduler/infra/cli/__init__.py`                 | drop `from .submit import submit` + `"submit"` from `__all__` + MODULE_MAP line; bump VERSION; CHANGE_SUMMARY |
| modify   | `pyproject.toml` line 54                           | `yasubmit = "yascheduler.entrypoints.cli.submit:submit"`              |
| modify   | `openspec/specs/package-facades/spec.md` R1 example | drop `submit` from infra/cli submodule list (assuming `relocate-show-nodes-command` archived first: list becomes `check_status`, `daemonize`, `manage_node`; if not yet archived: `check_status`, `daemonize`, `manage_node`, `show_nodes`, `submit` → drop `submit` → `check_status`, `daemonize`, `manage_node`, `show_nodes`) |
| modify   | `openspec/specs/cli-commands/spec.md`               | update yasubmit module path; update the "other N CLI commands" counter; add exit-code contract; add argv parameter; add prog="yasubmit"; add file-existence-via-argparse decision |
| modify   | `docs/knowledge-graph.xml`                          | drop `M-CLI-COMMANDS` `<fn-submit>`; add `M-ENTRYPOINTS-CLI-SUBMIT` node + CrossLink |
| modify   | `tests/unit/test_cli_smoke.py`                      | delete `test_submit_function_exists` (low-value smoke; replaced by real unit tests) |
| modify   | `tests/unit/test_cli_behavioral.py`                 | delete `TestSubmit` class (moved to dedicated file); drop `submit_mod` module-level import |
| add      | `tests/unit/test_cli_submit.py`                     | focused unit tests (new file, mirrors `test_cli_init.py` / `test_cli_show_nodes.py` shape) |

### Coordination with `relocate-show-nodes-command` (sequencing)

This change runs AFTER `relocate-show-nodes-command` archives (per user
decision 5). Implications for the state this change sees:

- `yascheduler/entrypoints/cli/show_nodes.py` already exists (second
  resident). `entrypoints/cli/__init__.py` PURPOSE already generalized by
  show_nodes (from "init CLI entry point" to "init and show_nodes CLI entry
  points" or similar). This change makes a declarative edit to add `submit`
  to the PURPOSE wording (or generalize further), consistent with show_nodes
  D14's declarative-edit pattern.
- `package-facades` spec R1 example already dropped `show_nodes` (by
  show_nodes change). This change drops `submit` → list becomes
  `check_status`, `daemonize`, `manage_node`.
- `cli-commands` spec "other N CLI commands remain in infra/cli/" counter
  already updated by show_nodes (from 5 to 4). This change updates to 3.
- `knowledge-graph.xml`: `M-ENTRYPOINTS-CLI-SHOW-NODES` already exists. This
  change adds `M-ENTRYPOINTS-CLI-SUBMIT` as the third entrypoints CLI node.
  `M-CLI-COMMANDS` already lost `<fn-show_nodes>`; this change drops
  `<fn-submit>`.

No conflict: the two changes touch disjoint elements of the same shared
artifacts (each drops its own submodule from the shared list, each adds its
own graph node).

## Open questions

None. All decisions captured above. Ready to write proposal.