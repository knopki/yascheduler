## 1. Baseline capture

- [x] 1.1 Run `openspec validate --all --json` and record the baseline (currently 32/32 passed) for post-change parity check.
- [x] 1.2 Run `python3 scripts/grace_check.py` and record the baseline warning counts (currently 18 `func-size` warnings, 0 `source-links-ref` warnings). Used to confirm no new warnings introduced.
- [x] 1.3 Run `uv run pytest -m unit` and record the baseline test count. Used to confirm expected reduction after test deletions.

## 2. Inline `get_logger` into `daemonize.py`

**Ordering constraint (design D7): steps 2.x MUST precede step 3.1.**

- [x] 2.1 Update `yascheduler/adapters/cli/daemonize.py` GRACE-lite headers FIRST (top-down per AGENTS.md): widen `MODULE_CONTRACT` SCOPE (line 5) to mention logger configuration; add `_get_logger - Configure and return the yascheduler logger (inlined from scheduler.py)` to `MODULE_MAP` (lines 10-12); append `v1.1.0 - Inline _get_logger from scheduler.py prior to scheduler.py deletion.` to `CHANGE_SUMMARY` (lines 14-15). `MODULE_CONTRACT` DEPENDS (line 6) unchanged — `logging` is stdlib.
- [x] 2.2 Inline the body of `scheduler.get_logger` (`yascheduler/scheduler.py:47-73`) verbatim into `daemonize.py` as a module-private `_get_logger(log_file, level=logging.INFO)`. Keep `logging.basicConfig(level=logging.INFO)` INSIDE `_get_logger` (per design D1: do NOT lift to module top-level — would change import-time behaviour for tests that import `daemonize` without invoking it).
- [x] 2.3 Replace the lazy import `from yascheduler.scheduler import get_logger` (`daemonize.py:42`) with the local `_get_logger(...)` call at line 54.
- [x] 2.4 Manually verify `python3 -c "import yascheduler.adapters.cli.daemonize"` succeeds without importing `yascheduler.scheduler` (check `sys.modules`).

## 3. Delete `scheduler.py`

- [x] 3.1 Delete `yascheduler/scheduler.py`.
- [x] 3.2 Grep-verify no remaining references: `rg "from yascheduler\.scheduler|yascheduler\.scheduler|from \.scheduler"` in `yascheduler/` and `tests/` MUST return zero hits.

## 4. Test deletions and relocations

- [x] 4.1 Move the two `WebhookPayload` construction tests (`TestWebhookPayload` class, `tests/unit/test_scheduler.py:169-192`) into `tests/unit/test_webhook_handler.py`. Update import to `from yascheduler.webhook import WebhookPayload` (already the form used at line 47 of that file). Update destination file's GRACE-lite headers: append `CHANGE_SUMMARY` entry recording the relocation; add `test_webhookpayload_construction` and `test_webhookpayload_default_custom_params` (or similar) to `MODULE_MAP`; widen `MODULE_CONTRACT` SCOPE to mention `WebhookPayload` construction alongside existing scope.
- [x] 4.2 Delete `tests/unit/test_scheduler.py`.
- [x] 4.3 Edit `tests/unit/test_characterization.py`: remove classes `TestSchedulerCreateNewTask`, `TestSchedulerStart`, `TestSchedulerStop` and their now-unused imports. Keep `TestClientQueueSubmitTaskAsync`. Update the file's GRACE-lite headers (MODULE_CONTRACT PURPOSE/SCOPE, MODULE_MAP, CHANGE_SUMMARY) to reflect the surviving scope.
- [x] 4.4 Delete `tests/fixtures/mock_scheduler.py` (whole file — both `make_scheduler` and `create_test_config` have no surviving consumers per design D3).
- [x] 4.5 Edit `tests/unit/test_cli_smoke.py`: remove `test_utils_import_does_not_import_scheduler` (lines 34-45). Restore any helper imports that become unused. Update `MODULE_MAP` if it lists the deleted test (line 14 area).

## 5. Knowledge-graph and source `LINKS:` scrub

**GRACE-lite: graph and contracts first.**

- [x] 5.1 In `docs/knowledge-graph.xml`: remove the `<M-SCHEDULER ...> ... </M-SCHEDULER>` element block (lines 39-52).
- [x] 5.2 In `docs/knowledge-graph.xml`: remove the four `<CrossLink from="M-SCHEDULER" ...>` entries (lines 882, 909, 910, 934).
- [x] 5.3 Scrub the `M-SCHEDULER` token from the `LINKS:` line in each of the 12 surviving source files (preserve other M-IDs on each line): `yascheduler/webhook.py`, `yascheduler/queue.py`, `yascheduler/time.py`, `yascheduler/db.py`, `yascheduler/domain/services.py`, `yascheduler/config/__init__.py`, `yascheduler/config/local.py`, `yascheduler/config/config.py`, `yascheduler/config/engine_repository.py`, `yascheduler/application/allocate_task.py`, `yascheduler/application/consume_task.py`, `yascheduler/application/submit_task.py`. After scrub, `rg "LINKS:.*M-SCHEDULER" yascheduler/` MUST return zero hits.

## 6. ARCHITECTURE.md cleanup

- [x] 6.1 `docs/ARCHITECTURE.md` §1 ASCII diagram: remove the `scheduler.py` line (line 84).
- [x] 6.2 `docs/ARCHITECTURE.md` §2 Component Reference table: remove the `scheduler.py` row (line 120).
- [x] 6.3 `docs/ARCHITECTURE.md` §2.2 last paragraph (line 178): drop `scheduler.py` from the sentence naming db.py consumers (currently "`client.py`, `scheduler.py`, and `CloudProvisionerImpl`").
- [x] 6.4 `docs/ARCHITECTURE.md` §2.9: remove the `scheduler.py` bullet (lines 258-260) AND drop `scheduler.py` from the `db.py` consumer list at line 268 (currently "`client.py`, `scheduler.py`, `CloudProvisionerImpl`").
- [x] 6.5 `docs/ARCHITECTURE.md` §3.7 (line 386): remove the `class Scheduler in scheduler.py preserves its pre-migration surface.` bullet.
- [x] 6.6 `docs/ARCHITECTURE.md` §4 project structure tree (line 464): remove the `scheduler.py` line.

## 7. Validation gate

**All steps in this section must pass before the change is considered done.**

- [x] 7.1 `openspec validate remove-scheduler-wrapper --json` — the change itself validates clean.
- [x] 7.2 `openspec validate --all --json` — must report all passed (no regressions vs. baseline 32/32; deltas correctly applied).
- [x] 7.3 `python3 scripts/grace_check.py` — exit 0; `source-links-ref` warnings MUST remain 0; `func-size` warnings unchanged from baseline.
- [x] 7.4 `uv run pytest -m unit` — passes. Test count reduced vs. baseline by the deleted tests minus the two relocated `WebhookPayload` tests.
- [x] 7.5 `uv run ruff check .` — clean.
- [x] 7.6 `uv run ruff format --check .` — clean.
- [x] 7.7 `uv run lint-imports` — passes; no new layer violations from the deletion.
- [x] 7.8 `uv run zuban check` — clean (per AGENTS.md static checks).
- [x] 7.9 Manual sanity (broader than 2.4: covers full import surface): `python3 -c "import sys; import yascheduler; import yascheduler.adapters.cli.daemonize; import yascheduler.client; assert 'yascheduler.scheduler' not in sys.modules"` succeeds.
