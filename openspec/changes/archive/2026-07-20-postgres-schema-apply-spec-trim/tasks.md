## Common rules for every code-touching task

Every code-touching task below obeys these invariants. They exist because a
prior attempt at a similar change was discarded specifically for violating
them.

- **GRACE fields are a closed set.** Allowed fields: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No invented fields. Specifically: no `SHALL NOT:`
  pseudo-field, no `EFFECTS:`, no `EXAMPLES:`, no `NOTES:`, no `RAISES:`,
  no free-form labels. The spec's removed `SHALL NOT be declared as SERIAL`
  sentence does NOT become a `SHALL NOT:` contract field — it becomes an
  `INVARIANTS` entry stating the positive contract ("PK columns are declared
  `INTEGER GENERATED ALWAYS AS IDENTITY`; the legacy `SERIAL PRIMARY KEY`
  pseudo-type is not used").
- **`RATIONALE` is Q/A format only**, answering "why is this entity shaped
  this way?". It is NOT a junk drawer for arbitrary prose, NOT a place to
  restate `PURPOSE`, NOT a place to dump the trimmed spec text verbatim. One
  Q and one A per item; multi-item allowed when there are distinct reasons.
- **`PURPOSE` answers WHY, not WHAT.** If the existing `PURPOSE` already
  answers WHY, leave it — do not churn for churn's sake.
- **Every `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity.**
  For a function: the `def` line, the entire body, any nested `BLOCK_*`
  regions, and the trailing blank line. A region that closes before its
  entity ends (e.g. wrapping only the contract comment block) is a defect.
  The contract comment block (`# PURPOSE:`, `# INVARIANTS:`, etc.) sits
  INSIDE the region, ABOVE the entity's first line; the `# region` marker
  opens the block, the contract fields follow, then the entity, then
  `# endregion`. Nesting is allowed: `BLOCK_*` regions live INSIDE the
  enclosing `FUNC_*` / `METHOD_*` / `CLASS_*` region; the outer `# endregion`
  comes after the last nested `# endregion`. The existing
  `FUNC_apply_schema` in `postgres_schema.py` already encloses its full
  function (lines 23-72) with its five nested `BLOCK_*` regions correctly
  ordered; this change does NOT add, move, or remove any region marker — it
  only enriches the contract fields above the `def apply_schema(...)` line
  and above the module's first statement.
- **Comment-only diff.** No code logic, signature, decorator choice, docstring
  semantics, or import changes. Edits are contract-field enrichment inside the
  existing `MODULE_CONTRACT` and `FUNC_apply_schema` regions. The module
  docstring (the first `"""..."""` after `# endregion MODULE_CONTRACT`) is NOT
  touched. The five nested `BLOCK_*` regions inside `FUNC_apply_schema`
  (`BLOCK_open_connection`, `BLOCK_apply_schema`, `BLOCK_handle_existing`,
  `BLOCK_rollback`, `BLOCK_close`) stay as-is.

## 1. Apply the postgres-schema-apply spec delta

- [x] 1.1 Apply the 4 MODIFIED requirements from
  `openspec/changes/postgres-schema-apply-spec-trim/specs/postgres-schema-apply/spec.md`
  to `openspec/specs/postgres-schema-apply/spec.md`, replacing each original
  requirement block in place. Preserve requirement header text exactly
  (whitespace-insensitive match) so OpenSpec recognizes the MODIFIED
  operation. Headers to match (in spec order):
  `Transactional schema application`,
  `Error reporting on existing schema`,
  `Bootstrap DO block`,
  `Full latest snapshot with no inline ALTERs`.
- [x] 1.2 Confirm the trimmed main spec contains zero `SHALL NOT` / `shall
  not` instances in requirement bodies (the one enumerated in `proposal.md`
  Why § 1 — `SHALL NOT be declared as SERIAL PRIMARY KEY` — is gone from the
  body). Confirm every observable behavioral scenario (`#### Scenario:` count)
  is preserved: pre 11 → post 11. Confirm the relocated prose enumerated in
  `proposal.md` Why § 2-5 is gone from the spec body (the procedural SQL
  ordering narrative on enum types / triggers; the redundant
  `username/port` column enumeration; the `Schema evolution is expressed via
  migration files, not via inline ALTERs` aside; the `magic 0 sentinel`
  sentence; the `(SQL:2003 identity columns, PostgreSQL 10+)` parenthetical).
  Confirm the per-status CHECK-contract SQL fragment on
  `task_status_field_invariants`, the `node_ncpus_positive` SQL fragment
  `(ncpus IS NULL OR ncpus > 0)`, and the `SMALLINT DEFAULT NULL` declaration
  STAY in the body (they are the normative statement of the business rules).
- [x] 1.3 `openspec validate --all --json` passes (exit 0). The change
  validates AND the trimmed main spec validates AND no other spec regresses
  (currently 20 specs + the in-flight change set).

## 2. yascheduler/infra/persistence/postgres_schema.py — enrich MODULE_CONTRACT and FUNC_apply_schema

The existing `MODULE_CONTRACT` (lines 2-7) and `FUNC_apply_schema` (lines
23-72) regions already enclose their full entities; this task only enriches
the contract fields inside each region. No region markers are added, moved,
or removed. The five nested `BLOCK_*` regions inside `FUNC_apply_schema`
stay as-is. Only defined GRACE fields are used; every `PURPOSE` answers WHY
(both existing `PURPOSE` lines already answer WHY and stay unchanged).

- [x] 2.1 Enrich existing `MODULE_CONTRACT`: keep `PURPOSE` (current text
  "Bootstrap the database schema from scratch (fresh database, test fixtures,
  CI) in a single transactional apply — idempotent so repeated invocation
  does not corrupt existing databases." answers WHY — keep). Keep `SCOPE`
  and `DEPENDENCIES` and `KEYWORDS`. Add `INVARIANTS`:
  - `schema.sql` is the canonical full latest snapshot of the database —
    every `CREATE TABLE` statement includes all current columns; no inline
    `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements appear.
  - Primary-key columns `yascheduler_nodes.node_id` and
    `yascheduler_tasks.task_id` are declared
    `INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY`; the legacy
    `SERIAL PRIMARY KEY` PostgreSQL-specific pseudo-type is not used.
  - `schema.sql` declares enum types (`NODE_STATUS`, `TASK_STATUS`) before
    the `CREATE TABLE` statements that reference them; the shared
    `YASCHEDULER_TOUCH_UPDATED_AT()` trigger function and per-table triggers
    (`yascheduler_tasks_touch_updated_at`,
    `yascheduler_nodes_touch_updated_at`) are declared after the
    `CREATE TABLE` statements — PostgreSQL requires types and tables to
    exist before dependent objects can reference them.
  - `apply_schema` is the sole consumer of `schema.sql`; `apply_migrations`
    consumes the migration files in `sql/migrations/` separately.
  Add `RATIONALE` Q/A:
  - Q1: why is `schema.sql` maintained as a hand-edited full snapshot instead
    of being generated from migrations? A1: a fresh database must reach the
    latest schema in a single transactional apply (for CI, test fixtures,
    and fresh deployments) without replaying every historical migration;
    maintaining the snapshot by hand is the tradeoff, and the migration edit
    procedure (see the `db-migrations` spec) requires updating both
    `schema.sql` and the migration files in lockstep.
  - Q2: why are primary-key columns declared `INTEGER GENERATED ALWAYS AS
    IDENTITY` instead of `SERIAL PRIMARY KEY`? A2: SQL:2003 identity columns
    are the modern PostgreSQL standard (PostgreSQL 10+) — SQL-standard,
    decoupled from the underlying sequence object, and aligned with the
    project's `2026-07-03-serial-to-generated-identity` migration;
    `SERIAL` is a legacy PostgreSQL-specific pseudo-type retained only for
    backwards compatibility.
  - Q3: why is `yascheduler_nodes.ncpus` declared `SMALLINT DEFAULT NULL`
    with a `node_ncpus_positive` CHECK instead of using `0` as a "no
    operator limit" sentinel? A3: a magic `0` sentinel overloaded a numeric
    column with a non-numeric meaning and forced every caller to remember
    the special case; `NULL` is the SQL-native representation of "no value"
    and the `CHECK (ncpus IS NULL OR ncpus > 0)` constraint makes the
    contract enforceable at the database (see archived
    `2026-07-13-node-ncpus-as-config`).
- [x] 2.2 Enrich existing `FUNC_apply_schema`: keep `PURPOSE` (current text
  "Bootstrap the database from scratch — apply all DDL in one transaction so
  CI, test fixtures, and fresh deployments start with a consistent schema
  without manual setup." answers WHY — keep). Add `REQUIRES`:
  - `config` is a validated `PostgresDbConfig` with a reachable PostgreSQL
    database; the connecting user has `CREATE TABLE`, `CREATE TYPE`, and
    `CREATE TRIGGER` privileges on the target database.
  Add `ENSURES`:
  - On success, the database contains every table, enum type, trigger
    function, and `CHECK` constraint declared in `schema.sql`; the bootstrap
    DO block has either created `yascheduler_migrations` and seeded it to
    the latest migration (fresh database), created the tracker without a
    seed row (legacy database), or left the tracker untouched (modern
    database); the connection is closed.
  - On any failure, the open transaction is rolled back (best-effort), the
    original exception is re-raised, and the connection is closed.
  Add `INVARIANTS`:
  - Synchronous — opens ONE pg8000 native `Connection` for the whole apply
    and closes it in `finally`.
  - Wraps the entire `schema.sql` body in a single `BEGIN` / `COMMIT`
    transaction — partial-failure leaves no half-applied schema.
  - On `DatabaseError`, issues best-effort `ROLLBACK`, logs
    `"Database already initialized!"` when the error message contains
    `"already exists"`, and re-raises regardless.
  - On any other `BaseException`, issues best-effort `ROLLBACK` and
    re-raises.
  - Closes the connection in `finally` regardless of outcome.
- [x] 2.3 Verify
  `uv run ruff check yascheduler/infra/persistence/postgres_schema.py`
  and `uv run ruff format --check yascheduler/infra/persistence/postgres_schema.py`
  pass; `uv run pytest -m integration tests/integration/test_postgres_schema.py`
  is green (assume Docker running).

## 3. End-to-end verify

- [x] 3.1 Manual scan: every `# region MODULE_CONTRACT`, `FUNC_*`, `BLOCK_*`
  in `yascheduler/infra/persistence/postgres_schema.py` has a paired
  `# endregion` and wraps the entire entity. No orphaned trailing code
  outside the region; no region closes before its entity ends.
  `FUNC_apply_schema` continues to enclose the full function body including
  the docstring, all five nested `BLOCK_*` regions, and the trailing blank
  line. The nested `BLOCK_*` regions' `# endregion` markers continue to
  appear BEFORE the outer `# endregion FUNC_apply_schema`.
- [x] 3.2 Manual scan: no invented GRACE field names anywhere in the touched
  file — only `PURPOSE` / `SCOPE` / `INVARIANTS` / `USECASES` /
  `DEPENDENCIES` / `RATIONALE` / `KEYWORDS` / `REQUIRES` / `ENSURES`.
  Specifically, NO `SHALL NOT:` field, NO `RAISES:` field, NO `EFFECTS:`
  field, NO `EXAMPLES:` field, NO `NOTES:` field anywhere.
- [x] 3.3 Manual scan: every `PURPOSE` field answers WHY, not WHAT.
  Spot-check `MODULE_CONTRACT` and `FUNC_apply_schema`. Both existing
  `PURPOSE` lines already answer WHY and are unchanged.
- [x] 3.4 Manual scan: every `RATIONALE` field is in Q/A format
  ("Q: ... A: ..."). No `RATIONALE` block contains free-form prose that
  should be in `PURPOSE` / `INVARIANTS` / `SCOPE`. Specifically, the
  `schema.sql`-as-snapshot / `IDENTITY`-vs-`SERIAL` /
  `ncpus`-`NULL`-vs-`0` rationale live as Q/A pairs inside
  `MODULE_CONTRACT.RATIONALE` of `postgres_schema.py`.
- [x] 3.5 `openspec validate --all --json` passes (exit 0); the trimmed
  `postgres-schema-apply` spec validates AND the change
  `postgres-schema-apply-spec-trim` validates AND no other spec regresses.
- [x] 3.6 `uv run pytest -m unit` — all unit tests pass (no behavior
  changed; markup-only diff).
- [x] 3.7 `uv run pytest -m integration` — all integration tests pass
  (assume Docker running). Specifically
  `tests/integration/test_postgres_schema.py` exercises the four
  requirements: `test_apply_schema_succeeds` (Transactional application),
  `test_apply_schema_tables_exist` (Transactional application),
  `test_apply_schema_raises_on_existing` (Error reporting),
  `test_apply_schema_has_node_ncpus_positive_check` (Full latest snapshot).
- [x] 3.8 `uv run ruff check .` and `uv run ruff format --check .` pass on
  all changed files.
- [x] 3.9 `uv run lint-imports` passes (no new imports introduced;
  markup-only edits).
- [x] 3.10 Confirm no public-surface change: no CLI command,
  console_script, INI config key, DB schema, public API, `schema.sql`
  content, or log-format change in the diff. The diff is
  `# region` / `# endregion` markup + comment-field enrichment + spec
  text trim only.
