## Why

Phase 5 of the architecture migration. `utils.py` (~540 lines) mixes argparse
setup, DB operations, SSH connections, and business logic in one file. CLI
commands should be thin wrappers that parse arguments and call use cases via DI.

## What Changes

- Create `adapters/cli/commands.py` — thin CLI command functions (submit,
  status, nodes, setnode, init, daemonize).
- Each command calls use cases via `di.make_cli_deps()`.
- `utils.py` becomes a re-export wrapper, importing from `adapters/cli/`.
- `pyproject.toml` entry points updated to point to new location
  (`yascheduler.adapters.cli.commands:submit`).

## Capabilities

### New Capabilities
- `cli-commands`: CLI command functions moved from `utils.py` to
  `adapters/cli/commands.py`, each calling use cases via DI.

### Modified Capabilities
<!-- None. -->

## Impact

- New file: `adapters/cli/commands.py`.
- Modified: `utils.py` — becomes re-export wrapper.
- Modified: `pyproject.toml` — entry points update paths.
- All 6 CLI commands functional with identical behavior.
- `docs/knowledge-graph.xml` updated.
