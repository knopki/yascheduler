## Why

`openspec/specs/postgres-schema-apply/spec.md` (114 lines, 4 requirements, 11
scenarios) interleaves actual SHALL contracts with five content kinds that
GRACE assigns to code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space guard.** The `Full latest snapshot
   with no inline ALTERs` requirement says: "The primary-key columns
   `yascheduler_nodes.node_id` and `yascheduler_tasks.task_id` SHALL be declared
   as `INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY` (SQL:2003 identity
   columns, PostgreSQL 10+). They SHALL NOT be declared as `SERIAL PRIMARY
   KEY`." The `SHALL NOT` half enumerates absent SQL syntax as a normative
   requirement — `SERIAL PRIMARY KEY` does not appear anywhere in `schema.sql`
   (verified: zero hits in `yascheduler/infra/persistence/sql/schema.sql`).
   This is precisely the negative-space pattern the project's prior trims
   removed from `db-migrations` (forward-only `SHALL NOT` enumerations),
   `cloud`, `domain-exceptions`, `domain-ports`, and `engine-config-parsing`.
   The positive half of the sentence — IDENTITY columns are the contract —
   stays in the spec; the `SHALL NOT` half becomes an `INVARIANTS` entry on the
   owning module in positive form.
2. **Procedural SQL ordering narrative.** The same requirement body specifies
   creation order step by step: "The `task_status` enum type SHALL be created
   in `schema.sql` before the `CREATE TABLE yascheduler_tasks` statement. The
   `yascheduler_touch_updated_at()` trigger function and the
   `yascheduler_tasks_touch_updated_at` trigger SHALL be created in `schema.sql`
   after the `CREATE TABLE yascheduler_tasks` statement." This describes HOW
   `schema.sql` serializes its DDL — a PostgreSQL mechanical requirement
   (dependent objects need their prerequisites to exist first). The observable
   behavior — `apply_schema` applies the full schema cleanly on a fresh
   database — is already asserted by the `Schema applies cleanly on empty
   database`, `Fresh database has the task_status_field_invariants CHECK`, and
   `Fresh database has the node_ncpus_positive CHECK` scenarios. The procedural
   ordering belongs in `INVARIANTS` on the module that owns the asset.
3. **Redundant column enumeration.** The body sentence "The `username` and
   `port` columns of `yascheduler_nodes` SHALL be present in the
   `CREATE TABLE yascheduler_nodes` statement (they are part of the latest
   snapshot)." restates the requirement's opening ("every `CREATE TABLE`
   statement includes all current columns") for two specific columns. There is
   no scenario that observes `username` or `port` separately; the columns are
   in `schema.sql` because the snapshot is authoritative. The sentence is drift
   bait and is dropped; the high-level "every `CREATE TABLE` statement includes
   all current columns" SHALL remains.
4. **Design rationale living in the spec.** Three pieces answer *why the code
   is shaped this way*, not *what the system does*:
   - The `Schema evolution is expressed via migration files, not via inline
     `ALTER`s in `schema.sql`.` aside on the `Full latest snapshot`
     requirement — a forward-looking design rule duplicating the scenario
     `schema.sql has no inline ALTER TABLE ADD COLUMN` plus the entire
     `db-migrations` capability.
   - The `The magic 0 sentinel is no longer a valid stored value in the latest
     snapshot; NULL represents "no operator limit".` sentence on the
     `yascheduler_nodes.ncpus` declaration — a migration-history rationale
     (see archived `2026-07-13-node-ncpus-as-config`).
   - The `(SQL:2003 identity columns, PostgreSQL 10+)` parenthetical and the
     `SERIAL PRIMARY KEY` prohibition together — they document *why* IDENTITY
     is the choice (modern PostgreSQL standard, survived the
     `2026-07-03-serial-to-generated-identity` migration), not *what* the
     system does.
   Each piece belongs in `RATIONALE` on the owning entity, not in spec text.
