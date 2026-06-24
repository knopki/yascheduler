## 1. New module: entrypoints/cli/submit.py

- [x] 1.1 Create `yascheduler/entrypoints/cli/submit.py` with fresh GRACE-lite markup (FILE, VERSION, MODULE_CONTRACT with PURPOSE/SCOPE/DEPENDS/LINKS, MODULE_MAP, CHANGE_SUMMARY)
- [x] 1.2 Add `_existing_path(s: str) -> Path` — returns `Path(s)` if `.is_file()` else raises `argparse.ArgumentTypeError(f"not a file: {s}")` (START_CONTRACT + block anchors)
- [x] 1.3 Add `_parse_submit_args(argv: list[str] | None) -> argparse.Namespace` — `ArgumentParser(prog="yasubmit", description="Submit task to yascheduler via AiiDA script")`, positional `script` with `type=_existing_path`, `parser.parse_args(argv)` (START_CONTRACT)
- [x] 1.4 Move `_parse_script_metadata(script_text: str) -> dict[str, str]` as-is from `infra/cli/submit.py` (key=value parsing, malformed lines ignored via try/except ValueError: pass) (START_CONTRACT)
- [x] 1.5 Move `_read_input_files(engine, local_folder) -> dict[str, str]` as-is, preserving the `UnicodeDecodeError → base64` fallback (START_CONTRACT)
- [x] 1.6 Add `_build_metadata(script_params, config, local_folder) -> dict[str, Any]` — sets `local_folder`, merges `_read_input_files(engine, local_folder)` results, and when `"PARENT" in script_params and config.local.webhook_url` adds `webhook_url` + `webhook_custom_params = {"parent": script_params["PARENT"]}` (START_CONTRACT + START_BLOCK_BUILD_METADATA / END_BLOCK_BUILD_METADATA)
- [x] 1.7 Implement `submit(argv: list[str] | None = None) -> None` decorated with `@to_sync`: parse args → `Config.from_config_parser(CONFIG_FILE)` → `make_cli_deps(config)` → read script text → `_parse_script_metadata` → validate ENGINE present (raise ValueError on missing → exit 1) → `config.engines.get(engine_name)` (raise ValueError on None → exit 1) → `_build_metadata` → `await deps.submit(label, dict(metadata), engine.name)` → `print(str(task_id))` (implicit exit 0); wrap body in `try/except Exception as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)` (START_CONTRACT: submit + START_BLOCK_PARSE_ARGS / END_BLOCK_PARSE_ARGS, START_BLOCK_CONFIGURE / END_BLOCK_CONFIGURE, START_BLOCK_VALIDATE_CONTENT / END_BLOCK_VALIDATE_CONTENT, START_BLOCK_SUBMIT / END_BLOCK_SUBMIT, START_BLOCK_HANDLE_FAILURE / END_BLOCK_HANDLE_FAILURE)
- [x] 1.8 Do NOT carry the `# FIXME: split adapter and application layer` comment to the new file

## 2. Remove old module + update infra/cli facade

