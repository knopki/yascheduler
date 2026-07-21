## 1. YaLogger, LogFormatter, and get_logger factory core

- [x] 1.1 Create `yascheduler/shared/log.py` with `YaLogger(logging.Logger)` subclass exposing `trace(block: str, /, **fields)` that calls `self.debug(block, extra={"block": block, "fields": fields}, stacklevel=2)`
- [x] 1.2 Add `LogFormatter(logging.Formatter)` to `yascheduler/shared/log.py` with two rendering branches: trace records (carrying `record.fields`) render `[%(shortname)s][%(funcName)s][%(message)s]` + deterministic sorted `key=value` pairs from `record.fields`; user-facing records render plain `%(levelname)s %(name)s: %(message)s`. Set `record.shortname` from `record.name.removeprefix("yascheduler.")` before formatting.
- [x] 1.3 Add `get_logger(name: str) -> YaLogger` factory to `yascheduler/shared/log.py` that does `logger = logging.getLogger(f"yascheduler.{name}")`, `logger.__class__ = YaLogger`, `return logger`. The factory owns the `yascheduler.` namespace prefix and the runtime reclassing; it SHALL NOT use `logging.setLoggerClass`. Remove the existing `logging.setLoggerClass(YaLogger)` call and the `from yascheduler.shared import YaLogger` import from `yascheduler/__init__.py`; the package init SHALL NOT mutate the process-global logger class.
- [x] 1.4 Add `M-LOGGING` entry to `docs/knowledge-graph.xml` for `yascheduler/shared/log.py` (TYPE=UTILITY, STATUS=implemented) with `<purpose>`, `<path>`, `<depends>` and annotations for `class-YaLogger`, `class-LogFormatter`, and `fn-get_logger` (the factory annotation is added when task 1.3 lands)
- [x] 1.5 Verify outcome: a unit test calls `get_logger("M-TEST")`, asserts `isinstance(result, YaLogger)`, asserts `result.name == "yascheduler.M-TEST"`, calls `result.trace("TEST_BLOCK", k=1)`, captures the record, and asserts `record.block == "TEST_BLOCK"` and `record.fields == {"k": 1}` and `record.funcName` reflects the test function. A second call to `get_logger("M-TEST")` returns the same object (cached), verifying idempotent reclassing.

## 2. Guard tests enforce trace discipline and M-ID validity

- [x] 2.1 Add `tests/unit/test_log_scope_discipline.py` with `test_no_raw_debug_calls_in_yascheduler`: AST-walk `yascheduler/**/*.py`, fail on any `.debug(` attribute call, exempt `yascheduler/shared/log.py` (the `YaLogger.trace` implementation calls `self.debug` internally)
- [x] 2.2 Add `test_logger_names_are_real_m_ids`: AST-walk `yascheduler/**/*.py`, collect every `get_logger("M-...")` call (an `ast.Call` whose `func` resolves to `get_logger`, with a single string-literal argument), parse `docs/knowledge-graph.xml`, assert each literal matches a real `<M-*>` tag name. Additionally assert that no `logging.getLogger(...)` call inside `yascheduler/` outside `yascheduler/shared/log.py` is used for module-level logger binding (the factory is the only sanctioned path).
- [x] 2.3 Verify outcome: both guard tests pass under `uv run pytest -m unit` without external resources, and each fails loudly when fed a synthetic violation (a raw `.debug(`, a fabricated `get_logger("M-FABRICATED-NONEXISTENT")`, or a direct `logging.getLogger("yascheduler.M-...")` binding)

## 3. configure_logger wires LogFormatter

- [x] 3.1 Update `configure_logger` in `yascheduler/entrypoints/cli/daemon_common.py` to instantiate one `LogFormatter` and call `setFormatter` on both the `StreamHandler(sys.stderr)` and the `FileHandler` (when `log_file is not None`)
- [x] 3.2 Update the `configure_logger` contract block comment to document the `LogFormatter` wiring; preserve `backoff`/`asyncssh` ERROR suppression and `captureWarnings(True)` behavior unchanged
- [x] 3.3 Verify outcome: a unit test calls `configure_logger(log_file=None, level=logging.INFO)` and asserts both that the stderr handler has a `LogFormatter` and that no `FileHandler` is attached; a second test with a temp file path asserts both handlers carry a `LogFormatter`

