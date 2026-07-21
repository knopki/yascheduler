## Why

`openspec/specs/testing-unit/spec.md` (424 lines, 19 requirements, 44 scenarios)
interleaves actual SHALL requirements with content kinds that GRACE assigns to
code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 6 distinct
   instances in requirement bodies and prose enumerating removed APIs or
   non-behavior as normative requirements:
   - "Tests SHALL construct `Task` / `NewTask` with the typed fields directly
     (no `TaskContext` wrapper, no `context=` kwarg)." — `TaskContext` was
     removed in `2026-07-06-drop-task-context-entity`.
   - "`MachineOperations` Protocol is removed; operations-side collaborators
     (`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`) are concrete
     classes and are not subject to Protocol conformance checks." —
     `MachineOperations` was removed in
     `2026-07-13-connected-machine-runtime-only`.
   - "The project SHALL NOT retain the former 'trace-only DEBUG discipline'
     guard (raw `.debug(` calls are now the sanctioned trace path via
     `debug(msg, extra=...)`), the 'M-ID validity and factory-only binding'
     guard (the `get_logger` factory and M-ID logger names are removed), or
     any synthetic-violation meta-tests specific to those removed guards." —
     `get_logger` / M-ID were removed in
     `2026-07-15-switch-to-standard-logging`; raw `.debug(...)` IS the
     sanctioned trace path under stdlib logging.
   - "The value objects (`LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`,
     `Config`, `Engine`, `EngineRepository`, `ConfigCloud*`) SHALL be asserted
     frozen (`@dataclass(frozen=True)`) with no `from_config_parser_section` or
     `get_valid_config_parser_fields` methods." — parser methods were removed
     in `2026-06-26-config-aggregate-to-entrypoints`; the
     `@dataclass(frozen=True)` decorator IS the frozen assertion.
   - "`ConnectedMachine` tests SHALL construct the entity with `node_id` and
     `platform` keyword arguments only (NOT `hostname` or `ncpus`)." —
     `hostname` / `ncpus` were removed from the `ConnectedMachine` constructor.
   - "`occupy()` SHALL raise `MachineBusyError(node_id)` — assertions SHALL
     verify `e.node_id` and SHALL NOT access `e.hostname`." — the `hostname`
     attribute was removed from `MachineBusyError`.
   Every one is either already asserted by a positive Gherkin scenario (the
   `Scenario: ConnectedMachine occupy on BUSY raises MachineBusyError with
   node_id only` asserts `not hasattr(e, "hostname")`; the
   `Scenario: Value objects have no parser methods` asserts no
   `from_config_parser_section` / `get_valid_config_parser_fields`; the
   `Scenario: Exception hierarchy and field carrying` asserts `MachineBusyError`
   stores `node_id` only) or describes a non-existent code path dressed up as a
   normative requirement. The prose is drift bait — every guard describes a
   refactor that already shipped.
