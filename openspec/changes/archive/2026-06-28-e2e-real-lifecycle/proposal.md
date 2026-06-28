## Why

`tests/e2e/test_full_cycle.py` passes green while exercising none of the application's
real entrypoint code paths. It manually calls `SSHMachineRepository.connect`,
`uow.nodes.add`, `CLIDeps.submit`, `uow.nodes.remove` — bypassing `yasetnode`,
`yasubmit`, and the daemon lifecycle. A green test does not prove the application
works in even the simplest happy path: a regression in argparse parsing, INI
loading, `setup_node`, `submit_task` input-file handling, or the
soft-remove branch would not be caught. The test also uses a single node, so
multi-machine scheduling — the core purpose of yascheduler — is unverified.

## What Changes

- Rewrite `tests/e2e/test_full_cycle.py` to drive the full lifecycle through the
  internal async entrypoint functions (`_submit_async`, `_manage_node_async`)
  instead of bypassing them with direct repository/UoW calls. The sync wrappers
  (`submit()`, `manage_node()`) are skipped only because they call `asyncio.run`,
  which cannot run inside the test's already-running event loop.
- Start the daemon via `make_daemon(config)` + `asyncio.create_task(orch.start())`
  (already the production path used by `run_daemon`, minus signal-handler
  registration which is undesirable in a test loop).
- Use two SSH containers (one shared keypair) so the test exercises multi-node
  scheduling and verifies jobs land on different nodes.
- Submit four jobs BEFORE adding nodes so the allocator's no-provider spin is
  observable in logs; then add two nodes and watch the daemon schedule the
  queued jobs onto them.
- Assert distribution by set equality (`{ipA, ipB}`) and reject the 0:4 / 4:0
  monopoly case. Exact 2:2 is NOT asserted — it is nondeterministic by design
  (~3s tasks, 2 nodes; 1:3, 2:2, 3:1 are all valid outcomes).
- Poll DB until all four tasks reach `DONE` (timeout ~30s) and assert each
  downloaded output file `1.input.out` exists with content matching the
  submitted `1.input` payload.
- Remove both nodes via `_manage_node_async([host, "--remove-soft", ...])` — the
  soft path removes cleanly when no RUNNING tasks remain (our happy path).
- Collect daemon debug logs via an in-memory `logging.Handler` and assert that
  `[ALLOCATED]` records appear for every task_id with both node IPs represented.
- Update `openspec/specs/e2e-testing/spec.md` to replace the bypass-path
  requirements (lines 36, 41 currently prescribe `uow.nodes.add` /
  `uow.nodes.remove` directly) with entrypoint-path requirements, and add
  multi-node, distribution, soft-remove, and log-tracking scenarios.
- Add a session-scoped `ssh_pool` fixture (list of 2 SSH containers sharing one
  keypair) and a function-scoped `log_records` fixture (in-memory log capture)
  to `tests/e2e/conftest.py`.

## Capabilities

### New Capabilities

_(none — no new behavior is introduced; this change only tightens test coverage
and updates the existing e2e-testing spec to match what the tests should have
been doing all along.)_

### Modified Capabilities

- `e2e-testing`: replace the single-node bypass-path full-cycle requirement with
  a multi-node entrypoint-driven lifecycle requirement, plus scenarios for
  distribution across nodes, soft-remove via entrypoint, and log-tracked
  scheduling activity.

## Impact

- `tests/e2e/test_full_cycle.py` — full rewrite (~150 lines).
- `tests/e2e/conftest.py` — add `ssh_pool` (session) and `log_records` (function)
  fixtures; `e2e_config` adjusted to symlink the shared keypair once (already
  does this for the single-container case — no change needed beyond consuming
  the new `ssh_pool` fixture).
- `openspec/specs/e2e-testing/spec.md` — rewrite the "Full cycle E2E test"
  requirement block and its scenarios.
- No production-code changes. No new dependencies. No CLI, config, DB schema,
  or public-API changes.