## 4. M-ID namespaced logger names via get_logger factory

- [x] 4.1 Replace every `logging.getLogger(__name__)`, every `logging.getLogger("yascheduler.M-...")`, and every ad-hoc logger name (`"Orchestrator"`, `"SSHMachineSession"`, `"SSHMachineRepository"`, `"test_..."`) in `yascheduler/` with `get_logger("M-...")` (imported via `from yascheduler.shared import get_logger`) using the M-ID matching the module's `docs/knowledge-graph.xml` `<path>` mapping. The `yascheduler.` prefix is no longer written at the callsite — the factory applies it.
- [x] 4.2 Audit all module-level logger bindings in `yascheduler/application/` (`allocate_task.py`, `consume_task.py`, `submit_task.py`, `abandon_node.py`, `deallocate_nodes.py`, `query_tasks.py`, `message_bus.py`, `orchestrator.py`) and `yascheduler/infra/` (`notifier/webhook.py`, `cloud/manager.py`, `cloud/provider_selection.py`, `ssh/session.py`, `ssh/repository.py`, `ssh/platform/linux.py`, `ssh/platform/windows.py`, `ssh/operations/occupancy.py`, `persistence/postgres_schema.py`, `persistence/postgres_migrations.py`, `persistence/postgres_uow.py`) and bind each via `get_logger("M-...")`. Also migrate the entrypoints CLI module (`show_nodes.py`) currently using `logging.getLogger("yascheduler.M-ENTRYPOINTS-CLI-SHOW-NODES").trace(...)` inline.
- [x] 4.3 Verify outcome: `test_logger_names_are_real_m_ids` passes (every `get_logger(...)` literal references a real `<M-*>` tag and no `logging.getLogger(...)` module-level binding remains in `yascheduler/` outside `yascheduler/shared/log.py`); `uv run zuban check` is green (the factory return type makes every `log.trace(...)` callsite statically valid)

## 5. DEBUG-only trace marker migration

