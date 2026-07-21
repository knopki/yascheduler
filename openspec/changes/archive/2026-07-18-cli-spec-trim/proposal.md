## Why

`openspec/specs/cli/spec.md` (963 lines, 29 requirements, 111 scenarios) interleaves
actual SHALL requirements with three content kinds that GRACE assigns to
code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 11 instances
   enumerating absent code (`daemon_sysv SHALL NOT pass short="-l"`,
   `configure_logger SHALL NOT call logging.basicConfig`,
   `run_daemon`'s `logger SHALL NOT be forwarded to make_daemon`,
   `daemon_systemd/daemonize SHALL NOT use python-daemon`,
   `SSH repository SHALL NOT receive jump_host / jump_username`,
   `yastatus SHALL NOT add header/footer/summary`,
   `yastatus SHALL NOT pass jump_host / jump_username`,
   `submit() SHALL NOT add --json/--table/output-mode flag`). Every one is
   already asserted by a Gherkin scenario or is a non-existent code path dressed
   up as a normative requirement. The prose is drift bait.
2. **Design rationale living in the spec** — the AiiDA-plugin contract
   narrative (repeated three times across `yasubmit` requirements), the
   "argument-shape vs argument-content validation" split, the "yainit is a
   bootstrap exception" framing, the implementation instruction "wrap in
   `try: ... except Exception as e: print(...); sys.exit(1)`; a bare traceback
   is a defect", and the "Single source of truth" / "via shared helpers" /
   "via DI" prose. These answer *why the code is shaped this way* — they belong
   in `RATIONALE` / `INVARIANTS` / `SCOPE` on the owning entity, not in spec.
3. **Duplicated exit-code contract** — the same "exit codes match the shared
   contract (0 success, 1 operational error, 2 invalid args)" requirement is
   restated verbatim in `yasubmit`, `yanodes`, `yasetnode`, `yastatus` while the
   authoritative `Daemon and CLI exit-code contract` requirement already covers
   them.

In parallel, the code under `yascheduler/entrypoints/cli/` violates the GRACE
Python rule ("if an entity is annotated by markup, it must always be wrapped in
a region"): public exception classes (`EngineNotDefinedError`,
`EngineNotSupportedError`, `MalformedHostSpecError`, `NodeAlreadyInDBError`,
`NodeIdNotInDBError`, `HostNotInDBError`), public dataclasses (`HostSpec`,
`NodeTarget`, `_NodeView`), and many non-trivial functions
(`_parse_submit_args`, `_parse_script_metadata`, `_read_input_files`,
`_build_metadata`, `_parse_nodes_args`, `_filter_rows`, `_parse_status_args`,
`_query_tasks`, `_download_convergence_snippet`, `_parse_convergence`,
`_parse_node_target`) live under a `MODULE_CONTRACT` but carry no entity-level
contract region. Where regions exist (all four `args.py` helpers,
`configure_logger`, `run_daemon`, the daemon launchers, the existing wrapped
functions in `submit.py`/`show_nodes.py`/`manage_node.py`/`check_status.py`),
they hold `PURPOSE` only — the rationale/invariants/scope that should accompany
the code is missing because it currently sits in the spec.

## What Changes

- **MODIFIED `cli`**: rewrite requirements to carry only behavioral contracts
  (SHALL statements + Gherkin scenarios). Remove the 11 invented `SHALL NOT`
  enumerations of absent code, the AiiDA-plugin narrative (repeated 3×), the
  "argument-shape vs argument-content validation" split paragraph, the
  "yainit bootstrap exception" framing, the implementation instruction
  paragraph ("wrap in try/except; bare traceback is a defect"), "single source
  of truth" prose, "via DI/shared helpers" connective tissue, and the four
  duplicated per-command exit-code requirements (already covered by the
  shared `Daemon and CLI exit-code contract`). Every observable behavioral
  scenario (111) survives unchanged.
