## Why

`yasetnode` (`manage_node`) lives at `yascheduler/infra/cli/manage_node.py` but is
an entrypoint (a CLI command invoked by `console_script`), not an infra adapter.
The archived `add-entrypoints-layer` change listed `infra/cli/` as deferred-for-
migration; `relocate-init-command`, `relocate-show-nodes-command`, and
`relocate-submit-command` then moved three of the six CLI commands into
`yascheduler/entrypoints/cli/` as residents, establishing the relocation pattern
(real move, no compat shim, layer direction `entrypoints → infra` preserved,
fresh GRACE-lite markup, argparse-based reimplemented logic, `0`/`1`/`2`
exit-code contract). `manage_node` is the 4th resident and follows the same
pattern; `check_status` and `daemonize` remain in `infra/cli/` for follow-up
changes.

The current `manage_node()` also has real bugs and issues worth fixing in the
same move:

1. **Silent IPv6 data corruption.** `manage_node ::1` parses as `host="::"`,
   `port=1` (the `rsplit(":", 1)` splits at the last colon). The wrong host is
   written to the DB with no error. `manage_node [::1]:22` raises an uncaught
   `ValueError` traceback on `int("1]")`.
2. **`type=bool nargs="?"` argparse footgun.** `--skip-setup false` activates
   skip-setup, because `bool("false") is True`. Same for `--remove-soft false`
   and `--remove-hard false`.
3. **`--remove-soft --remove-hard` silently picks hard** (the `if/elif`),
   ignoring `--remove-soft`. The two flags are not in a `mutually_exclusive_group`.
4. **No exit-code contract.** Uncaught exceptions (SSH connect failure,
   `int("abc")` for port/ncpus, multi-`@`/multi-`~` unpack errors) produce
   Python tracebacks with the default uncaught-exception exit code.
5. **No `argv` testability parameter.** Tests must `patch("sys.argv", ...)`
   (fragile global-state coupling).
6. **No `prog="yasetnode"`.** `--help`/error screens show the binary path, not
   the command name.
7. **Resource leak.** `_add_node` constructs `SSHMachineGateway()`, calls
   `connect`, then `setup_node`/`nodes.add`. If any step after `connect`
   raises, `gateway.disconnect(host)` never runs (the SSH connection hangs
   until timeout).
8. **`already_there` and not-in-DB branches `return False`** (process exits 0)
   even though the requested action was not performed.
9. **Host-port-ncpus validation mixed with orchestration** — no validation of
   port range (`99999` accepted), ncpus sign (`-5` accepted), or empty
   segments (`host:` raises `int("")`).
10. **Stale description** — argparse `description="Add nodes to yascheduler
    daemon"` does not mention removal.
11. **Stale `# FIXME: split adapter and application layer`** — its framing is
    wrong at the new home (`entrypoints/` is not the adapter layer); the
    in-module function split resolves the logic-vs-IO separation at the
    appropriate granularity (functions, not layers). Same call as
    `relocate-submit-command` D13.

## What Changes

- Move `yascheduler/infra/cli/manage_node.py` →
  `yascheduler/entrypoints/cli/manage_node.py` (real implementation, not a
  shim). This is the 4th resident of `entrypoints/cli/`, mirroring `init.py`,
  `show_nodes.py`, and `submit.py`. The other 2 execution commands
  (`check_status`, `daemonize`) stay in `infra/cli/` for follow-up changes.
- Delete `yascheduler/infra/cli/manage_node.py`. Drop
  `from .manage_node import manage_node` and `"manage_node"` from `__all__`
  in `yascheduler/infra/cli/__init__.py`; drop the
  `manage_node - Re-exported from .manage_node` line from its `MODULE_MAP`. No
  compat shim: any `infra → entrypoints` re-export would invert the layer
  direction enforced by `import-linter` (same reasoning as
  `relocate-submit-command` D1).
- Update `pyproject.toml` line 52:
  `yasetnode = "yascheduler.entrypoints.cli.manage_node:manage_node"`.