- [x] 5.1 Convert the DEBUG-only marker emits in `allocate_task.py` (`ALLOCATED` l.139, `CLOUD` l.486, `DEDUP` l.491, `NO_PROVIDER` l.508, `CLOUD_DONE` l.412, `SESSION_FAILED` l.228) from hand-assembled `[Module][fn][BLOCK] k=%s` strings to `log.trace("BLOCK", k=v)` calls. NOTE: `TMP_CLEANUP_FAILED` (l.308), `CLOUD_FAILED` (l.344), `PERSIST_FAILED` (l.386), `DEALLOC_FAILED` (l.400) are `logger.error(...)` (user-facing, non-test-targeted) — they go to task 7 cleanup, NOT here. `NO_PLATFORM` (l.477) is `logger.warning(...)` (user-facing, non-test-targeted) — also task 7 cleanup.
- [x] 5.2 Convert the DEBUG-only marker emits in `orchestrator.py` (`ALLOCATE`, `CONSUME`, `MACHINE_GONE`, `BG_JOB_ENDED`) to `log.trace(...)` calls
- [x] 5.3 Convert the DEBUG-only marker emits in `infra/cloud/manager.py` (`CREATE_VM`, `DONE`, `SETUP_NODE`, `READY`, `CONNECT`, `CLOUD_INIT`, `THROTTLE`, `NO_CLOUD`, `UNSUPPORTED`, `NO_CONFIG`, `SETUP_FAILED`, `DISCONNECT_FAILED`) to `log.trace(...)` calls
- [x] 5.4 Convert the DEBUG-only marker emits in `infra/cloud/provider_selection.py` (`MAXED`, `NO_PLATFORM`, `NONE`, `CHOSEN`) to `log.trace(...)` calls
- [x] 5.5 Convert the DEBUG-only marker emits in `infra/ssh/session.py` (`CANCEL_MONITOR`), `infra/ssh/repository.py` (`CONNECT`, `DETECT`), `infra/ssh/platform/linux.py` (`YIELD`, `DONE`, `UPLOAD`, `EXTRACT`, `DOWNLOAD`, `UPGRADE`, `INSTALL`), `infra/ssh/platform/windows.py` (`UPLOAD`, `EXTRACT`, `DOWNLOAD`), `infra/ssh/operations/occupancy.py` (`PGREP`, `PGREP_FREE`, `CHECK_CMD`, `NO_CHECK`) to `log.trace(...)` calls
- [x] 5.6 Convert the DEBUG-only marker emits in `infra/persistence/postgres_schema.py` (`OPEN_CONNECTION`, `APPLY_SCHEMA`, `HANDLE_EXISTING`, `ROLLBACK`, `CLOSE`) and `infra/persistence/postgres_migrations.py` (`APPLY_SQL`, `TRACKER_RECORD`, `OPEN_CONNECTION`, `READ_LAST`, `APPLY_PENDING`, `CLOSE`) to `log.trace(...)` calls
- [x] 5.7 Convert the DEBUG-only marker emits in `application/query_tasks.py` (`EMPTY_DISPATCH`) and any remaining DEBUG markers in `application/` to `log.trace(...)` calls
- [x] 5.8 Convert the DEBUG-only marker emits in `application/deallocate_nodes.py` (`DISABLE` l.65, `CLOUD_DELETE` l.77, `REMOVE` l.87, `DISABLE` l.156) to `log.trace(...)` calls. NOTE: `deallocate_nodes.py:103` is `logger.error(...)` (user-facing, non-test-targeted) — it goes to task 7 cleanup, NOT here. The `CLOUD_DELETE` DEBUG marker at l.77 is the producing callsite for the e2e assertion migrated in task 8.3.
- [x] 5.8 Verify outcome: `test_no_raw_debug_calls_in_yascheduler` passes (no `.debug(` calls remain in `yascheduler/` outside `yascheduler/shared/log.py`), and the trace records render with `[M-ID][funcName][BLOCK] k=v` via `LogFormatter`

## 6. Split test-targeted user-facing emits into trace plus narrative

