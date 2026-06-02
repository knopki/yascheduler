# AGENTS.md

## Project

`yascheduler` schedules scientific calculation jobs on SSH machines and
cloud-created nodes. It provides a daemon, CLI tools, a Python client, and an
AiiDA scheduler plugin.

## Core Flow

1. A client or `yasubmit` creates a DB task with status `TO_DO`.
2. The daemon connects enabled nodes from `yascheduler_nodes`.
3. The allocator picks a compatible free node or requests a cloud node.
4. Inputs are uploaded, `spawn` starts remotely, and the task is `RUNNING`.
5. The daemon detects completion, downloads outputs, and marks `DONE`.
6. Idle cloud nodes are disabled and deleted after provider tolerance.

## Development Rules

- Follow the methodology of GRACE-lite and OpenSpec.
- Public interface stability: CLI commands (`yasubmit`, `yastatus`, `yanodes`,
  `yasetnode`, `yainit`, `yascheduler`), `class Yascheduler` public API, INI
  config format (including `[engine.*]` sections and `%(key)s` interpolation),
  DB schema (`schema.sql` — schema changes MUST include migrations), AiiDA
  scheduler entrypoint.
- Do not hand-edit `pyproject.toml` version; release automation owns it.
- Python minimum is `>=3.9` in `pyproject.toml`.
- Do not add new dependencies without declaring them in a change proposal with
  rationale.
- Maintain compatibility with both `pip` and `uv`. Use only PEP 621 standard
  fields in `pyproject.toml`.
- Prefer minimal changes over broad refactors.
- Do not add compatibility layers without a concrete need.
- Use Conventional Commits if asked to commit.

## OpenSpec Rule

Any code, configuration, CLI, workflow, engine contract, cloud behavior, DB
schema, or operational behavior change must consult `openspec/specs/` before
implementation and update the relevant OpenSpec requirements in the same change.

Use `openspec/changes/` proposals for behavior-changing work before
implementation.

If the user requests changes outside the OpenSpec workflow, offer to use
OpenSpec via `/opsx-propose`, but do not block or refuse the requested work.

- [testing-unit](openspec/specs/testing-unit) — unit tests: config parsing, data
  models, DB (mocked), remote machine management, scheduler orchestration
- [test-db-integration](openspec/specs/test-db-integration) — integration tests
  for DB against real PostgreSQL via testcontainers
- [e2e-testing](openspec/specs/e2e-testing) — end-to-end tests: full task
  lifecycle against real PostgreSQL and SSH containers via testcontainers
- [testing-infrastructure](openspec/specs/testing-infrastructure) — pytest
  config, directory structure, shared fixtures, CI workflow

## Verification

- New code should include focused unit tests for core logic and pure behavior;
  test happy paths first, then meaningful edge cases.
- For changes touching DB queries, node lifecycle, SSH interaction, or
  orchestrator flow, also add or update integration/e2e tests per the relevant
  OpenSpec specs (`test-db-integration`, `e2e-testing`).
- Run tests: `uv run -m unit`, `uv run -m integration`, `uv run -m e2e`
  (Docker must be running for integration and e2e — they use testcontainers).
- Static checks: `uv run zuban check`, `uv run ruff check .`,
  `uv run ruff format --check .`
- Spec validation: `openspec validate --all --json` must pass after creating a
  change proposal and after any modification to `openspec/specs/` (on
  archive/sync too).
- Validate GRACE-lite must pass after any code modification session.
- Use testcontainers for integration and e2e tests (PostgreSQL, SSH). Avoid
  only uncontrolled production resources (real cloud accounts, production DBs,
  live SSH servers) unless explicitly requested and configured.

<!-- START_GRACE-lite -->

## GRACE-lite: Graph-RAG Anchored Code Engineering

GRACE-lite: code methodology. **Semantic markup** (contracts, anchors) +
**knowledge graph** (`docs/knowledge-graph.xml`) + **structured logging** =
machine-navigable code. Self-similar markup: MODULE_CONTRACT → function
contract → block anchors. Each level narrows ambiguity. Same markup serves
generation (top-down template) and navigation (bottom-up index).

### Core Principles

**1. Contract-First.** Create/update MODULE_CONTRACT before code. Requirements,
architecture, or verification unclear → write contract first. Contract =
intent, code = implementation.

**2. Semantic Markup Is Navigation.** `START_*/END_*` = semantic coordinates
for 1-2 hop navigation. Not documentation. Unique, paired.

**3. Knowledge Graph Is Always Current.** `docs/knowledge-graph.xml` = project
map. Update in same change when structure, API, or dependencies change. Graph
compresses structure for fragment-based reading.

**4. Governed Autonomy.** Contracts/plans/graph = WHAT. Agents choose HOW
within boundaries.

**5. Proportional Markup.** Core logic → full contracts. Trivial helpers →
none. Unnecessary anchors = noise. Over-markup degrades navigation.

Paired anchors set expectations before implementation. Contract-first: decide
intent → generate. Self-similar markup: MODULE_CONTRACT → function contract →
block anchors. Each level restricts ambiguity below. Code markup only.

### Navigation Order (mandatory)

Navigate: **1)** `docs/knowledge-graph.xml` (shared truth) → **2)** file-local
markers (`START_MODULE_CONTRACT`, `START_MODULE_MAP`, `START_CHANGE_SUMMARY`,
`START_CONTRACT:`, `START_BLOCK_`) → **3)** full file reads after narrowing to
module/file/block.

Anchor-based path exists → use it. No linear reads.