- Reimplement `manage_node()` with `argparse`:
  - `prog="yasetnode"` passed to `ArgumentParser` so `--help` and error
    screens show the command name (mirrors `init`'s `prog="yainit"`,
    `show_nodes`'s `prog="yanodes"`, `submit`'s `prog="yasubmit"`).
  - Updated `description="Add or remove nodes from the yascheduler daemon"`
    (replaces the misleading "Add nodes…" text).
  - One positional `host` with `type=_parse_host_spec`, where
    `_parse_host_spec(s)` is a local callable returning a frozen `HostSpec`
    dataclass. The grammar is `[user@]host[:port][~ncpus]` where `host` is
    either an IPv4 literal or a bracketed IPv6 literal `[...]`. This places
    argument-*shape* validation (host grammar, port range, ncpus sign) at the
    argparse layer (exit 2), not in the body (exit 1). Mirrors the
    argparse-layer / body-layer validation split established by `submit`'s
    `type=_existing_path`.
  - `argv: list[str] | None = None` parameter passed through to
    `parser.parse_args(argv)`. The `argv=None` default means the
    console_script entrypoint reads `sys.argv` (standard argparse
    convention); tests pass an explicit list. Mirrors `init`, `show_nodes`,
    `submit`.
  - `--help` shows the standard argparse help screen (argparse default).
- Argparse flag fixes (welcome behavior changes on previously-buggy paths):
  - `--skip-setup`, `--remove-soft`, `--remove-hard` all use
    `action="store_true"` (replaces the buggy `nargs="?", type=bool,
    const=True` pattern). **BREAKING** for anyone passing
    `--skip-setup VALUE` / `--remove-soft VALUE` / `--remove-hard VALUE`
    (undocumented; previously activated the flag for any non-empty value
    including `"false"`). After this change, the value form exits `2`.
  - `--remove-soft` and `--remove-hard` placed in a
    `mutually_exclusive_group`: passing both exits `2` (was: silently picked
    hard).
  - `--skip-setup` is valid only on the add path. A body-level check after
    `parse_args` calls `parser.error(...)` if
    `skip_setup and (remove_soft or remove_hard)`, producing exit `2`
    (was: silently ignored on the remove path).
- Exit code contract (mirrors `relocate-init-command` D3,
  `relocate-show-nodes-command` D5, `relocate-submit-command`):
  - `0` on success (normal completion, success messages to stdout).
  - `1` on runtime failure: host already in DB (on add), host NOT in DB (on
    remove), SSH failure, DB error, config parse error, or any unexpected
    exception caught at the top level. The error SHALL be printed to stderr
    as `Error: <error>` and the process SHALL exit `1`. **BREAKING** for
    callers relying on exit `0` for the already-in-DB / not-in-DB paths
    (previously `return False` → process exit `0`).
  - `2` on argparse error (argparse default — missing host, malformed host
    grammar via `type=_parse_host_spec`, port out of `1..65535`, negative
    ncpus, `--remove-soft --remove-hard`, `--skip-setup --remove-*`, unknown
    flag).
- Output channel discipline:
  - Success messages print to **stdout**, **after** `uow.commit()`
    (currently some print before commit, so a commit failure rolls back the
    DB while the user has already seen success text). Verbatim text
    preserved: `"Setup host..."`, `"Added host to yascheduler: {host}:{port}"`,
    `"An associated task {task_id} at {host} is now marked done!"`,
    `"Removed host from yascheduler: {host}"`,
    `"A task associated, prevent from assigning the new tasks"`,
    `"Prevented from assigning the new tasks: {host}"`,
    `"No tasks associated, remove node immediately"`.
  - Failure messages print to **stderr** as `Error: <message>` via `raise` +
    top-level `except Exception as e: print(f"Error: {e}", file=sys.stderr);
    sys.exit(1)`. **BREAKING** for callers parsing failure text from stdout
    (verified: no in-repo consumer; the messages had no documented contract).