- [x] 2.1 Delete `yascheduler/infra/cli/submit.py`
- [x] 2.2 Update `yascheduler/infra/cli/__init__.py`: drop the `from .submit import submit` line, drop `"submit"` from `__all__`, drop the `submit - Re-exported from .submit` line from MODULE_MAP; update the SCOPE line to drop `submit` from the re-export count (5 → 4); bump VERSION (read the current value first — it's post-show_nodes state) and add a CHANGE_SUMMARY entry referencing relocate-submit-command. Line numbers are not pinned: read the current file state (post-show_nodes) before editing
- [x] 2.3 Update `yascheduler/entrypoints/cli/__init__.py`: declarative PURPOSE edit to add `submit` (e.g. "init, show_nodes, submit CLI entry points" or a generic "relocated CLI entry points"); keep SCOPE as "no re-exports" (submit is invoked by console_script, not imported across layers); bump VERSION; CHANGE_SUMMARY entry

## 3. pyproject.toml

- [x] 3.1 Update `pyproject.toml` line 54: `yasubmit = "yascheduler.entrypoints.cli.submit:submit"`

## 4. Knowledge graph

- [x] 4.1 In `docs/knowledge-graph.xml` under `M-CLI-COMMANDS`, delete the `<fn-submit PURPOSE="Submit task via AiiDA script (infra/cli/submit.py)" />` annotation
- [x] 4.2 Add new module node `M-ENTRYPOINTS-CLI-SUBMIT` (TYPE="ENTRY_POINT", STATUS="implemented"): `<purpose>yasubmit CLI command — parse AiiDA script, submit task via DI</purpose>`, `<path>yascheduler/entrypoints/cli/submit.py</path>`, `<depends>M-DI, M-CONFIG, M-SHARED</depends>`, `<annotations>` with `<fn-submit PURPOSE="Submit task via AiiDA script" />`, `<fn-_parse_script_metadata PURPOSE="Parse key=value pairs from script text" />`, `<fn-_read_input_files PURPOSE="Read engine input files from disk" />`, `<fn-_build_metadata PURPOSE="Assemble task metadata dict with webhook branch" />`, `<fn-_parse_submit_args PURPOSE="argparse → Namespace" />`, `<fn-_existing_path PURPOSE="argparse type validator for existing file paths" />`
- [x] 4.3 Add `<CrossLink from="M-ENTRYPOINTS-CLI-SUBMIT" to="M-DI" relation="uses make_cli_deps for CLI submit" />`
- [x] 4.4 Amend (do NOT delete) the existing `<CrossLink from="M-CLI-COMMANDS" to="M-DI" relation="uses make_cli_deps for CLI submit; make_daemon for daemon entry" />` — change the `relation` attribute to drop only the "CLI submit" clause, leaving `relation="uses make_daemon for daemon entry"` (daemonize still remains in infra/cli and still uses M-DI via M-CLI-COMMANDS)
- [x] 4.5 Do NOT modify `DF-SUBMIT` (the existing data-flow element describing the client API path is untouched — the CLI path is visible via the new M-ENTRYPOINTS-CLI-SUBMIT node + CrossLink)

## 5. Spec deltas

- [x] 5.1 `openspec/changes/relocate-submit-command/specs/cli-commands/spec.md` is written (MODIFIED "CLI commands call use cases via DI"; ADDED "yasubmit parses AiiDA script and submits task", "yasubmit parses flags via argparse", "yasubmit validates script content in the body", "yasubmit exit code contract", "yasubmit preserves AiiDA stdout compatibility"; MODIFIED "Entry points updated" to include yasubmit + counter 4→3). Verify it is consistent with the frozen design (D1–D13)
- [x] 5.2 `openspec/changes/relocate-submit-command/specs/package-facades/spec.md` is written (MODIFIED "Within-package relative imports (R1)" — drop `submit` from the infra/cli submodule list, post-state is `check_status, daemonize, manage_node`; update entrypoints/cli scenario to note show_nodes AND submit are NOT re-exported). Verify it targets the post-show_nodes state

## 6. Tests

- [x] 6.1 Delete `tests/unit/test_cli_smoke.py::test_submit_function_exists` (the low-value smoke test checking existence + @to_sync)
- [x] 6.2 Delete the `TestSubmit` class (lines 121-210) and the `submit_mod = importlib.import_module("yascheduler.infra.cli.submit")` line (line 38) from `tests/unit/test_cli_behavioral.py`
- [x] 6.3 Create `tests/unit/test_cli_submit.py` with fresh GRACE-lite markup (MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY), `pytest.mark.unit` marks, mirroring the shape of `tests/unit/test_cli_init.py` / `tests/unit/test_cli_show_nodes.py`
- [x] 6.4 Add argparse tests: `--help` exits 0 and shows `prog="yasubmit"`; no-args → exit 2; non-existent file via `type=_existing_path` → exit 2 + clean argparse message; extra positional → exit 2; unknown flag → exit 2
- [x] 6.5 Add happy-path tests: valid script + known engine + input file present → `stdout == str(task_id)`, `deps.submit` called once with correct label / metadata / engine_name, exit 0
- [x] 6.6 Add content-validation tests: ENGINE key missing → exit 1 + stderr `Error: Script has not defined an engine` + stdout empty; engine name unknown → exit 1 + stderr `Error: Engine {name} is not supported` + stdout empty
- [x] 6.7 Add webhook-branch tests for `_build_metadata`: PARENT present + `config.local.webhook_url` set → metadata contains `webhook_url` + `webhook_custom_params == {"parent": ...}`; PARENT absent → no webhook keys; PARENT present but `webhook_url is None` → no webhook keys
- [x] 6.8 Add helper tests: `_parse_script_metadata` (key=value lines, malformed lines ignored, empty input); `_read_input_files` (utf-8 → text, binary → base64 fallback); `_build_metadata` (local_folder always present, input files merged, webhook branch)
- [x] 6.9 Add exit-code tests: success → exit 0; DB error / config error / unexpected exception → exit 1 + stderr `Error: ...`; argparse errors → exit 2
- [x] 6.10 Add argv-injection tests: `submit(["script.in"])` works without `patch("sys.argv", ...)` — pass an explicit argv list; verify no global-state coupling

## 7. Verification

- [x] 7.1 Run `uv run pytest -m unit` — all unit tests pass (new test_cli_submit.py + existing tests unaffected)
- [x] 7.2 Run `uv run ruff check .` — no lint errors in the new/modified files
- [x] 7.3 Run `uv run ruff format --check .` — formatting passes
- [x] 7.4 Run `uv run lint-imports` — import-linter `layers` + `forbidden` contracts stay green (no new violations; the `infra → entrypoints` re-export is gone, so no layer-direction concern)
- [x] 7.5 Run `uv run zuban check` — static analysis passes
- [x] 7.6 Run `python3 scripts/grace_check.py` — GRACE-lite validation passes (new module has valid MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY/contracts/blocks; updated infra/cli/__init__.py and entrypoints/cli/__init__.py pass; knowledge-graph.xml is well-formed)
- [x] 7.7 Run `openspec validate --all --json` — spec validation passes (cli-commands and package-facades deltas are well-formed)
- [x] 7.8 Verify `yasubmit --help` from a re-installed package shows `prog="yasubmit"` and the `script` positional argument (manual smoke or via a unit test asserting the help screen)