5. **Implementation-level DDL narrative inside a SHALL contract.** The
   `Full latest snapshot` requirement body mixes genuine SHALL contracts
   (the `task_status_field_invariants` CHECK enforcing the per-status field
   contract; the `node_ncpus_positive` CHECK enforcing `(ncpus IS NULL OR
   ncpus > 0)`; the `SMALLINT DEFAULT NULL` declaration) with the verbatim
   SQL fragments that already live in `schema.sql`. The SHALL contracts and
   the SQL fragments both stay — the per-status field contract and the
   `ncpus` nullability contract are the only normative statement of the
   business rule (the matching scenarios only assert the constraint exists by
   name via `information_schema`, not its definition); the `schema.sql` text
   is the implementation, the spec text is the normative rule. What leaves
   the body is only the surrounding rationale and the negative-space guard.

In parallel, the code under `yascheduler/infra/persistence/postgres_schema.py`
(the sole consumer of `schema.sql`, explicitly named out of scope by the
in-flight `db-migrations-spec-trim`) carries only `PURPOSE` on its
`MODULE_CONTRACT` and `FUNC_apply_schema` regions. The rationale/invariants/
preconditions/postconditions that should accompany the code is missing because
it currently sits in the spec.

## What Changes

- **MODIFIED `postgres-schema-apply`**: rewrite all 4 requirements to carry
  only behavioral contracts (SHALL statements + Gherkin scenarios). Remove
  the enumerated `SHALL NOT` negative-space guard, the procedural SQL ordering
  narrative, the redundant `username/port` column enumeration, and the design
  rationale pieces listed above from the body. Every observable behavioral
  scenario (11) survives unchanged; the per-status CHECK-contract SQL fragments
  and the `ncpus` declaration stay (they are the normative statement of the
  business rules the scenarios only verify by name). No requirement is added,
  removed, merged, or split; the 4 requirement headers stay identical so
  OpenSpec recognizes the MODIFIED operation.