- Add the missing `CLASS_*` and `FUNC_*` regions required by the GRACE Python
  rule to all unwrapped public exception classes, dataclasses, and non-trivial
  functions across `submit.py`, `show_nodes.py`, `check_status.py`,
  `manage_node.py`.
- Enrich existing `MODULE_CONTRACT`, `FUNC_*`, and the new `CLASS_*` regions
  with the rationale/invariants/scope that leaves the spec, each in its correct
  GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
  - `INVARIANTS` carries conditions/contracts that always hold (e.g.
    `configure_logger` never calls `basicConfig`; daemon entry points never
    register signal handlers themselves; `_add_node` never passes
    `jump_host`/`jump_username` to `repository.connect`).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g.
    why `submit()` never grows a `--json` flag: the AiiDA plugin parses
    `int(stdout.strip())` so the success output is fixed to `str(task_id)`).
  - `SCOPE` declares the entity's functional boundaries with explicit `NOT:`
    exclusions where useful.
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no free-form labels.
- Every `CLASS_*` region encloses the FULL class body — the `class` line (and
  any `@dataclass(...)` decorator), the docstring, every field, every
  `__init__` line, every `self.<attr>` assignment — through the trailing blank
  line before the next region marker. Every `FUNC_*` region encloses the
  decorator (if any), the `def`/`async def` line, the body, and the trailing
  blank line. No region closes before its entity ends.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `cli`: requirements slimmed to SHALL statements and behavior scenarios;
  invented `SHALL NOT` negative-space language, design rationale, integration
  narrative, and four duplicated per-command exit-code requirements relocated
  out of the spec text and into GRACE code contracts across
  `yascheduler/entrypoints/cli/*.py`. No CLI behavior, signatures, scenarios,
  exit codes, output formats, or argv contracts are added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/cli/spec.md` rewritten — every requirement trimmed
  to behavioral SHALL + scenarios; pre/post scenario count compared and MUST
  remain 111 → 111 (or higher if deduplication reveals a need). `openspec
  validate --all --json` must still pass after the change.
- **Code (markup only, no logic)**: `yascheduler/entrypoints/cli/args.py`,
  `daemon_common.py`, `daemonize.py`, `daemon_systemd.py`, `daemon_sysv.py`,
  `init.py`, `submit.py`, `show_nodes.py`, `manage_node.py`, `check_status.py`
  — existing `MODULE_CONTRACT`/`FUNC_*` regions enriched with
  `INVARIANTS`/`RATIONALE`/`SCOPE`; new `CLASS_*` regions added for the 9
  currently-unwrapped exception classes and dataclasses; new `FUNC_*` regions
  added for the 11 currently-unwrapped non-trivial functions. No code logic,
  signature, decorator, docstring semantics, or import changes. Code contracts
  absorb what leaves the spec, comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing CLI tests already assert them. A passing
  `uv run pytest -m unit` and `-m integration` run after the change is the
  regression guard.
- **Public surface**: none. No CLI command, console_script, INI config, DB
  schema, public API, or log-format change in the diff. The diff is
  `# region`/`# endregion` markup + comment-field enrichment + spec text trim
  only.
- **Pilot scope**: this change ONLY dehydrates the `cli` spec. Other specs
  (`orchestrator`, `cloud`, `use-cases`, etc.) are explicitly out of scope.
  Follows the pattern set by `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`, `2026-07-18-domain-exceptions-spec-trim`,
  and `2026-07-18-slim-domain-ports-spec`.
- **Non-goals**:
  - No change to any CLI behavior, argparse grammar, exit-code value, output
    format, console_script, or service-template substitution.
  - No spec split; all trimmed requirements remain in the `cli` capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No rewrite of `entrypoints/__init__.py`, `entrypoints/config.py`,
    `entrypoints/config_parser.py`, `entrypoints/di.py`, or
    `entrypoints/_config_utils.py` (out of capability scope).
