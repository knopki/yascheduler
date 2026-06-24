## Why

`yasubmit` lives at `yascheduler/infra/cli/submit.py` but is an entrypoint
(a CLI command invoked by `console_script`), not an infra adapter. The
archived `add-entrypoints-layer` change listed `infra/cli/` as deferred-for-
migration; the archived `relocate-init-command` change then moved `init.py`
into `yascheduler/entrypoints/cli/init.py` as the first resident, establishing
the `entrypoints/cli/` home and the relocation pattern (real move, no compat
shim, layer direction `entrypoints → infra` preserved, fresh GRACE-lite
markup, argparse-based reimplemented logic, `0`/`1`/`2` exit-code contract).
The in-progress `relocate-show-nodes-command` is the second resident
(execution-query precedent). `submit` is the third resident — the
execution-write counterpart — and follows after `relocate-show-nodes-
command` archives.

The current `submit()` also has real issues worth fixing in the same move:
no `prog="yasubmit"` (`--help`/error screens show the console_script path,
not the command name), no `argv` testability parameter (tests must
`patch("sys.argv", ...)`, a fragile global-state coupling), no exit-code
contract (`ValueError` propagates as a traceback with Python's default
uncaught-exception exit code — AiiDA-compatible only by accident), and file-
existence validation done in the body via `if not script_file.exists(): raise
ValueError(...)` (a usage-shaped error surfacing as runtime exit 1 instead
of argparse exit 2). The move is the moment to bring it to the modern standard
`init` and `show_nodes` set (`prog`, `argv`, `0`/`1`/`2` exit codes, fresh
GRACE-lite markup) while preserving the AiiDA scheduler plugin's stdout
contract exactly.

## What Changes

- Move `yascheduler/infra/cli/submit.py` →
  `yascheduler/entrypoints/cli/submit.py` (real implementation, not a shim).
  This is the third resident of `entrypoints/cli/`, mirroring `init.py`
  (from `relocate-init-command`) and `show_nodes.py` (from
  `relocate-show-nodes-command`). The other 3 execution commands
  (`check_status`, `manage_node`, `daemonize`) stay in `infra/cli/` for
  follow-up changes if pursued.
- Delete `yascheduler/infra/cli/submit.py`. Drop `from .submit import submit`
  and `"submit"` from `__all__` in `yascheduler/infra/cli/__init__.py`; drop
  the `submit - Re-exported from .submit` line from its `MODULE_MAP`. No
  compat shim: any `infra → entrypoints` re-export would invert the layer
  direction enforced by `import-linter` (same reasoning as
  `relocate-init-command` D1 and `relocate-show-nodes-command` D1).
- Update `pyproject.toml` line 54:
  `yasubmit = "yascheduler.entrypoints.cli.submit:submit"`.