- Enrich existing `MODULE_CONTRACT` and `FUNC_apply_schema` regions in
  `yascheduler/infra/persistence/postgres_schema.py` with the
  rationale/invariants/scope/preconditions/postconditions that leaves the spec,
  each in its correct GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
    The existing `PURPOSE` on both regions already answers WHY and stays
    unchanged.
  - `INVARIANTS` carries conditions/contracts that always hold (e.g. `schema.sql`
    is the canonical full latest snapshot; PK columns are `INTEGER GENERATED
    ALWAYS AS IDENTITY`; enum types are declared before the `CREATE TABLE`
    statements that reference them; trigger functions after; one transaction
    wraps the whole apply; on failure the transaction is rolled back and the
    exception is re-raised).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g.
    why `schema.sql` is a hand-edited snapshot instead of generated; why
    IDENTITY columns instead of `SERIAL`; why `ncpus SMALLINT DEFAULT NULL`
    with a CHECK instead of a `0` sentinel).
  - `REQUIRES` carries the precondition on `config` (validated
    `PostgresDbConfig`, reachable database, connecting user has CREATE
    privileges).
  - `ENSURES` carries the precise postconditions on success/failure.
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no
  `NOTES:`, no `RAISES:`, no free-form labels. The spec's removed `SHALL NOT`
  sentence does NOT become a `SHALL NOT:` contract field — it becomes an
  `INVARIANTS` entry stating the positive contract ("PK columns are declared
  `INTEGER GENERATED ALWAYS AS IDENTITY`; the legacy `SERIAL PRIMARY KEY`
  pseudo-type is not used").
- Every `CLASS_*` / `FUNC_*` / `METHOD_*` / `BLOCK_*` region already encloses
  the FULL entity (verified: `FUNC_apply_schema` spans lines 23-72 with all
  five nested `BLOCK_*` regions correctly nested; `MODULE_CONTRACT` spans
  lines 2-7). This change is comment-field enrichment only — no region markers
  are added, removed, or moved. The existing nested `BLOCK_*` regions inside
  `FUNC_apply_schema` (`BLOCK_open_connection`, `BLOCK_apply_schema`,
  `BLOCK_handle_existing`, `BLOCK_rollback`, `BLOCK_close`) stay as-is; their
  parent `FUNC_*` `# endregion` continues to come AFTER the last nested
  `# endregion`.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `postgres-schema-apply`: requirements slimmed to SHALL statements and
  behavior scenarios; the `SHALL NOT be declared as SERIAL` negative-space
  guard, the procedural SQL ordering narrative (enum types / triggers), the
  redundant `username/port` column enumeration, the design rationale
  (`schema.sql` hand-edited snapshot, `SERIAL`→`IDENTITY` migration history,
  `ncpus` magic-`0`-sentinel removal), and the verbatim CHECK-constraint SQL
  text relocated out of the spec body and into GRACE code contracts on
  `yascheduler/infra/persistence/postgres_schema.py`. No `apply_schema`
  behavior, signature, transaction semantics, error-reporting contract,
  `schema.sql` layout, observable scenario, or public API is added, removed,
  or changed.

## Impact

- **Specs**: `openspec/specs/postgres-schema-apply/spec.md` rewritten — every
  requirement trimmed to behavioral SHALL + scenarios; pre/post scenario count
  compared and MUST remain 11 → 11. `openspec validate --all --json` must
  still pass after the change.
- **Code (markup only, no logic)**:
  - `yascheduler/infra/persistence/postgres_schema.py` — enrich
    `MODULE_CONTRACT` with `INVARIANTS` (snapshot/identity/ordering contracts)
    and `RATIONALE` (snapshot vs generated; `IDENTITY` vs `SERIAL`; `ncpus`
    `NULL` vs `0`); enrich `FUNC_apply_schema` with `REQUIRES`, `ENSURES`,
    `INVARIANTS`, and (if useful) `RATIONALE`. No code logic, signature,
    decorator, docstring semantics, or import changes. Code contracts absorb
    what leaves the spec, comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing integration tests
  (`tests/integration/test_postgres_schema.py`) already assert them —
  `test_apply_schema_succeeds`, `test_apply_schema_tables_exist`,
  `test_apply_schema_raises_on_existing`,
  `test_apply_schema_has_node_ncpus_positive_check` cover the 4 requirements.
  A passing `uv run pytest -m integration tests/integration/test_postgres_schema.py`
  run after the change is the regression guard.
- **Public surface**: none. No CLI command, console_script, INI config key,
  DB schema, public API, `schema.sql` content, or log-format change in the
  diff. The diff is `# region` / `# endregion` markup + comment-field
  enrichment + spec text trim only.
- **Pilot scope**: this change ONLY dehydrates the `postgres-schema-apply`
  spec. Other specs (`db-migrations`, `postgres-persistence`, `cli`, `cloud`,
  `orchestrator`, etc.) are explicitly out of scope. Follows the pattern set
  by `2026-07-17-orchestrator-spec-dehydrate`,
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`,
  `2026-07-18-slim-domain-ports-spec`, the completed `cli-spec-trim`, the
  in-flight `cloud-spec-trim`, `config-value-objects-spec-trim`,
  `db-migrations-spec-trim`, `dependency-injection-spec-trim`,
  `e2e-testing-spec-trim`, `orchestrator-spec-trim`, `logging-spec-trim`, and
  `engine-config-parsing-spec-trim`.
- **Non-goals**:
  - No change to `apply_schema` behavior, transaction semantics, signature,
    error reporting, the contents of `schema.sql`, or the bootstrap DO block.
  - No spec split; all trimmed requirements remain in the
    `postgres-schema-apply` capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No markup added to `yascheduler/infra/persistence/sql/schema.sql` — it is
    a SQL DDL data asset, not a Python source file with GRACE regions, and
    the contract for what `schema.sql` contains lives on its sole consumer
    (`postgres_schema.py`) via `INVARIANTS`. This mirrors the rule established
    by `db-migrations-spec-trim` for migration `.sql` / `.py` files.
  - No markup additions to `yascheduler/entrypoints/cli/init.py` (owned by the
    `cli` capability, out of scope here) even though it consumes
    `apply_schema`.
