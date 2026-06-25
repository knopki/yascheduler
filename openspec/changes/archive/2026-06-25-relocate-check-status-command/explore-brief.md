# Explore Brief — relocate-check-status-command

## Context

`yascheduler/infra/cli/check_status.py` (the `yastatus` command) is the 4th and
last execution-command resident to migrate into `entrypoints/cli/`. Precedents:
`relocate-init-command`, `relocate-show-nodes-command`, `relocate-submit-command`
(all archived 2026-06-24). The migration pattern is fully established (real
move, no compat shim, `entrypoints → infra` layer direction preserved, fresh
GRACE-lite markup, argparse reimplementation, `0/1/2` exit-code contract).

The AiiDA scheduler plugin (`entrypoints/aiida_plugin.py`) does NOT import
`check_status` — it shells out to the `yastatus` binary over SSH transport and
parses stdout via `_parse_joblist_output` (`job.split()` → expects 2 elements;
status must be a key of `_MAP_STATUS_YASCHEDULER`). This is the hard contract,
analogous to submit's `str(task_id)`.

## Alternatives Rejected

- **Compat shim at `infra/cli/check_status.py`** — rejected: inverts
  `import-linter` layer direction (`infra → entrypoints`); same reasoning as
  relocate-submit-command D1.
- **B-min for ssh_user bug** (only username) — rejected: leaves `-v` broken for
  jump-host cloud nodes. Going B-full (mirror `orchestrator:209-214`).
- **Carry `# FIXME: split adapter and application layer`** — rejected: stale
  framing at `entrypoints/` (not the adapter layer); in-module split resolves
  the concern. Precedent: relocate-submit-command D10.
- **Extract a `query_status` use case to `application/`** — rejected: YAGNI, no
  second consumer of the script/query logic (AiiDA client queries via
  `queue_get_tasks_async`, not via CLI; daemon does not query status).
- **Carry convergence into `--json`** — rejected: convergence requires SSH +
  SFTP download (expensive) + pycrystal parse; mixing machine-readable JSON with
  ephemeral scientific output is bad design. `--json` and `-o` are mutually
  exclusive via the `-v` mutex group.
- **Public `SSHMachineGateway.run_command(ip, cmd)`** — out of scope: the
  `_get_machine_state` FIXME is carried forward with updated framing (cross-
  cutting change, not a relocation concern).

## Decisions (all confirmed by user)

| ID | Decision |
|----|----------|
| A1 | `--json` object fields (9): `task_id`, `status`, `label`, `allocated_ip`, `port`, `cloud`, `engine`, `local_folder`, `remote_folder` |
| A2 | `--json` is a renderer selector, mutex with `-v`/`-i` |
| A3 | Convergence (`-o`) is NOT part of `--json`; `--json` and `-o` are mutually exclusive |
| A4 | Default filter (no `-j`) returns `RUNNING + TO_DO` (DONE excluded) — unchanged, AiiDA relies on it |
| A5 | `status` rendered as the enum name string (`"RUNNING"`, etc.) |
| B-full | Connection params bugfix mirrors `orchestrator._connect_machine_consumer:209-214`: `node.username` + `node.port` + `jump_host`/`jump_username` from the matching cloud. Duplicated (different shape from orchestrator), no shared helper (YAGNI). |
| C-validate | `-o` without `-v` → argparse `parser.error(...)` exit 2 (not silently ignored as today) |
| D-in | Happy-path `-v` unit test in scope (mock gateway); `-o`/pycrystal left to follow-up |
| E | AiiDA-contract regression golden test in scope |
| Q-mutex | `mutually_exclusive_group([-v/--view, -i/--info, --json])`; `-o/--convergence` is a dependency of `-v` (body-check, not in the mutex group since `-o -v` must remain valid) |
| Q-uow | Query/render separation: `tasks` (and `nodes_by_ip` when needed) fetched in one short UoW, closed before any SSH operation. No DB connection held during SSH. |

## Argparse Mechanics

- `mutually_exclusive_group`: `-v/--view`, `-i/--info`, `--json` (pick at most
  one; none = default AiiDA-compatible output).
- `-o/--convergence`: NOT in the mutex group (it modifies `-v`). Body-check
  after parse: `if args.convergence and not args.view: parser.error(...)`.
- `-j/--jobs`: orthogonal filter (nargs="*"), composes with any renderer.
- Order: argparse catches mutex violations first (exit 2); `-o`-requires-`-v`
  body-check runs second (exit 2).

## Nodes Lookup — Lazy

Default path (`_render_default`) and `-i` do NOT query nodes (only task fields).
Node lookup (`uow.nodes.get_by_ips`) only for `-v` and `--json` (which need
`port`/`cloud`). AiiDA invokes the default mode during polling — avoiding a
spurious extra `SELECT` matters. Query/render is still separated (Q-uow), but
the query phase is conditional on the renderer.

## Cross-Module Data Flows

- `yastatus` (no flags): `M-ENTRYPOINTS-CLI-CHECK-STATUS → M-DI (make_cli_deps)
  → M-APPLICATION-UOW → M-DOMAIN-MODEL (Task, TaskStatus)` — pure DB read,
  AiiDA-compatible output.
- `yastatus -v`: additionally `→ M-SSH-GATEWAY (connect, run_full, sftp,
  disconnect)` — long-lived SSH, UoW closed beforehand.
- `yastatus --json`: same as default DB path + `uow.nodes.get_by_ips` for
  `port`/`cloud`.
- AiiDA plugin (`entrypoints/aiida_plugin.py`) is unchanged: still shells out to
  `yastatus [--jobs ...]` and parses the default `<task_id>   <STATUS>` output.

## Open Questions

None. All resolved during explore.