- Logging setup adopted from `submit`:
  `logging.captureWarnings(True)` + `log.setLevel(logging.WARN)` so config
  warnings (`warn_unknown_fields`) reach the operator.
- Resource leak fix: `_add_node` wraps the gateway connect/setup/add sequence
  in `try/finally` so `gateway.disconnect(host)` runs on any failure.
- Gateway instantiation moved: `SSHMachineGateway()` is constructed at the top
  of `manage_node` and passed as a parameter to `_add_node` (symmetric with
  how `uow` is passed down; makes `_add_node` unit-testable via direct mock
  injection, no `patch.object` on the class). As in the three predecessors,
  `manage_node()` obtains `Config` via `Config.from_config_parser(CONFIG_FILE)`
  and builds `CLIDeps` via `make_cli_deps(config)`, then opens the UoW via
  `async with deps.uow_factory() as uow:`.
- Helper return types normalized: `_remove_node_hard`, `_remove_node_soft`,
  `_add_node` all return `None` (currently some return `bool`). Exit codes
  replace the return-value signaling.
- Split the logic into private pure functions in the new module:
  - `_parse_host_spec(s) -> HostSpec` (argparse type; grammar + range
    validation, raises `ArgumentTypeError`).
  - `_parse_node_args(argv) -> argparse.Namespace` (parser construction +
    `parse_args`; includes the `skip_setup × remove` body check calling
    `parser.error`).
  - `_remove_node_hard(uow, spec) -> None`.
  - `_remove_node_soft(uow, spec) -> None`.
  - `_add_node(uow, gateway, spec, config, skip_setup) -> None` (wraps
    connect/setup/add/disconnect in `try/finally`).
  - `HostSpec` — frozen dataclass with `host: str`, `username: str | None`,
    `port: int`, `ncpus: int | None`.
  - Do NOT extract a `manage_node` use case into `application/` — YAGNI: the
    orchestrator owns the daemon-side node lifecycle; `yasetnode` is the
    only operator-side ad-hoc node-management entry point. The contract
    records that promotion to `application/` awaits a second consumer.
- Do NOT carry the `# FIXME: split adapter and application layer` comment to
  the new file (same reasoning as `relocate-submit-command` D13).
- Fresh GRACE-lite markup at the new path: `MODULE_CONTRACT`, `MODULE_MAP`,
  `CHANGE_SUMMARY`, function contracts, and block anchors appropriate to the
  reimplemented logic. The `entrypoints/cli/__init__.py` facade gets a
  declarative PURPOSE edit to add `manage_node` (it currently mentions
  "init, show_nodes, and submit"; generalize to include `manage_node`).
- Update `openspec/specs/package-facades/spec.md` line 101: drop
  `manage_node` from the R1 example listing `infra/cli/__init__.py`
  submodules. Pre-state: `check_status`, `daemonize`, `manage_node` →
  post-state: `check_status`, `daemonize`.
- Update `openspec/specs/cli-commands/spec.md`:
  - Add a new `yasetnode` requirement block covering: module path
    (`entrypoints/cli/manage_node.py`), `prog="yasetnode"`, the `argv`
    testability parameter, the `type=_parse_host_spec` grammar (incl.
    mandatory bracketed IPv6), the `store_true` flags, the
    `mutually_exclusive_group` for `--remove-soft`/`--remove-hard`, the
    body-level `--skip-setup × remove` check (exit 2), the exit-code
    contract (`0`/`1`/`2`), the output-channel discipline (stdout success
    after commit, stderr `Error: …` failure), the verbatim success-message
    list, the `try/finally` gateway disconnect, and the in-module function
    split.
  - Decrement the "other N CLI commands remain in `infra/cli/`" counter from
    "other 3" (`check_status`, `manage_node`, `daemonize`) to "other 2"
    (`check_status`, `daemonize`).
