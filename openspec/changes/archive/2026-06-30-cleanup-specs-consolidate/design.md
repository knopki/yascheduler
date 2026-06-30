## Context

This is a specs-only hygiene change over `openspec/specs/` (35 specs, ~7640 lines).
The codebase is stable; the specs drifted during the recent architecture migrations
(`decompose-ssh-gateway`, `session-based-machine-handle`, `resolve-type-bridge-debt`,
`engine-to-domain-frozen`, config relocation) and the first cleanup pass
(`2026-06-28-cleanup-stale-specs`) did not reach all of it. The proposal establishes
WHAT changes (multiple defect fixes across 7 specs, residue strips, 3 merges,
cli-commands trim, AGENTS.md update). This design establishes HOW the spec edits
are structured and applied without introducing new drift.

Precedent: `openspec/changes/archive/2026-06-28-cleanup-stale-specs` — same change
class (specs-only), same delta representation.

## Goals / Non-Goals

**Goals:**
- Edits across all 15 Modified specs (residue strips, old-name renames, merges, cli-commands trim); each Modified/New/Removed capability gets a surgical requirement-level delta file under the change's
  `specs/` dir (per D1); at apply, MODIFIED requirements replace in-place, ADDED
  requirements append, REMOVED requirements delete, and the 5 Removed capabilities'
  directories are deleted.
- Strip migration residue via a single testable principle (see Decisions).
- Merges preserve every still-live requirement; no live contract lost.
- AGENTS.md OpenSpec Rule becomes the authoritative spec inventory.

**Non-Goals:**
- No `yascheduler/` code, test, DB schema, or CLI surface changes.
- No cosmetic renames of surviving specs (only the 3 agreed merges).
- No split of `cli-commands`; no merge of `abstract-uow`/`domain-services`/
  `domain-events`/`cli-args`/`daemon-common`.
- No knowledge-graph rewrite (verified: no module record references a merged-away
  spec name; the graph tracks M-* code modules, not specs).

## Decisions

### D1. Delta representation: surgical requirement-level deltas (matches precedent)
Mirror `2026-06-28-cleanup-stale-specs` exactly: each affected capability gets a
delta file under `specs/<name>/spec.md` using OpenSpec's requirement-level sections —
- `## MODIFIED Requirements` → `### Requirement: <exact current name>` with the full
  new text of that requirement (replaces the same-named requirement in the main spec).
  Used when a requirement's prose/scenarios change (e.g. dropping a defensive scenario,
  renaming an old symbol). To delete a single scenario, MODIFY its parent requirement
  with text that omits the scenario.
- `## ADDED Requirements` → `### Requirement: <name>` for genuinely new requirements
  (e.g. the merged `config-value-objects` content, the `AllocationTracker` requirement
  absorbed into `use-cases`, the shared "CLI exit-code contract" extracted in cli-commands).
- `## REMOVED Requirements` → `### Requirement: <exact current name>` (name only) for
  requirements deleted outright (e.g. ssh-keys-loading's "ConfigLocal migrated", the
  Report-capacity-bearing requirement if dropped whole). For a **whole capability**
  being deleted by a merge, the delta lists ALL its current requirements under
  `## REMOVED Requirements` (marks the capability for directory removal at apply).

Delta files are small (precedent: domain-ports 49 lines, package-facades 108) and keep
the diff reviewable. **Alternative rejected:** full-file rewrite — verbose, harder to
review, and unnecessary since the validator reconciles requirement-level deltas natively.

### D2. Residue-stripping principle (the test for what stays)
For every sentence in an affected spec, apply: *"Would an engineer writing this spec
from scratch today, against the current code, write this sentence?"*
- **Delete:** references to removed symbols (`MachineGateway`, `SSHMachineGateway`,
  `RemoteMachineRepository`, `ConfigLocal`, `ConfigDb`, `ConfigRemote`, the deleted
  `yascheduler.config` package, dissolved god-classes); "X SHALL NO LONGER be
  re-exported"; "the prior Y"; "relocated from"; defensive scenarios of the form
  "the removed symbol is still removed" / "the deleted package does not exist".
- **Keep (rephrase to positive if needed):** architectural constraints that still
  bind — layering rules (`application` ↛ `infra` runtime imports), the
  composition-root-only `Config` consumption rule, `@runtime_checkable` Protocol
  requirements, frozen-dataclass invariants. If such a rule is phrased negatively
  against an old name, rewrite it positively against the current symbol.
