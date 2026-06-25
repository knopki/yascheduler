# Explore Brief — relocate-manage-node-command

## Context

`yasetnode` (`manage_node`) lives at `yascheduler/infra/cli/manage_node.py` but is
an entrypoint (CLI command invoked by `console_script`), not an infra adapter.
Three predecessors established a repeatable relocation pattern:
`relocate-init-command`, `relocate-show-nodes-command`, `relocate-submit-command`
(all archived). `manage_node` is the 4th resident of `entrypoints/cli/`;
`check_status` and `daemonize` stay for follow-up changes.

## Rejected Alternatives

- **Compat shim re-exporting `manage_node` from `infra/cli/`** — rejected: any
  `infra → entrypoints` re-export inverts the layer direction enforced by
  `import-linter` (same call as in relocate-submit-command D1).
- **Inline host parsing kept in the body, wrapped in try/except** — rejected:
  the host grammar is syntactic shape, belongs at the argparse layer (mirrors
  submit's `_existing_path` precedent). Inline parsing leaves validation mixed
  with orchestration.
- **IPv6 without brackets** — rejected: ambiguous against `:port` suffix
  (`::1:22` is unparseable). Brackets `[::1]` (URL-style) disambiguate.
- **Hardcode `username="root"` in parser** — rejected: breaks deployments with
  `[remote] user = xyz`. Parser returns `username=None`; `manage_node` resolves
  from `config.remote.username` (preserves current behavior).
- **Add `--re-enable` flag for disabled nodes** — rejected: status quo (remove
  + add cycle) is intentional per maintainer decision.
- **Keep `type=bool nargs="?"` for flags** — rejected: classic argparse footgun
  (`--skip-setup false` activates it via `bool("false") == True`).
- **`--skip-setup` silently ignored on remove path** — rejected: invalid
  combinations should surface as argparse errors (exit 2).

## Final Approach — Full Mapping Tables

### Host grammar

```
[user@]host[:port][~ncpus]

host  := ipv4-literal | "[" ipv6-literal "]"
user  := non-empty string without "@"
port  := integer 1..65535 (default 22, applied by parser)
ncpus := integer >= 0       (0 and absent both map to None = unlimited)
```

Parser-applied defaults: `port=22`, `ncpus=None`.
Config-resolved default: `username` left `None`, `manage_node` substitutes
`config.remote.username`.

### HostSpec (frozen dataclass)

| field    | type           | source                       |
| -------- | -------------- | ---------------------------- |
| `host`   | `str`          | parsed, non-empty            |
| `username` | `str \| None` | `None` if no `user@`         |
| `port`   | `int`          | parsed or `22`               |
| `ncpus`  | `int \| None`  | parsed-or-0 → `None`; positive int as-is |

### Argparse shape

| flag               | action          | group        | notes                                  |
| ------------------ | --------------- | ------------ | -------------------------------------- |
| `host` (positional)| `type=_parse_host_spec` | —      | required; malformed → exit 2           |
| `--skip-setup`     | `store_true`    | —            | mutex-with-remove enforced in body     |
| `--remove-soft`    | `store_true`    | mutex pair   | `mutually_exclusive_group` with hard   |
| `--remove-hard`    | `store_true`    | mutex pair   | `mutually_exclusive_group` with soft   |

Body check after `parse_args`: `skip_setup and (remove_soft or remove_hard)` →
`parser.error(...)` → exit 2.

### Exit-code contract (0/1/2)

| path                                | stdout         | stderr           | exit |
| ----------------------------------- | -------------- | ---------------- | ---- |
| add success                         | success msgs   | —                | 0    |
| remove-hard/soft success            | success msgs   | —                | 0    |
| host already in DB (on add)         | —              | `Error: ...`     | 1    |
| host NOT in DB (on remove)          | —              | `Error: ...`     | 1    |
| runtime failure (DB/SSH/uncaught)   | —              | `Error: ...`     | 1    |
| argparse error (shape/grammar/mutex)| —              | argparse usage   | 2    |
| `--help`                            | help screen    | —                | 0    |

### Message preservation (success path, verbatim, in stdout, AFTER commit)

- `"Setup host..."`
- `"Added host to yascheduler: {host}:{port}"`
- `"An associated task {task_id} at {host} is now marked done!"`
- `"Removed host from yascheduler: {host}"`
- `"A task associated, prevent from assigning the new tasks"`
- `"Prevented from assigning the new tasks: {host}"`
- `"No tasks associated, remove node immediately"`

Failure-path messages: uniform `Error: <message>` via `raise` + top-level
`except Exception as e: print(f"Error: {e}", file=sys.stderr); sys.exit(1)`.

## Cross-Module Data Flows

```
console_script (pyproject.toml)
  → yascheduler.entrypoints.cli.manage_node:manage_node(argv=None)
      → _parse_node_args(argv)         # argparse + _parse_host_spec
      → Config.from_config_parser(...)  # config.remote.username fallback
      → make_cli_deps(config)          # CLIDeps.uow_factory
      → SSHMachineGateway()            # constructed here, passed down
      async with deps.uow_factory() as uow:
          already_there = await uow.nodes.get(spec.host) is not None
          branch on already_there × remove flags:
            add:           _add_node(uow, gateway, spec, config, skip_setup)
            remove-hard:   _remove_node_hard(uow, spec)
            remove-soft:   _remove_node_soft(uow, spec)
      → top-level try/except → "Error: ..." / sys.exit(1)
```

`_add_node` body wraps connect/setup in `try/finally` so `gateway.disconnect`
runs on any failure (fixes current resource leak).

## Behavior Changes (on previously-buggy/undocumented paths)

1. `--skip-setup VALUE` form removed → exit 2 (was: `bool(VALUE)` activated it).
2. `--remove-soft --remove-hard` → exit 2 (was: hard won silently).
3. `--skip-setup --remove-*` → exit 2 (was: silently ignored).
4. add-already-in-DB / remove-nonexistent → exit 1 (was: exit 0 via `return False`).
5. malformed host (IPv6 without brackets, multi-`@`, multi-`~`, empty segments,
   port out of `1..65535`, negative ncpus) → exit 2 (was: uncaught traceback).
6. uncaught runtime exceptions → `Error: ...` exit 1 (was: traceback).
7. failure messages → stderr (was: stdout).
8. `--help` shows `prog="yasetnode"` (was: binary path).

Public interface preserved: command name, documented host syntax forms
(`user@host:port~ncpus` with bracketed IPv6), all success messages, exit 0 on
success.

## Open Questions

None. All closed during explore (decisions logged in conversation):
- IPv6 in brackets — mandatory
- `~0` → `None` (unlimited)
- disabled node reactivation — remove+add cycle (status quo)
- gateway leak — fix with try/finally
- error message format — uniform `Error: ...` via raise + catch
- argparse description — mention remove
- validate ranges — port `1..65535`, ncpus `>= 0`
- success messages — verbatim, after commit
- username default — config-driven (parser returns `None`)
- `--skip-setup` + remove combo — exit 2 via `parser.error(...)`
- logging setup — adopt submit's `captureWarnings(True)` + WARN level
- `test_cli_behavioral.py` — leave as-is (drop only `TestManageNode`)