- Update `docs/knowledge-graph.xml`:
  - `M-CLI-COMMANDS`: delete the `<fn-manage_node>` annotation; drop
    `M-SSH-GATEWAY` and `M-APPLICATION-UOW` from `<depends>` if they are
    there only for `manage_node` (verify against remaining residents
    `check_status` and `daemonize` — `check_status` still depends on
    `M-SSH-GATEWAY`, so both stay).
  - Add a new module node `M-ENTRYPOINTS-CLI-MANAGE-NODE`
    (`path: yascheduler/entrypoints/cli/manage_node.py`, `depends: M-CONFIG,
    M-DI, M-DOMAIN-MODEL, M-SSH-GATEWAY, M-SHARED, M-APPLICATION-UOW`).
  - Add `CrossLink from="M-ENTRYPOINTS-CLI-MANAGE-NODE" to="M-DI"
    relation="uses make_cli_deps for CLI manage_node"`. The existing
    `<CrossLink from="M-CLI-COMMANDS" to="M-DI" relation="uses make_daemon
    for daemon entry" />` covers daemon only (the `CLI submit` clause was
    already dropped by the archived `relocate-submit-command`); this change
    does NOT amend it (the `manage_node` clause was never in that relation
    string).
- Tests:
  - Delete `tests/unit/test_cli_smoke.py::test_manage_node_function_exists`
    (low-value smoke test that only checks the function exists and is
    `@to_sync`-decorated — replaced by real unit tests, same as the three
    predecessors did).
  - Delete the `TestManageNode` class from
    `tests/unit/test_cli_behavioral.py` (moved to a dedicated file); drop
    the `manage_node_mod` module-level import; bump the file's
    `MODULE_CONTRACT` SCOPE and `CHANGE_SUMMARY`.
  - Add `tests/unit/test_cli_manage_node.py` with focused unit tests
    covering: argparse (`prog="yasetnode"`, `--help`, missing host → exit 2,
    unknown flag → exit 2, `--remove-soft --remove-hard` → exit 2,
    `--skip-setup --remove-*` → exit 2); `_parse_host_spec` (plain IPv4,
    `user@`, `:port`, `~ncpus`, all combined, bracketed IPv6, IPv6 without
    brackets → exit 2, port out of range → exit 2, negative ncpus → exit 2,
    `~0` → `ncpus is None`, multi-`@`/multi-`~` → exit 2, empty segments →
    exit 2, default port `22` when absent, default username `None` when
    absent); add happy path (gateway wired correctly, setup skipped when
    `--skip-setup`, `gateway.disconnect` called, `nodes.add` called with
    correct `Node`, `commit` called, `"Added host"` printed after commit);
    add resource-leak fix (`gateway.disconnect` called when `setup_node`
    raises); add-already-in-DB (exit 1, `Error:` on stderr, no `nodes.add`);
    remove-hard happy path (tasks marked `DONE`, `nodes.remove`, `commit`,
    per-task prints after commit); remove-soft with tasks (`nodes.disable`
    called, `nodes.remove` NOT called); remove-soft without tasks
    (`nodes.remove` called, `nodes.disable` NOT called); remove-nonexistent
    (exit 1, stderr message); exit codes (0 success, 1 runtime failure, 2
    argparse); `argv` injection (no `patch sys.argv` needed). Mark with
    `pytest.mark.unit`.

### Out of scope (explicit, deferred to follow-up changes)

- The other 2 CLI commands (`check_status`, `daemonize`) remain in
  `yascheduler/infra/cli/`; their migration into `entrypoints/cli/` is
  tracked separately. `check_status` has its own latent issues
  (`type=bool nargs="?"` flag bug, `_get_machine_state` private-method
  access, in-function `pycrystal`/`numpy` import) — those are its own
  follow-up.
- No new `application/manage_node.py` use case (YAGNI — no second consumer).
- No multi-host add (`yasetnode` takes exactly one host positional; adding
  multiple is a feature, out of scope).
- No `[remote] user` decoupling (the config-driven username default is
  preserved; parser returns `None`, `manage_node` applies
  `config.remote.username`).
- No `--re-enable` flag for disabled nodes (status quo: remove + add cycle,
  per maintainer decision).
