## Context

Phase 5. `utils.py` is the last module still mixing infrastructure with
orchestration. All use cases (Phase 3) and DI (Phase 4) are ready. CLI
commands should be adapters — parse args, call use cases, format output.

## Goals / Non-Goals

**Goals:**
- Move 6 CLI command functions to `adapters/cli/commands.py`.
- Each command obtains deps from `make_cli_deps()` or `make_daemon()`.
- Update console_scripts entry points.
- Preserve identical CLI behavior.

**Non-Goals:**
- No changes to command-line argument format.
- No changes to output format.
- No new commands.

## Decisions

### D1: One function per command

Each CLI function:
1. Parses argparse arguments
2. Calls `di.make_cli_deps(config)` (or `make_daemon` for daemonize)
3. Calls the appropriate use case
4. Formats output (print, sys.exit)

### D2: Entry points updated

```toml
[project.scripts]
yainit = "yascheduler.adapters.cli.commands:init"
yanodes = "yascheduler.adapters.cli.commands:show_nodes"
yascheduler = "yascheduler.adapters.cli.commands:daemonize"
yasetnode = "yascheduler.adapters.cli.commands:manage_node"
yastatus = "yascheduler.adapters.cli.commands:check_status"
yasubmit = "yascheduler.adapters.cli.commands:submit"
```

### D3: utils.py becomes re-export

```python
# utils.py
from yascheduler.adapters.cli.commands import (
    submit, check_status, init, show_nodes, manage_node, daemonize
)
```

This preserves any direct imports of `yascheduler.utils.submit` etc.

## Risks / Trade-offs

- **Entry point change may break packaging**: The `pyproject.toml` paths
  change. Mitigation: verify with `uv run yasubmit --help` after change.
- **utils.py imports in AiiDA plugin**: AiiDA may import from utils.
  Mitigation: re-export preserved.
