## Why

`domain-entities` is the largest domain spec (~518 lines) yet ~40% of its prose
describes *how* the code is arranged — dataclass field order, `replace()`
mechanics, DB constraints (`DEFAULT NOW()`, `UNIQUE`, FK `ON DELETE SET NULL`,
`CHECK`), migration footprints ("REMOVED", "no longer", "SHALL NOT inherit
`UserDict`"), and out-of-scope future intent. This duplicates what the code's
`# region` contract markup already states at the point of truth, leaving two
sources that drift, and obscures the behavioral contract (lifecycle transitions,
value-object semantics, platform/ncpus rules) that the spec alone should carry.

The "Engine INI parser in entrypoints" requirement describes functions that live
in `entrypoints/config_parser.py`, not the domain — it is misplaced and silently
couples a domain spec to an entrypoint module.

## What Changes

- **MODIFIED `domain-entities`**: rewrite the spec to carry only behavioral
  contracts (requirements + Gherkin scenarios). Remove implementation mechanics,
  migration footprints, dataclass field-order rationale, DB constraint
  language, and future-intent notes — these belong in code contract regions, not
  the spec.
- **NEW `engine-config-parsing`**: relocate the Engine INI parsing requirement
  (`parse_engine_section`, `parse_engines`, `engine_valid_fields`) out of
  `domain-entities` into a capability that matches where the code lives
  (`entrypoints/config_parser.py`), preserving its scenarios unchanged.
- Update `# region` contract markup in `yascheduler/domain/model.py` and
  `yascheduler/domain/engine.py` to absorb the implementation-side rationale
  (field-order reasoning, value-object "why a dedicated type" rationale,
  migration-era "REMOVED" notes framed as current-state invariants) that leaves
  the spec. Contract region blocks already enclose full classes/methods; this
  change keeps and extends that discipline.

## Capabilities

### New Capabilities

- `engine-config-parsing`: INI → `Engine` / `EngineRepository` parsing
  (`parse_engine_section`, `parse_engines`, `engine_valid_fields`) and its
  parser-side validation scenarios.

### Modified Capabilities

- `domain-entities`: requirements shed implementation/migration/future-intent
  prose; behavioral contracts and Gherkin scenarios preserved. The INI-parser
  requirement is removed from this capability (moved to `engine-config-parsing`).

## Impact

- `openspec/specs/domain-entities/spec.md` — rewritten (trim); all behavioral
  scenarios preserved, implementation prose removed.
- `openspec/specs/engine-config-parsing/spec.md` — new, receives the relocated
  INI-parser requirement and its scenarios verbatim.
- `yascheduler/domain/model.py` — contract regions (`CLASS_TaskId`, `CLASS_Task`,
  `CLASS_Node`, `CLASS_NewNode`, etc.) extended with rationale that moves out of
  the spec; field-order reasoning and value-object "why" stated as INVARIANTS /
  RATIONALE inside the regions.
- `yascheduler/domain/engine.py` — `CLASS_Engine`, `CLASS_EngineRepository`
  regions extended with rationale currently mislived in the spec.
- No public API, schema, dependency, or runtime behavior change.
- Non-goal: other domain specs (`domain-ports`, `domain-events-and-dispatch`,
  `domain-exceptions`), application/infra specs, and the webhook-handler
  relocation flagged in earlier review — separate changes.