- Reimplement `submit()` with `argparse`:
  - `prog="yasubmit"` passed to `ArgumentParser` so `--help` and error
    screens show the command name (mirrors `init`'s `prog="yainit"` and
    `show_nodes`'s `prog="yanodes"`).
  - One positional `script` with `type=_existing_path`, where
    `_existing_path(s)` is a local callable that returns `Path(s)` if it
    is an existing file or raises `argparse.ArgumentTypeError(f"not a file:
    {s}")`. This makes missing-file a usage error (exit 2) at the argparse
    layer, not a runtime error (exit 1) in the body. Mirrors the argparse-
    layer / body-layer validation split: argparse owns argument *shape* (file
    exists); the body owns *content* validation (ENGINE key present, engine
    known to config).
  - `argv: list[str] | None = None` parameter passed through to
    `parser.parse_args(argv)`. The `argv=None` default means the
    console_script entrypoint reads `sys.argv` (standard argparse
    convention); tests pass an explicit list. Mirrors `init` and
    `show_nodes`.
  - `--help` shows the standard argparse help screen (argparse default).
- Exit code contract (mirrors `relocate-init-command` D3 and
  `relocate-show-nodes-command` D5):
  - `0` on success (`print(str(task_id))`, normal completion).
  - `1` on runtime failure: ENGINE key missing in script, engine name
    unknown to config, DB error, config parse error, any unexpected
    exception caught at the top level.
  - `2` on argparse error (argparse default — missing script arg, file not
    found via `type=_existing_path`, extra positional, unknown flag).
- Output contract preserved exactly (AiiDA compatibility — the key
  constraint distinguishing `submit` from `show_nodes`):
  - Success: `stdout = str(task_id)` — exactly the integer, no prefix, no
    suffix, no decoration, no JSON envelope. `stderr` empty. Exit 0.
  - Runtime failure: `stdout` empty, `stderr = Error: {exception}`, exit 1.
  - The AiiDA scheduler plugin
    (`entrypoints/aiida_plugin.py:_parse_submit_output`) parses
    `int(stdout.strip())` and treats failure as "no task id received"; any
    decoration breaks it. This change does NOT add `--json`, `--table`, or
    any output-mode flag (submit is a write command, not a query command;
    `--json` convention from `show_nodes` applies to query-oriented
    commands only).
- Split the logic into private pure functions in the new module:
  `_existing_path` (argparse type validator), `_parse_submit_args(argv)`
  (argparse → Namespace), `_parse_script_metadata` (moved as-is),
  `_read_input_files` (moved as-is, `UnicodeDecodeError → base64` fallback
  preserved), `_build_metadata` (encapsulates the current webhook block,
  no behavior change). Do NOT extract a `submit_script` or `query_submit`
  use case into `application/` — YAGNI: no second consumer of the script-
  parsing logic exists (the AiiDA client submits via
  `queue_submit_task_async` with direct label/metadata/engine args, not via
  script files; the daemon does not submit). The contract records that
  promotion to `application/` awaits a second consumer.
- Do NOT carry the `# FIXME: split adapter and application layer` comment to
  the new file: the FIXME's framing ("adapter and application layer") is
  stale at the new home (`entrypoints/` is not the adapter layer), and the
  in-module function split resolves the logic-vs-IO separation at the
  appropriate granularity (functions, not layers). Same reasoning as
  `relocate-show-nodes-command` D13, adapted for submit's two existing
  helpers.
- Fresh GRACE-lite markup at the new path: `MODULE_CONTRACT`, `MODULE_MAP`,
  `CHANGE_SUMMARY`, function contracts, and block anchors appropriate to
  the reimplemented logic. The `entrypoints/cli/__init__.py` facade gets a
  declarative PURPOSE edit to add `submit` (assuming `relocate-show-nodes-
  command` has already generalized it; otherwise this change generalizes
  from "init CLI entry point" to "init, show_nodes, submit CLI entry
  points" or a generic equivalent).
- Update `openspec/specs/package-facades/spec.md`: drop `submit` from the
  R1 example listing `infra/cli/__init__.py` submodules (assuming
  `relocate-show-nodes-command` archived first: the pre-state list is
  `check_status`, `daemonize`, `manage_node`, `submit` (show_nodes already
  dropped); this change drops `submit` → `check_status`, `daemonize`,
  `manage_node`).
- Update `openspec/specs/cli-commands/spec.md`:
  - Update the `yasubmit` requirement: module path
    `infra/cli/submit.py` → `entrypoints/cli/submit.py`; add the
    `prog="yasubmit"` detail, the `argv` testability parameter, the
    `type=_existing_path` file-existence validation (exit 2 for missing
    file), the exit-code contract (`0`/`1`/`2`), the argparse-layer vs
    body-layer validation split, and the AiiDA stdout compatibility
    contract (`str(task_id)` on success, empty on failure, no output-mode
    flags).
  - Update the "other N CLI commands remain in `infra/cli/`" counter
    (assuming `relocate-show-nodes-command` archived first: from "other 4"
    to "other 3": `check_status`, `manage_node`, `daemonize`).
- Update `docs/knowledge-graph.xml`:
  - `M-CLI-COMMANDS`: delete the `<fn-submit>` annotation.
  - Add a new module node `M-ENTRYPOINTS-CLI-SUBMIT`
    (`path: yascheduler/entrypoints/cli/submit.py`,
    `depends: M-CONFIG, M-DI, M-SHARED`).
  - Add `CrossLink from="M-ENTRYPOINTS-CLI-SUBMIT" to="M-DI"
    relation="uses make_cli_deps for CLI submit"`. The existing
    `<CrossLink from="M-CLI-COMMANDS" to="M-DI" relation="uses
    make_cli_deps for CLI submit; make_daemon for daemon entry" />` covers
    both `submit` AND `daemon` in one relation string; this change amends
    that relation to drop only the "CLI submit" clause, leaving
    "uses make_daemon for daemon entry" (NOT deleting the edge — the daemon
    clause still applies while `daemonize` remains in `infra/cli/`).
  - Do NOT touch `DF-SUBMIT` (the existing data-flow element describes the
    client API path `M-ENTRYPOINTS-CLIENT → M-DI → M-APPLICATION-SUBMIT →
    ...`; the CLI path is trivially `M-ENTRYPOINTS-CLI-SUBMIT → M-DI →
    M-APPLICATION-SUBMIT`, and adding a parallel `/` alternative would mix
    two different entry points in one flow element — YAGNI per user decision).
- Tests:
  - Delete `tests/unit/test_cli_smoke.py::test_submit_function_exists`
    (low-value smoke test that only checks the function exists and is
    `@to_sync`-decorated — replaced by real unit tests, same as
    `relocate-init-command` and `relocate-show-nodes-command` did).
  - Delete the `TestSubmit` class from
    `tests/unit/test_cli_behavioral.py` (moved to a dedicated file); drop
    the `submit_mod` module-level import.
  - Add `tests/unit/test_cli_submit.py` with focused unit tests: argparse
    (`--help`, missing script arg → exit 2, file not found via
    `type=_existing_path` → exit 2, extra positional → exit 2, unknown flag
    → exit 2, `prog="yasubmit"` in help/error screens), happy path
    (`stdout == str(task_id)`, `deps.submit` called with correct label /
    metadata / engine_name), validation errors (ENGINE key missing → exit
    1 + stderr message, engine name unknown → exit 1 + stderr message,
    stdout empty on failure), webhook branch (PARENT +
    `config.local.webhook_url` set → metadata contains `webhook_url` +
    `webhook_custom_params`; no PARENT or no webhook_url → no webhook
    keys), `_parse_script_metadata` (key=value parsing, malformed lines
    ignored), `_read_input_files` (utf-8 file → text content,
    `UnicodeDecodeError` → base64 fallback), `_build_metadata` (local_folder
    always present, webhook branch encapsulated), exit codes (0 success, 1
    runtime error, 2 argparse error), `argv` injection (no `patch sys.argv`
    needed). Mark with `pytest.mark.unit`.

### Out of scope (explicit, deferred to follow-up changes)

- The other 3 CLI commands (`check_status`, `manage_node`, `daemonize`)
  remain in `yascheduler/infra/cli/`; their migration into `entrypoints/cli/`
  is tracked separately. This change follows the execution-command
  relocation pattern established by `relocate-show-nodes-command`; the
  others may follow one per change.
- No new `application/submit_script.py` or `application/query_submit.py`
  use case (YAGNI — no second consumer of the script-parsing logic).
- No `--json`, `--table`, or any output-mode flag (submit is a write
  command; the AiiDA stdout contract forbids decorating the success
  output; `--json` convention applies to query-oriented commands only).
- No new dependencies — stdlib only (`argparse`, `pathlib`, `base64`,
    `logging`, `os`, `sys`).
- `relocate-show-nodes-command` (in progress, archives first) — unaffected;
  this change assumes its artifacts are already in the codebase.
- `schema-migrations` (in progress) — unaffected; `yasubmit` touches no
  schema, only inserts via `submit_task` use case. Parallel work, no
  conflict.
- `di.py`, `application/`, `domain/`, `infra/persistence/`,
  `entrypoints/aiida_plugin.py` — unchanged.

## Capabilities

### New Capabilities

_None._ The relocation and reimplementation are structural/operational
concerns for an existing command. No new spec capability is introduced:
`yasubmit` already exists under `cli-commands`, and its requirements are
modified (below) rather than replaced.

### Modified Capabilities

- `cli-commands`: the `yasubmit` command gains `prog="yasubmit"`, the
  `argv: list[str] | None = None` testability parameter, the
  `type=_existing_path` file-existence validation (exit 2 for missing file
  at the argparse layer instead of exit 1 in the body), the `0`/`1`/`2`
  exit-code contract, the argparse-layer vs body-layer validation split, the
  AiiDA stdout compatibility contract (`str(task_id)` on success, empty on
  failure, no output-mode flags), the in-module function split, and a new
  module path (`entrypoints/cli/submit.py`). The "other N CLI commands
  remain in `infra/cli/`" counter decrements.
- `package-facades`: the R1 example listing `infra/cli/__init__.py`
  submodules drops `submit` (it has moved to `entrypoints/cli/`). No
  layer-direction or facade-content requirement changes.

## Impact

- **Code**: `yascheduler/entrypoints/cli/submit.py` (1 new file);
  `yascheduler/infra/cli/submit.py` removed;
  `yascheduler/infra/cli/__init__.py` loses the `submit` re-export +
  `__all__` entry + MODULE_MAP line (bump VERSION, CHANGE_SUMMARY);
  `yascheduler/entrypoints/cli/__init__.py` gets a declarative PURPOSE edit.
- **CLI**: `yasubmit` behavior: `--help` works; missing-file error now exits
  2 (argparse `type` error) with a clean argparse message instead of exit 1
  with a traceback — the one observable behavior change, AiiDA-compatible
  (still != 0). ENGINE-key-missing and unsupported-engine errors now exit 1
  with a clean stderr message instead of a traceback. Success path
  (`stdout == str(task_id)`, exit 0) unchanged. No **BREAKING** change to
  the command name or the success invocation; the AiiDA scheduler plugin
  contract is preserved exactly.
- **Config**: `pyproject.toml` line 54 (console_script target) updated.
  `[tool.importlinter]` unchanged.
- **Tests**: `tests/unit/test_cli_smoke.py` loses one test method;
  `tests/unit/test_cli_behavioral.py` loses the `TestSubmit` class and the
  `submit_mod` module-level import;
  `tests/unit/test_cli_submit.py` added with focused unit tests for the new
  argparse / validation / exit-code / argv / output-contract / helper logic.
- **Specs**: `openspec/specs/cli-commands/spec.md` and
  `openspec/specs/package-facades/spec.md` modified.
- **Knowledge graph**: `docs/knowledge-graph.xml` — `M-CLI-COMMANDS` loses
  `<fn-submit>`; new `M-ENTRYPOINTS-CLI-SUBMIT` node + CrossLink added;
  `DF-SUBMIT` untouched.
- **Docs**: any references to the `yasubmit` command name only — unchanged.
- **Dependencies**: none added or removed.