- [x] 6.1 Split `webhook.py:110` (`RETRY` warning) into `log.trace("RETRY", url=url)` + `log.warning("webhook retry to %s", url)`; update `tests/unit/test_webhook_handler.py` to assert on `record.block == "RETRY"` and `record.fields["url"]` instead of `"RETRY" in record.message`
- [x] 6.2 Split `abandon_node.py:59` (`CLOUD_DELETE_FAILED` error) into `log.trace("CLOUD_DELETE_FAILED", node_id=..., hostname=..., cloud=..., err=...)` + `log.error(...)` narrative; update `tests/unit/test_abandon_node.py` to assert on `record.block`
- [x] 6.3 Split `abandon_node.py:86` (`AMBIGUOUS_TRACKER` warning) into `log.trace("AMBIGUOUS_TRACKER", node_id=..., hostname=..., count=...)` + `log.warning(...)` narrative; update `tests/unit/test_abandon_node.py` (both the presence assertion at line 249 and the absence assertion at line 223) to use `record.block`
- [x] 6.4 Split `orchestrator.py:300` (`CONNECT_RETRY_STATIC` warning) into `log.trace("CONNECT_RETRY_STATIC", ...)` + `log.warning(...)` narrative; update `tests/unit/test_connect_machine_consumer.py:454` to assert on `record.block`
- [x] 6.5 Split `orchestrator.py:316` (`CONNECT_RETRY` warning) into `log.trace("CONNECT_RETRY", ...)` + `log.warning(...)` narrative; update `tests/unit/test_connect_machine_consumer.py:184` to assert on `record.block`
- [x] 6.6 Split `orchestrator.py:329` (`CONNECT_ABANDON` error) into `log.trace("CONNECT_ABANDON", ...)` + `log.error(...)` narrative; update `tests/unit/test_connect_machine_consumer.py:218` to assert on `record.block`
- [x] 6.7 Split `orchestrator.py:345` (`ABANDON_FAILED` error) into `log.trace("ABANDON_FAILED", ...)` + `log.error(...)` narrative; update `tests/unit/test_connect_machine_consumer.py:276` to assert on `record.block`
- [x] 6.8 Split `orchestrator.py:630` (`CONSUMER_ERROR` error) into `log.trace("CONSUMER_ERROR", ...)` + `log.error(...)` narrative; update `tests/unit/test_orchestrator_consumer_resilience.py:195` and `:244` to assert on `record.block`
- [x] 6.9 Split `orchestrator.py:664` (`PRODUCER_ERROR` error) into `log.trace("PRODUCER_ERROR", ...)` + `log.error(...)` narrative; update `tests/unit/test_orchestrator_producer_resilience.py:232` and `:298` to assert on `record.block`
- [x] 6.10 Split `orchestrator.py:249` (`_print_stats` `ERROR`) into `log.trace("ERROR", context="stats", err=...)` + `log.error("stats print failed: %s", err)` narrative; update `tests/unit/test_orchestrator_producer_resilience.py:544` to assert on `record.block` and `record.fields["context"] == "stats"`
- [x] 6.11 Split `ssh/repository.py:242` (`CPUs` info) into `log.trace("CPUS", hostname=..., ncpus=...)` + `log.info("connected to %s (%d CPUs)", hostname, ncpus)` narrative; update `tests/unit/test_ssh_gateway.py:688` to assert on `record.block == "CPUS"` and `record.fields["hostname"]`/`record.fields["ncpus"]`
- [x] 6.12 Verify outcome: all 6 unit test files touched by tasks 6.1–6.11 pass under `uv run pytest -m unit` asserting on `record.block`/`record.fields` instead of `getMessage()` substrings (`test_webhook_handler.py`, `test_abandon_node.py`, `test_connect_machine_consumer.py`, `test_orchestrator_consumer_resilience.py`, `test_orchestrator_producer_resilience.py`, `test_ssh_gateway.py`); the narrative WARN/ERROR/INFO records carry no grace markers. The 3 e2e test files (`test_full_cycle.py`, `test_hetzner_live.py`, `test_allocate_task_node_pairing.py`) are migrated in task 8.

## 7. Cleanup non-test-targeted user-facing emits to pure narrative

- [x] 7.1 Rewrite `infra/cloud/manager.py:170` (`CREATE_FAILED` error) as plain `log.error("cloud create failed for %s: %s", hostname, err)` narrative with no grace block marker and no `trace()` double
- [x] 7.2 Rewrite `infra/cloud/manager.py:99` (`[CloudProvisionerImpl] stop` info) as plain `log.info("cloud provisioner stop — draining machine_repository")` narrative with no grace block marker
- [x] 7.3 Rewrite `orchestrator.py:803` (`CLOUDS_STOP_FAILED` warning) as plain `log.warning("clouds stop failed: %s", e)` narrative with no marker and no `trace()` double
- [x] 7.4 Rewrite `orchestrator.py:810` (`DISCONNECT_ALL_FAILED` warning) as plain `log.warning("disconnect all failed: %s", e)` narrative with no marker and no `trace()` double
- [x] 7.5 Rewrite `orchestrator.py:818` (`HTTP_CLOSE_FAILED` warning) as plain `log.warning("http close failed: %s", e)` narrative with no marker and no `trace()` double
- [x] 7.6 Rewrite `webhook.py:86` (`GIVEUP` exception) as plain `log.exception("webhook giveup: %s", event.webhook_url)` narrative with no grace block marker and no `trace()` double
- [x] 7.7 Rewrite `allocate_task.py:308` (`TMP_CLEANUP_FAILED` error), `:344` (`CLOUD_FAILED` error), `:386` (`PERSIST_FAILED` error), `:400` (`DEALLOC_FAILED` error) as plain `log.error(...)` narrative with no grace block marker and no `trace()` double
- [x] 7.8 Rewrite `allocate_task.py:477` (`NO_PLATFORM` warning) as plain `log.warning(...)` narrative with no marker and no `trace()` double
- [x] 7.9 Rewrite `deallocate_nodes.py:103` (error) as plain `log.error(...)` narrative with no marker and no `trace()` double
- [x] 7.10 Verify outcome: the cleanup-path emits render as plain narrative under `LogFormatter`, no grace markers leak into user-facing output, and no test regresses