- **Rename in place:** `ConfigDb`→`PostgresDbConfig`, `ConfigRemote`→`RemoteDefaults`,
  `ConfigLocal`→`LocalSettings` wherever the symbol survives under a new name.

The distinguishing question is "is this about a *removed* thing, or a *current*
thing phrased with an old name?" — removed→delete; current-but-misnamed→rename/rewrite.

### D3. Merge mechanics
- **`config-value-objects` (new):** 4 Requirements colocated — `LocalSettings`,
  `RemoteDefaults`, `PostgresDbConfig`, `Config` — with their frozen-dataclass +
  `__post_init__` validation + no-INI-methods scenarios. Preserves the
  `config-aggregate` layering rule verbatim ("no module in `yascheduler.application`
  or `yascheduler.infra` SHALL import `Config`"). Source dirs `app-settings/`,
  `db-config/`, `config-aggregate/` deleted.
- **`testing-infrastructure` → `testing-unit`:** absorb the 3 unique requirements
  (pytest `[tool.pytest.ini_options]` config, `tests/{unit,integration,e2e}/` dir
  structure, CI unit-only workflow). De-duplicate the overlapping `UniqueQueue`
  requirement (keep the richer `testing-unit` version with the concurrent-put /
  unhashable-payload scenarios) and the shared-fixture requirement (merge the
  `make_task`/`make_node` + `ConfigBuilder` + mock-factory clauses into one).
  Delete `testing-infrastructure/`.
- **`allocation-tracker` → `use-cases`:** add as one Requirement (the
  `AllocationTracker` class contract: `add`/`discard`/`__contains__`, orchestrator-
  constructs-and-injects). Delete `allocation-tracker/`.

### D4. cli-commands trim (~1482 → ~800 lines)
Extract one shared **"CLI exit-code contract"** Requirement stating the uniform
0 / 1 / 2 semantics once. Each per-command Requirement drops its verbatim 0/1/2
block and references the shared contract. Drop the `@to_sync` → `asyncio.run`
migration narrative (the positive "entry points are sync `def` calling
`asyncio.run(_<name>_async(argv))`" rule stays). No per-command split.

### D5. AGENTS.md OpenSpec Rule format
Replace the 4-bullet testing-only subset with a full inventory: 31 entries, one per
line, as `` `openspec/specs/<name>` `` (backticked paths, no markdown links). Add a
terse one-line gloss ONLY where the spec name is not self-explanatory
(e.g. `config-value-objects`, `abstract-uow`); omit glosses for self-evident names
(`orchestrator`, `cli-commands`, `domain-entities`).

## Risks / Trade-offs

- **[Residue strip removes a live constraint]** → Mitigation: D2's distinguishing
  question. The risky cases are layering rules phrased as "not from X"; each is
  reviewed: if X is a *deleted* package → delete the clause (the constraint is
  vacuously satisfied); if X is a *current* package in a forbidden layer → keep,
  rewrite positively. `dependency-injection` and `config-parser-assembly` get this
  scrutiny.
- **[cli-commands exit-code trim loses per-command detail]** → Mitigation: extract
  the shared contract first, then verify each command still names its correct codes
  by reference; the k-reviewer pass on the `specs` batch checks per-command coverage.
- **[Merge orphans a cross-reference]** → Mitigation: grep verified zero cross-refs
  to the 5 removed capability names across `openspec/specs/`. The 3 merges are into
  existing capabilities that already carry their consumers' references.
- **[A MODIFIED requirement's new text drifts from intent]** → Mitigation: each
  MODIFIED requirement carries full replacement prose; the `specs` batch k-reviewer
  diffs the new text against the proposal's per-spec bullets, and any change not
  traceable to a proposal bullet is flagged.
- **[Graph drift]** → Mitigation: none needed; verified no M-* record references a
  merged spec name. If a record is found during apply, repoint it (declarative, per
  GRACE-lite soft-freeze).

## Migration Plan

1. Write delta specs in the change `specs/` dir (1 new capability with ADDED
   requirements + ~15 modified-capability deltas + 5 removed-capability deltas,
   each surgical per D1).
2. `openspec validate --all --json` must pass with the delta applied.
3. Apply: replace main `openspec/specs/` files, delete the 5 Removed dirs, rewrite
   AGENTS.md OpenSpec Rule section.
4. Re-run `openspec validate --all --json` (must pass) + `grace_check.py` (must
   remain green — no code/graph touched, so no-change expected).
5. Rollback: `git revert` the apply commit; the change dir preserves the originals
   in git history.

## Open Questions

None. All decisions confirmed before propose.
