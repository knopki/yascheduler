# AGENTS.md

## Project

`yascheduler` schedules scientific calculation jobs on SSH machines and
cloud-created nodes. It provides a daemon, CLI tools, a Python client, and an
AiiDA scheduler plugin.

## Architecture

The current architecture description is in the file `docs/knowledge-graph.xml`.
Always read it if you want to understand the architecture of the application or
find out which file contains the module.

## Core Flow

1. A client or `yasubmit` creates a DB task with status `TO_DO`.
2. The daemon connects enabled nodes from `yascheduler_nodes`.
3. The allocator picks a compatible free node or requests a cloud node.
4. Inputs are uploaded, `spawn` starts remotely, and the task is `RUNNING`.
5. The daemon detects completion, downloads outputs, and marks `DONE`.
6. Idle cloud nodes are disabled and deleted after provider tolerance.

## Development Rules

- Follow the methodology of GRACE-lite and OpenSpec
- Keep public CLI names and AiiDA entrypoint behavior stable unless the change
  is intentionally user-facing.
- Do not hand-edit `pyproject.toml` version; release automation owns it.
- Prefer minimal changes over broad refactors.
- Do not add compatibility layers without a concrete need.
- Use Conventional Commits if asked to commit.

## GRACE-lite: Code Navigation / Source Code Map / Find Symbol

<knowledge-graph path="docs/knowledge-graph.xml">
  Contains the authoritative map of every module, symbol, file path, and
  dependency edge. You SHOULD grep it to understand architecture and file
  locations. Do not read full file.
</knowledge-graph>

<navigation-algorithm mandatory before="ANY grep">
  <mandatory-step n="1">
    Understand project architecture, module map, file paths from
    `docs/knowledge-graph.xml`. Grep it. Do not read full file.
  </mandatory-step>
  <mandatory-step n="2">
    Read file offset only after the target is narrowed
    to a specific module, file, or block.
  </mandatory-step>
</navigation-algorithm>

<grace-lite-skill-triggers>
  <action>Load the `grace-lite` skill</action>
  <trigger>
    You encounter START_MODULE_CONTRACT, START_CONTRACT, or START_BLOCK
    markers during navigation.
  </trigger>
  <trigger>You are about to create, edit, or refactor any source file.</trigger>
  <trigger>You update docs/knowledge-graph.xml or add modules / public interfaces.</trigger>
  <trigger>The user mentions GRACE.</trigger>
</grace-lite-skill-triggers>

## OpenSpec Rule

Any code, configuration, CLI, workflow, engine contract, cloud behavior, DB
schema, or operational behavior change must consult `openspec/specs/` before
implementation and update the relevant OpenSpec requirements in the same change.

Use `openspec/changes/` proposals for behavior-changing work before
implementation.

If the user requests changes outside the OpenSpec workflow, offer to use
OpenSpec via `/opsx-propose`, but do not block or refuse the requested work.

## Verification

- New code should include focused unit tests for core logic and pure behavior;
  test happy paths first, then meaningful edge cases.
- New code should include focused unit tests for core logic and pure behavior;
  test happy paths first, then meaningful edge cases.
- Static checks: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run zuban check`
- Spec validation: `openspec validate --all --json` must pass after creating a
  change proposal and after any modification to `openspec/specs/` (on
  archive/sync too).
- Validate GRACE-lite must pass after any code modification session.
- For behavior changes, add focused tests when feasible or document manual
  verification.
- Avoid real cloud, SSH, system service, or DB mutations unless explicitly
  requested and configured.

## Reference Specs

- `docs/knowledge-graph.xml`: GRACE-lite navigational code graph with detailed
  architecture.
- `openspec/specs/development-conventions/spec.md`: project contracts and
  extension rules.