- No new dependencies — stdlib only (`argparse`, `dataclasses`, `logging`,
  `sys`).
- `schema-migrations` (in progress) — unaffected; `yasetnode` touches no
  schema, only node records and (on hard-remove) task status.
- `di.py`, `application/`, `domain/`, `infra/persistence/`,
  `infra/ssh/gateway.py` — unchanged.

## Capabilities

### New Capabilities

_None._ The relocation and reimplementation are structural/operational
concerns for an existing command. No new spec capability is introduced:
`yasetnode` already exists under `cli-commands`, and its requirements are
modified (below) rather than replaced.

### Modified Capabilities

- `cli-commands`: the `yasetnode` command gains a new module path
  (`entrypoints/cli/manage_node.py`), `prog="yasetnode"`, the
  `argv: list[str] | None = None` testability parameter, the
  `type=_parse_host_spec` host grammar (incl. mandatory bracketed IPv6,
  port range `1..65535`, ncpus `>= 0`), `store_true` flags, the
  `mutually_exclusive_group` for `--remove-soft`/`--remove-hard`, the
  body-level `--skip-setup × remove` check (exit 2), the `0`/`1`/`2`
  exit-code contract, the output-channel discipline (stdout success after
  commit, stderr `Error: …` failure), the verbatim success-message list,
  the `try/finally` gateway disconnect, the in-module function split, the
  logging setup, and the `HostSpec` dataclass. The "other N CLI commands
  remain in `infra/cli/`" counter decrements (3 → 2).
- `package-facades`: the R1 example listing `infra/cli/__init__.py`
  submodules drops `manage_node` (it has moved to `entrypoints/cli/`). No
  layer-direction or facade-content requirement changes.

## Impact

- **Code**: `yascheduler/entrypoints/cli/manage_node.py` (1 new file);
  `yascheduler/infra/cli/manage_node.py` removed;
  `yascheduler/infra/cli/__init__.py` loses the `manage_node` re-export +
  `__all__` entry + `MODULE_MAP` line (bump VERSION, CHANGE_SUMMARY);
  `yascheduler/entrypoints/cli/__init__.py` gets a declarative PURPOSE edit.
- **CLI**: `yasetnode` behavior — `--help` works; the documented host
  syntax `user@host:port~ncpus` is preserved (success path unchanged);
  bracketed IPv6 `[::1]` and `[::1]:22` now work (were: silent corruption /
  traceback); malformed hosts exit `2` with a clean argparse message;
  `--remove-soft --remove-hard` and `--skip-setup --remove-*` exit `2`;
  add-already-in-DB and remove-nonexistent exit `1` with a stderr message;
  SSH/DB failures print `Error: …` to stderr and exit `1` instead of a
  traceback; success messages still print to stdout (now after commit). No
  **BREAKING** change to the command name, the documented host syntax, or
  the success invocation; the AiiDA scheduler plugin is unaffected
  (`yasetnode` has no machine consumer).
- **Config**: `pyproject.toml` line 52 (console_script target) updated.
  `[tool.importlinter]` unchanged.
- **Tests**: `tests/unit/test_cli_smoke.py` loses one test method;
  `tests/unit/test_cli_behavioral.py` loses the `TestManageNode` class and
  the `manage_node_mod` module-level import;
  `tests/unit/test_cli_manage_node.py` added with focused unit tests for the
  new argparse / grammar / validation / exit-code / `argv` /
  output-contract / resource-leak / helper logic.
- **Specs**: `openspec/specs/cli-commands/spec.md` and
  `openspec/specs/package-facades/spec.md` modified.
- **Knowledge graph**: `docs/knowledge-graph.xml` — `M-CLI-COMMANDS` loses
  `<fn-manage_node>`; new `M-ENTRYPOINTS-CLI-MANAGE-NODE` node + CrossLink
  added.
- **Docs**: no references to update (the `yasetnode` command name is
  unchanged; the documented host syntax forms are preserved).
- **Dependencies**: none added or removed.