2. **Implementation summaries duplicated verbatim by their own scenarios**:
   - "`Yascheduler.queue_submit_task_async` MUST call
     `make_cli_deps(config).submit(label, metadata, engine_name)` and return
     its result." — the
     `Scenario: Yascheduler.queue_submit_task_async uses make_cli_deps` asserts
     the exact call shape ("`make_cli_deps` is called once with the client's
     `config`, `deps.submit` is awaited once with `("t", {"k": "v"}, "fleur")`,
     and the awaited return value is returned to the caller").
   - "`Orchestrator` initialization creates 4 `UniqueQueue` instances with
     correct names and config-derived maxsizes, `start()` creates background
     tasks, `stop()` cancels tasks and cleans up, cancellation propagates to
     producer-consumer loops, and concurrency limits are passed as
     `workers_num`." — the `Scenario: Orchestrator start creates background
     tasks` asserts the observable piece.
   - "Tests SHALL construct the client with a `FakeCLIDeps`-returning
     `deps_factory` whose `uow_factory()` returns a `FakeUnitOfWork` carrying
     a `FakeTaskRepository`." — fixture-construction guidance, not a
     requirement; the five scenarios under the same requirement assert the
     observable routing and shape.
   - "`WebhookPayload` SHALL hold `task_id`, `status`, and `custom_params`
     fields. Default `custom_params` is empty dict." — the
     `Scenario: WebhookPayload defaults custom_params to empty dict` asserts
     the only observable piece.
   These belong in `INVARIANTS` on the owning entity (e.g. the
   `make_cli_deps(config).submit(...)` call shape lives on
   `METHOD_queue_submit_task_async` INVARIANTS in `client.py` — already
   absorbed by `dependency-injection-spec-trim`; the `WebhookPayload` field
   shape lives on `CLASS_WebhookPayload` INVARIANTS in
   `yascheduler/infra/notifier/webhook.py` — already present); the spec body
   restating them is drift bait.
3. **Domain-contract restatements that duplicate other specs**:
   - "Task.error column format contract: bare human strings for
     `reject`/orchestrator `fail`, `"Download error: <path>: <msg>, ..."` for
     consume `fail`, `NULL`/`None` on success" — a domain contract that belongs
     on `Task.fail` / `Task.reject` / `Task.complete` `ENSURES` (owned by the
     `domain-entities` spec, already trimmed by
     `2026-07-17-domain-entities-spec-trim`).
   - The exception-class enumeration in `Domain exception hierarchy` — every
     class name + attribute list duplicates the `domain-exceptions` spec
     (already trimmed by `2026-07-18-domain-exceptions-spec-trim`).
   - The use-case branch enumeration in `Application use cases` — duplicates
     the `use-cases` spec (currently being trimmed by `use-cases-spec-trim`).
   - The orchestrator initialization detail (4 `UniqueQueue` instances,
     `workers_num`) — belongs on `CLASS_Orchestrator` INVARIANTS (owned by
     `orchestrator-spec-trim`).
   - The DI factory enumeration — belongs on `CLASS_CLIDeps`,
     `FUNC_make_cli_deps`, `FUNC_make_daemon` INVARIANTS (owned by
     `dependency-injection-spec-trim`).
   - The config value-object frozen / no-parser-methods enumeration — belongs
     on `CLASS_Config` / `CLASS_LocalSettings` / etc. INVARIANTS (owned by
     `config-value-objects-spec-trim`).
   Every restatement is drift bait: if the production contract evolves, the
   testing-unit spec's restatement silently goes stale while the owning spec
   stays correct.
4. **Dedup invariant living in the spec** — the
   "Deduplication in `UniqueQueue` SHALL be keyed on the message `id`. Two
   `UMessage` instances with equal `id` SHALL be treated as duplicates
   regardless of their `payload`. The `payload` field SHALL NOT participate in
   `__eq__` or `__hash__`; therefore an unhashable `payload` (e.g. a `dict`)
   SHALL be accepted at construction and during enqueue/get/item_done
   operations." paragraph answers *why the code is shaped this way* and
   belongs in `INVARIANTS` on `CLASS_UMessage` and `CLASS_UniqueQueue` in
   `yascheduler/application/queue.py`. The two scenarios below the paragraph
   (`UniqueQueue deduplicates identical items`,
   `UniqueQueue deduplicates under concurrent put on a full queue`) assert
   the observable dedup behavior; the invariant paragraph is the
   implementation rationale. `queue.py` is not touched by any other in-flight
   trim (`orchestrator-spec-trim` and `use-cases-spec-trim` both list
   `queue.py` as out of scope), so `testing-unit-spec-trim` owns it cleanly.
5. **One stale requirement** — the `Shared test fixtures` requirement asserts
   "The project SHALL provide spec-compliant mock factories in
   `tests/fixtures/mock_remote_machine.py` and `tests/fixtures/mock_clouds.py`."
   Both files were deleted: `mock_remote_machine.py` was removed in commit
   `3fba272` ("refactor(adapters): remove old remote-machine and clouds
   modules") and `mock_clouds.py` was removed in commit `9d1350c` ("refactor:
   cloud manager to use UoW"). `tests/fixtures/` now contains only an empty
   `__init__.py` (4 lines). The `Scenario: Mock factories provided for remote
   machine and clouds` cannot pass — no test imports either file. The
   requirement is a phantom: it describes code that does not exist.

## What Changes

- **MODIFIED `testing-unit`**: rewrite 18 of the 19 requirements to carry
  only behavioral contracts (SHALL statements + Gherkin scenarios). Remove
  the 6 invented `SHALL NOT` enumerations of removed APIs listed above, the
  4 implementation summaries duplicated verbatim by their own scenarios, the
  domain-contract restatements that duplicate `domain-entities`,
  `domain-exceptions`, `use-cases`, `orchestrator`, `dependency-injection`,
  and `config-value-objects` specs, and the `UniqueQueue` dedup invariant
  paragraph (relocated to code). Every observable behavioral scenario (43 of
  44 — the one phantom "Mock factories provided" scenario goes away with its
  requirement) survives unchanged. No requirement is added, merged, split, or
  renamed; the 18 surviving requirement headers stay identical so OpenSpec
  recognizes the MODIFIED operation.
- **REMOVED `Shared test fixtures`**: the requirement and its single
  scenario are deleted outright — the target files (`mock_remote_machine.py`,
  `mock_clouds.py`) were removed in `3fba272` / `9d1350c` and the scenario
  cannot pass. The `Scenario: Mock factories provided for remote machine and
  clouds` is removed with the requirement.
- Enrich the existing `CLASS_UMessage`, `CLASS_UniqueQueue`, and
  `METHOD_put` regions in `yascheduler/application/queue.py` (the file already
  carries tight `MODULE_CONTRACT` / `CLASS_*` / `METHOD_*` / `BLOCK_*`
  regions with `PURPOSE` / `INVARIANTS` / `SCOPE` / `KEYWORDS`) with the
  dedup invariant that leaves the spec, each in its correct GRACE field:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
    The existing `PURPOSE` lines on `CLASS_UMessage`, `CLASS_UniqueQueue`,
    and `METHOD_put` are already WHY-shaped ("Enable UniqueQueue
    deduplication by identity — decouple message payload from identity...",
    "Prevent the daemon from processing the same task event twice...",
    "Guarantee at-most-once delivery per message ID...") — kept as-is.
  - `INVARIANTS` carries the conditions/contracts that always hold:
    `CLASS_UMessage` gets "`__eq__` and `__hash__` consult `id` only;
    `payload` is excluded from both — an unhashable `payload` (e.g. `dict`)
    is accepted at construction, queue dedup checks, and `item_done`
    tracking.";
    `CLASS_UniqueQueue` gets "Dedup is keyed on `UMessage.id` (via
    `UMessage.__eq__` / `__hash__`); two messages with equal `id` are
    duplicates regardless of `payload`. `_put_lock` serializes the
    check-then-enqueue step so concurrent `put` calls on a full queue
    cannot both enqueue the same item.";
    `METHOD_put` gets "Holds `_put_lock` across the check-then-enqueue step;
    re-checks `_queue` and `_done_pending` membership after acquiring the
    lock to close the check-then-act race a blocking `super().put()` creates
    on a full queue."
  - No `RATIONALE` additions on `queue.py` — the relocated dedup content is
    invariant-shaped (conditions that always hold), not rationale-shaped
    (why the entity is shaped this way). The `MODULE_CONTRACT` already
    carries an `INVARIANTS` line "Dedup is by message ID, not payload — two
    messages with same ID but different payloads are treated as
    duplicates." — kept as the high-level statement; the class-level
    `INVARIANTS` are more precise.
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no
  `NOTES:`, no `RAISES:`, no free-form labels. The spec's removed `SHALL
  NOT` sentences do NOT become a `SHALL NOT:` contract field — they become an
  `INVARIANTS` entry stating the positive contract, or are simply dropped
  when the behavior is already asserted by a positive scenario.
- Every existing `CLASS_*` / `METHOD_*` / `BLOCK_*` region in `queue.py`
  continues to enclose the FULL entity per the Common rules (the regions are
  already correctly wrapped — verified before enrichment). No new regions
  are added; the existing regions are enriched with `INVARIANTS` lines
  inside the contract block (between the `PURPOSE` line and the first code
  line of the entity).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `testing-unit`: requirements slimmed to SHALL statements and behavior
  scenarios; invented `SHALL NOT` negative-space language (6 instances),
  4 implementation summaries duplicated by their own scenarios,
  domain-contract restatements of `domain-entities` / `domain-exceptions` /
  `use-cases` / `orchestrator` / `dependency-injection` /
  `config-value-objects` (each owned by its own spec or in-flight trim), and
  the `UniqueQueue` dedup invariant paragraph relocated out of the spec
  text and into GRACE code contracts on `yascheduler/application/queue.py`.
  The stale `Shared test fixtures` requirement (its target files were
  deleted in `3fba272` / `9d1350c`) is removed outright. No testing
  behavior, scenario, fixture, assertion, pytest marker, or test-file
  structure is added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/testing-unit/spec.md` rewritten — every
  surviving requirement trimmed to behavioral SHALL + scenarios; pre/post
  scenario count compared and MUST remain 44 → 43 (the single
  `Scenario: Mock factories provided for remote machine and clouds` is
  removed with its requirement; all other 43 scenarios are preserved
  verbatim — header, WHEN, THEN). `openspec validate --all --json` must
  still pass after the change.
- **Code (markup only, no logic)**:
  `yascheduler/application/queue.py` — existing `CLASS_UMessage`,
  `CLASS_UniqueQueue`, and `METHOD_put` regions enriched with `INVARIANTS`
  lines inside the contract block. No code logic, signature, decorator,
  docstring semantics, or import changes. Code contracts absorb what
  leaves the spec, comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing unit tests
  (`tests/unit/test_queue.py`,
  `tests/unit/test_domain_model.py`,
  `tests/unit/test_domain_exceptions.py`,
  `tests/unit/test_domain_ports.py`,
  `tests/unit/test_domain_services.py`,
  `tests/unit/test_config.py`,
  `tests/unit/test_persistence_adapter.py`,
  `tests/unit/test_persistence_node_adapter.py`,
  `tests/unit/test_application_use_cases.py`,
  `tests/unit/test_application_orchestrator.py`,
  `tests/unit/test_di.py`,
  `tests/unit/test_cli_behavioral.py`,
  `tests/unit/test_cli_submit.py`,
  `tests/unit/test_cli_check_status.py`,
  `tests/unit/test_cli_show_nodes.py`,
  `tests/unit/test_cli_manage_node.py`,
  `tests/unit/test_cli_smoke.py`,
  `tests/unit/test_client_query.py`,
  `tests/unit/test_characterization.py`,
  `tests/unit/test_checks.py`,
  `tests/unit/test_webhook_handler.py`,
  `tests/unit/test_log_scope_discipline.py`,
  `tests/unit/test_consume_task.py`,
  `tests/unit/test_abandon_node.py`,
  `tests/unit/test_allocate_task_node_pairing.py`,
  `tests/unit/test_allocate_task_failure_modes.py`,
  `tests/unit/test_deallocate_nodes.py`-equivalent coverage via
  `test_application_use_cases.py`,
  `tests/unit/test_orchestrator_start_task_on_machine.py`,
  `tests/unit/test_orchestrator_stop_idempotent.py`,
  `tests/unit/test_orchestrator_consumer_resilience.py`,
  `tests/unit/test_orchestrator_producer_resilience.py`,
  `tests/unit/test_connect_machine_consumer.py`) already assert them. A
  passing `uv run pytest -m unit` run after the change is the regression
  guard.
- **Public surface**: none. No CLI command, console_script, INI config
  key, DB schema, public API, log-format, pytest marker, or test-file
  structure change in the diff. The diff is `# region` / `# endregion`
  markup enrichment (3 `INVARIANTS` lines inside existing regions on
  `queue.py`) + spec text trim only.
- **Pilot scope**: this change ONLY dehydrates the `testing-unit` spec.
  Other specs (`cloud` is handled by `cloud-spec-trim`; `cli` by
  `cli-spec-trim`; `dependency-injection` by `dependency-injection-spec-trim`;
  `config-value-objects` by `config-value-objects-spec-trim`;
  `orchestrator` by `orchestrator-spec-trim`; `use-cases` by
  `use-cases-spec-trim`; `domain-entities` / `domain-exceptions` /
  `domain-ports` / `domain-events-and-dispatch` by their respective
  archived `2026-07-17-*` / `2026-07-18-*` trims; `e2e-testing` by
  `e2e-testing-spec-trim`; `logging` by `logging-spec-trim`;
  `db-migrations` / `postgres-persistence` / `postgres-schema-apply` by
  their respective trims; `ssh-infrastructure` / `engine-config-parsing` /
  `package-facades` / `test-db-integration` are out of scope) are
  explicitly out of scope. Follows the pattern set by `cloud-spec-trim`,
  `dependency-injection-spec-trim`, `orchestrator-spec-trim`,
  `config-value-objects-spec-trim`,
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`,
  `2026-07-18-slim-domain-ports-spec`, `cli-spec-trim`.
- **Non-goals**:
  - No change to any test behavior, assertion, fixture, pytest marker,
    test-file structure, or conftest.
  - No spec split; all trimmed requirements remain in the `testing-unit`
    capability.
  - No markup added to `tests/` (test files are out of trim scope per the
    established pattern). `tests/unit/**` and `tests/fixtures/**` are out
    of capability scope.
  - No rewrite of `yascheduler/domain/entities.py`,
    `yascheduler/domain/exceptions.py`, `yascheduler/domain/ports.py`,
    `yascheduler/domain/services.py` — the domain-contract restatements
    that leave the testing-unit spec are absorbed by the owning specs
    (`domain-entities`, `domain-exceptions`, `domain-ports`,
    `domain-events-and-dispatch`) and their archived trims; the production
    code GRACE contracts there are not edited by this change.
  - No rewrite of `yascheduler/entrypoints/di.py`,
    `yascheduler/entrypoints/client.py`,
    `yascheduler/entrypoints/config.py`,
    `yascheduler/entrypoints/config_parser.py`,
    `yascheduler/application/orchestrator.py`,
    `yascheduler/application/use_cases.py` — the restated DI / config /
    orchestrator / use-case contracts that leave the testing-unit spec are
    absorbed by `dependency-injection-spec-trim`,
    `config-value-objects-spec-trim`, `orchestrator-spec-trim`, and
    `use-cases-spec-trim` respectively. The production code GRACE contracts
    there are not edited by this change.
  - No rewrite of `yascheduler/infra/notifier/webhook.py` — the
    `WebhookPayload` field-shape restatement that leaves the testing-unit
    spec is already present verbatim in `CLASS_WebhookPayload` INVARIANTS
    ("`custom_params` defaults to an empty mapping"). No edit required.
  - The single production-code touch is `yascheduler/application/queue.py`
    — three `INVARIANTS` lines inside existing `CLASS_*` / `METHOD_*`
    regions. No new regions; the trivial methods (`_get`, `get`,
    `task_done`, `item_done`, `psize`, `__init__`) are left unmarked per
    the GRACE proportional rule (one-liners / obvious operations).