- `M-<ID>` — module record in `docs/knowledge-graph.xml`
- `CrossLink` — cross-module graph edges
- `LINKS:` + module ID — implementation files in `yascheduler/` and `tests/`
- `START_MODULE_CONTRACT` / `START_CONTRACT:` — file-local contracts
- `START_BLOCK_` — logic slices within functions
- `START_CHANGE_SUMMARY` — recent local rationale
- No line-number targeting. Use block/contract anchors.

### Semantic Markup Reference

#### Module Level (required on every governed file)

```python
# FILE: path/to/file.ext
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: [What this module does - one sentence]
#   SCOPE: [What operations are included]
#   DEPENDS: [M-ID dependencies or "none"]
#   LINKS: [Knowledge graph references]
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   exportedSymbol - one-line description
# END_MODULE_MAP
```

#### Function Level

Required: core business logic, exported functions, public methods,
graph-relevant callables. Optional: private helpers, trivial accessors. Place
above function signature.

```python
# START_CONTRACT: functionName
#   PURPOSE: [What it does]
#   INPUTS: { paramName: Type - description } | { None }
#   OUTPUTS: { ReturnType - description } | { None - no return value }
#   SIDE_EFFECTS: None | description of external state changes
#   LINKS: [Related modules/functions; M-*, fn-*, type-*, class-*, etc]
# END_CONTRACT: functionName
```

#### Code Block Level (required)

```python
# START_BLOCK_VALIDATE_INPUT
# ... code ...
# END_BLOCK_VALIDATE_INPUT
```

Block names = **logical purpose** (`VALIDATE_INPUT`, `COLLECT_RESULTS`), not
implementation details.

#### Change Tracking (required)

```python
# START_CHANGE_SUMMARY
#   LAST_CHANGE: [v1.2.0 - What changed and why]
#   PREVIOUS_CHANGE: [v1.1.0 - What changed and why]
# END_CHANGE_SUMMARY
```

### Logging & Verification

Structured logs = primary observability. Block boundary log entries declare
what code assumes at that point. Runtime behavior traceable back to contract.

Governed functions emit `logging.debug("[Module][function][BLOCK] msg", extra={...})`
at block boundaries. Prefer structured fields; redact secrets. Missing anchors
on critical branches = verification defect.

Tests: deterministic assertions first. Trace/log assertions when trajectory
matters. Module-local tests stay close to module. Test files may carry
MODULE_CONTRACT, MODULE_MAP, semantic blocks, CHANGE_SUMMARY when substantial.
Update tests when log markers change intentionally.

### Knowledge Graph (`docs/knowledge-graph.xml`)

Root: `<KnowledgeGraph>`. Child: `<Project NAME="..." VERSION="...">`.
Required children: `<keywords>`, `<annotation>`. Optional: `M-*`,
`DF-*`, `CrossLink`.

#### M-{NAME} Module Element

Each governed module uses unique `M-{DOMAIN}` ID as XML tag:

```xml
<M-DOMAIN NAME="Human name" TYPE="CORE_LOGIC" STATUS="planned">
  <purpose>One-line purpose</purpose>
  <path>src/relative/path.py</path>
  <depends>M-OTHER, M-THIRD or None</depends>
  <annotations>
    <fn-name PURPOSE="Function purpose" />
    <class-Name PURPOSE="Class purpose" />
    <type-Name PURPOSE="Type description" />
    <export-name PURPOSE="Public export" />
    <const-NAME PURPOSE="Constant purpose" />
  </annotations>
</M-DOMAIN>
```

Required: `<purpose>`, `<path>`, `<depends>`. Optional: `<annotations>`.
TYPE: `ENTRY_POINT` | `CORE_LOGIC` | `DATA_LAYER` | `UI_COMPONENT` |
`UTILITY` | `INTEGRATION`. STATUS: `planned` → `partial` → `implemented`.
Test modules stay out of graph.
Annotation prefixes: `fn-`, `class-`, `type-`, `export-`, `const-`. Each
MUST have PURPOSE attribute.

#### DF-{NAME} Data Flow Element

```xml
<DF-PROCESS NAME="Process request">M-API -> M-CONTENT -> M-STORAGE</DF-PROCESS>
<DF-STREAM NAME="Parallel paths">M-API -> M-STREAMING; M-DWEETS -> M-STREAMING</DF-STREAM>
```

Separators: `->` sequential, `;` parallel/independent, `/` alternatives.
Tag = `DF-<NAME>`, `NAME` attribute required.

#### CrossLink: Cross-module Link

```xml
<CrossLink from="M-API" to="M-CONTENT" relation="delegates parsing" />
```

`from`/`to` must reference existing M-IDs. `relation` = free-form prose.

### Rules for Modifications

Before code: read `docs/knowledge-graph.xml` → file's `MODULE_CONTRACT`.

1. New files → MODULE_CONTRACT + MODULE_MAP + CHANGE_SUMMARY on creation.
   Existing files: bring to standard when substantively edited; internal
   markup progressively.
2. After editing: update `MODULE_MAP` if public surface changed; add/update
   `CHANGE_SUMMARY` entry.
3. Update `docs/knowledge-graph.xml` in same change: module added/removed →
   `M-` entry; public API changed → `<annotations>`; dependencies changed →
   `<depends>` + `<CrossLink>`. Private-only changes → no graph update.
4. Never remove semantic markup anchors unless intentionally replacing them.

### Size Limits

Size limits: source file 500 soft/1000 hard, function+contract 60, semantic
block 50. Exceed → evaluate splitting.

### Validation

Run validation before considering work complete.

```bash
python3 scripts/grace_check.py              # XML + source checks
python3 scripts/grace_check.py --json       # Machine-readable
```

Exit 0 = ok, 1 = errors, 2 = usage.

<!-- END_GRACE-lite -->