## 8. Migrate log-driven e2e test assertions to structured fields

- [x] 8.1 Update `tests/e2e/test_full_cycle.py:47` and `:365` to assert on `record.block == "ALLOCATED"` and `record.fields["ip"]`/`record.fields["task_id"]` instead of `_ALLOCATED_MARKER in r.getMessage()`
- [x] 8.2 Update `tests/e2e/test_hetzner_live.py:70` and `:435` to assert on `record.block == "CLOUD_DONE"` and `record.fields["ip"]`/`record.fields["cloud"]` instead of `_CLOUD_DONE_MARKER in r.getMessage()`
- [x] 8.3 Update `tests/e2e/test_hetzner_live.py:71` and `:457` to assert on `record.block == "CLOUD_DELETE"` and `record.fields["cloud"]` instead of `_CLOUD_DELETE_MARKER in r.getMessage()`
- [x] 8.4 Update `tests/unit/test_allocate_task_node_pairing.py:201` to assert on `record.block == "ALLOCATED"` and `record.fields["hostname"]`/`record.fields["node_id"]` instead of `"[ALLOCATED]" in r.getMessage()`
- [x] 8.5 Update `tests/e2e/conftest.py` `log_records` fixture docstring (lines 5, 22, 27) to describe structured-field assertions rather than `getMessage()` substring matching
- [x] 8.6 Verify outcome: `uv run pytest -m e2e` (with testcontainers Postgres + SSH) passes with structured-field assertions; the `log_records` fixture captures trace records via propagation from M-ID-namespaced loggers

## 9. Update GRACE-lite contract documentation

- [x] 9.1 Rewrite the GRACE-lite "Logging & Verification" block in `AGENTS.md` to mandate `log.trace("BLOCK", **fields)` instead of hand-assembled `logging.debug("[Module][function][BLOCK] msg", extra={...})`; document the `record.block`/`record.fields` contract for tests, the M-ID namespaced logger name convention, and the `LogFormatter` rendering contract
- [x] 9.2 Update any GRACE-lite block-anchor documentation in `AGENTS.md` that references the old `[Module][function][BLOCK]` hand-assembly pattern to reference `log.trace(...)` and the auto-captured `funcName`
- [x] 9.3 Verify outcome: `AGENTS.md` GRACE-lite section describes the new contract with no reference to hand-assembled marker strings; `python3 scripts/grace_check.py` passes

## 10. Validation and regression sweep

- [x] 10.1 Run `openspec validate reform-grace-logging --json` and confirm the change validates cleanly
- [x] 10.2 Run `uv run pytest -m unit` and confirm all unit tests (including the two guard tests and the 9 migrated assertion files) pass
- [x] 10.3 Run `uv run pytest -m integration` and confirm no integration test regresses from the logger name changes
- [x] 10.4 Run `uv run pytest -m e2e` (with testcontainers) and confirm the e2e suite passes with structured-field assertions
- [x] 10.5 Run static checks: `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`; fix any violations
- [x] 10.6 Run `python3 scripts/grace_check.py` and confirm the GRACE-lite XML + source checks pass (knowledge-graph M-LOGGING entry, M-ID logger names match `<path>` mappings)
- [x] 10.7 Verify outcome: the full validation suite passes — `openspec validate`, `pytest -m unit`, `pytest -m integration`, `pytest -m e2e`, `zuban`, `ruff`, `lint-imports`, `grace_check.py` — confirming the big-bang migration is complete and no contract drifted