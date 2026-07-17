## 1. Split engine-config-parsing into its own capability

- [x] 1.1 Create `openspec/specs/engine-config-parsing/spec.md` with a `## Purpose` (WHY: decouple engine INI parsing from the domain model so the domain spec does not reference an entrypoints module) and the `### Requirement: Engine INI parser functions` block plus its 5 scenarios, taken verbatim from `openspec/changes/domain-entities-spec-trim/specs/engine-config-parsing/spec.md`
- [x] 1.2 Delete the `### Requirement: Engine INI parser in entrypoints` block (requirement text and all 5 scenarios) from `openspec/specs/domain-entities/spec.md`
- [x] 1.3 Run `openspec validate --all --json` — passes; both capabilities validate and `domain-entities` no longer references `entrypoints/config_parser.py`

## 2. Trim domain-entities spec to behavioral contracts

- [x] 2.1 Apply the trimmed versions of all 12 MODIFIED requirements from `openspec/changes/domain-entities-spec-trim/specs/domain-entities/spec.md` to `openspec/specs/domain-entities/spec.md`, replacing each original requirement block in place
- [x] 2.2 Verify every behavioral scenario from the original spec (~30 scenarios across TaskId, NewTask, Task, Node, ConnectedMachine, Engine, materialize_task, NodeId, NewNode, NodeStatus, EngineRepository, plus ProcessResult and MachineState which are carried over unchanged) is present in the main spec — no behavioral scenario dropped. The change delta is 11 MODIFIED + 1 REMOVED; the two unchanged requirements (ProcessResult, MachineState) are preserved as-is by the merge and must still be present in the main spec after the MODIFIED blocks are applied
- [x] 2.3 Confirm the trimmed main spec contains no implementation/migration/DB/future-intent prose: no `REMOVED`/`no longer`/`is removed`/`migrating` migration footprints; no dataclass field-order reasoning; no DB constraints (`UNIQUE`/`CHECK`/`FK ON DELETE`/`DEFAULT NOW()`/`RETURNING`); no `replace()` mechanics; no `SHALL NOT` enumerations of removed methods/classes; no `Future intent`/`future cloud-adapter change`; no version-branch enum detail
- [x] 2.4 Run `openspec validate --all --json` — passes

## 3. Absorb model.py rationale into contract regions under contract discipline

- [x] 3.1 Enrich `# region CLASS_TaskId` and `# region CLASS_NodeId` in `yascheduler/domain/model.py` with the value-object rationale that left the spec (why a dedicated type vs bare int / vs NewType / vs int subclass), using only existing contract fields per their defined purpose — RATIONALE holds design-choice Q/A, INVARIANTS holds the value>0 + hashable + not-equal-to-int facts; PURPOSE stays a single WHY sentence (not a WHAT)
- [x] 3.2 Enrich `# region CLASS_Task`, `# region CLASS_NewTask`, `# region CLASS_Node`, `# region CLASS_NewNode`, `# region CLASS_ConnectedMachine`, `# region FUNC_materialize_task` with the field-order rationale, the "sole conversion/emission site" architectural constraints, and the migration-era notes rephrased as current-state invariants — each constraint in its correct field (INVARIANTS for invariants, RATIONALE for design-choice justification), no field misused as a dumping ground
- [x] 3.3 Verify every `# region` block encloses ALL content of its target: a `CLASS_*` region spans from the `@dataclass`/`class` line through the full class body (all fields and methods) to its `# endregion`; a `METHOD_*`/`FUNC_*` region spans the full def body to its `# endregion` — no region closes before the class/method body ends
- [x] 3.4 Verify no invented contract field names are introduced — only PURPOSE / SCOPE / INVARIANTS / RATIONALE / REQUIRES / ENSURES / KEYWORDS appear, each used per its meaning
- [x] 3.5 Run `uv run ruff check yascheduler/domain/model.py` and `uv run ruff format --check yascheduler/domain/model.py` — pass

## 4. Absorb engine.py rationale into contract regions

- [x] 4.1 Enrich `# region CLASS_Engine` in `yascheduler/domain/engine.py` with the rationale that left the spec (why INI parsing lives outside Engine / why Engine must not import ConfigParser; why the 4 merge fields carry defaults) — in RATIONALE/INVARIANTS per field purpose; PURPOSE stays WHY
- [x] 4.2 Enrich `# region CLASS_EngineRepository` with the frozen/Mapping-unhashable rationale and the "returns a new frozen instance" filter contract — in INVARIANTS/RATIONALE per field purpose
- [x] 4.3 Verify the region-enclosure and no-invented-fields rules from 3.3 and 3.4 hold for engine.py as well
- [x] 4.4 Run `uv run ruff check yascheduler/domain/engine.py` and `uv run ruff format --check yascheduler/domain/engine.py` — pass

## 5. Test audit and full static verification

- [x] 5.1 Audit `tests/` for any docstring, comment, or assertion referencing the relocated requirement name ("Engine INI parser in entrypoints") or asserting domain-entities spec text content — update references to point at the new `engine-config-parsing` capability; confirm no test asserts spec prose (tests assert behavior, which is unchanged)
- [x] 5.2 Run `uv run pytest -m unit` — all domain/engine unit tests pass (no behavior changed)
- [x] 5.3 Run `uv run ruff check .` and `uv run ruff format --check .` — pass
- [x] 5.4 Run `uv run lint-imports` — passes (no new imports; INI-parser functions stay where they are)
- [x] 5.5 Run `openspec validate --all --json` — all specs and the change validate cleanly; change is ready to archive
