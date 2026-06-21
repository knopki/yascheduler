## Context

`yascheduler/scheduler.py` (192 LOC) is one of three legacy top-level modules
listed as "composition root" members in `openspec/specs/package-facades/`
(`scheduler.py`, `di.py`, `client.py`). Of these three, only `di.py` and
`client.py` are wired into production entry points: the daemon CLI
(`yascheduler` console script → `adapters/cli/daemonize.py`) calls
`make_daemon()` directly; the AiiDA plugin uses `class Yascheduler` from
`client.py`; CLI submit/status/nodes commands use `make_cli_deps()` or
`DB` directly.

`scheduler.py` survives only as a thin `attrs` wrapper (`class Scheduler`)
plus two stray concerns: a `get_logger` factory (consumed by `daemonize.py`
via a lazy import) and a re-export of `WebhookPayload` (canonical home:
`yascheduler/webhook.py`). The file carries `# FIXME: remove this module`
at line 22. Its `class Scheduler` has zero production consumers; only test
code (`test_scheduler.py`, three classes of `test_characterization.py`,
the `mock_scheduler.py` fixture) constructs it.

The frozen `proposal.md` authorises full removal of the file plus the
consequent minimal set of adjustments in tests, docs, and three spec
capabilities (`package-facades`, `testing-unit`, `db-wrapper`). This design
covers HOW.

## Goals / Non-Goals

**Goals:**

- Eliminate `yascheduler/scheduler.py` with no regression to documented
  public API (`yascheduler/__init__.py` exports, CLI entry points, AiiDA
  entry point).
- Preserve the one piece of live functionality in the file (`get_logger`)
  by moving it to its sole consumer.
- Update specs so `openspec validate --all --json` passes after the change
  (no stale requirements mentioning `Scheduler` or `scheduler.py`).
- Update `docs/ARCHITECTURE.md` so the architecture description matches
  the source tree. The six affected sections (per `proposal.md` Impact):
  §1 ASCII diagram (line 84), §2 component reference table (line 120),
  §2.2 last paragraph (line 178), §2.9 (lines 258-260, 268), §3.7
  (line 386), §4 project structure tree (line 464).
- Apply GRACE-lite: bump `CHANGE_SUMMARY` on `daemonize.py` and update
  its MODULE_MAP/SCOPE per D6; remove the `M-SCHEDULER` element from the
  knowledge graph and scrub `M-SCHEDULER` from `LINKS:` lines in the 12
  surviving source files (D5); update `test_webhook_handler.py`'s
  MODULE_CONTRACT/MODULE_MAP per D2.

**Non-Goals:**

- Touching any other legacy wrapper (`db.py`, `client.py`) — those have
  active consumers and their own retirement paths (ARCHITECTURE.md §6.4).
- Adding a new logging-utility module — the single consumer justifies
  inlining (YAGNI; rejected in `explore-brief.md`).
- Deprecation cycle — no production consumer exists, so a
  `DeprecationWarning` would fire only inside the test suite.
- Changing the AiiDA plugin's direct use of `Yascheduler` — that is
  ARCHITECTURE.md §6.3, a separate proposal.
- Promoting `_get_logger` to any facade (private to `daemonize.py`).

## Decisions

### D1. Inline `get_logger` into `daemonize.py` as `_get_logger`

**Decision.** Move the body of `scheduler.get_logger` (lines 47-73)
verbatim into `yascheduler/adapters/cli/daemonize.py` as a module-private
`_get_logger(log_file, level=logging.INFO)`. Replace the lazy
`from yascheduler.scheduler import get_logger` (line 42) with the local
call.

**Rationale.** Single consumer, ~25 LOC, daemon-only. Extracting to a new
`yascheduler/log.py` was rejected as premature (YAGNI); placing in `di.py`
was rejected because `di.py` is the composition root for wiring, not
logging configuration. If a second consumer materialises later, extraction
becomes a small follow-up with a clear migration path.

**Visibility.** Leading underscore (private). No facade re-export. The
function name loses no semantic information; the underscore merely
declares "no external consumers".

**Side effects of the body.** Today `logging.basicConfig(level=logging.INFO)`
sits at module top-level of `scheduler.py` (line 44), and the scheduler
import in `daemonize.py` is lazy (inside `daemonize()`'s body, line 42).
The net effect today: `basicConfig` fires exactly once, on the first
invocation of `daemonize()`. After the move, `basicConfig` lives inside
`_get_logger` (still called from within `daemonize()`); runtime behaviour
is identical — `basicConfig` fires exactly once on first `daemonize()`
call. Care must be taken NOT to lift `basicConfig` to `daemonize.py`
module top-level, which would change import-time behaviour for tests
that import `daemonize` without invoking it.

### D2. Drop the `WebhookPayload` re-export without ceremony

**Decision.** Remove `from .webhook import WebhookPayload as WebhookPayload`
(line 42 of `scheduler.py`). The canonical definition at
`yascheduler/webhook.py` stays; the notifier adapter already imports from
there (`adapters/notifier/webhook.py:35`).

**Rationale.** Zero production consumers of the re-export. The two
construction tests in `test_scheduler.py:169-192` move to
`tests/unit/test_webhook_handler.py` with the import switched to
`from yascheduler.webhook import WebhookPayload` (already the form used by
that file at line 47).

**GRACE-lite housekeeping for the destination file.**
`tests/unit/test_webhook_handler.py` currently has a MODULE_CONTRACT with
SCOPE "Unit tests for webhook_handler event dispatch and _send_webhook"
(line 5) and a MODULE_MAP listing five test functions (lines 10-17).
Adding `TestWebhookPayload` widens the file's scope. The apply phase
must: (a) append a CHANGE_SUMMARY entry recording the relocation;
(b) add the two new test functions to MODULE_MAP; (c) widen SCOPE to
mention `WebhookPayload` construction alongside the existing scope.

### D3. Test deletions are file-level where the file's purpose is Scheduler-only

**Decision.**

- `tests/unit/test_scheduler.py` — **delete the file**. Its MODULE_CONTRACT
  says "Unit tests for Scheduler class after refactoring"; with the
  subject gone, the file has no purpose. The `WebhookPayload` tests move
  out first (D2).
- `tests/unit/test_characterization.py` — **delete three classes**
  (`TestSchedulerCreateNewTask`, `TestSchedulerStart`, `TestSchedulerStop`)
  and their imports. Keep `TestClientQueueSubmitTaskAsync` and the file's
  MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY (update them to reflect the
  surviving scope).
- `tests/fixtures/mock_scheduler.py` — **delete the file**. Both
  `make_scheduler` (subject is `Scheduler`) and `create_test_config`
  (only consumer is the deleted `test_scheduler.py`) have no surviving
  users. Relocating `create_test_config` was rejected as speculative.
- `tests/unit/test_cli_smoke.py` — **delete one test**
  (`test_utils_import_does_not_import_scheduler`). The file's other tests
  (CLI function smoke checks) survive. Update MODULE_MAP if it lists the
  deleted test.

**Rationale.** Maximises signal. Keeping stub files around "for the next
person" violates YAGNI; deleting entire files whose only reason for
existence was `Scheduler` keeps the test tree honest about what is being
tested.

### D4. Spec delta form: `## MODIFIED Requirements` for rewrite-in-place; remove stale scenarios within MODIFIED

**Decision.** For each of the three Modified Capabilities, write a
`## MODIFIED Requirements` delta under
`openspec/changes/remove-scheduler-wrapper/specs/<capability>/spec.md`
containing the full new requirement text. OpenSpec computes the diff
against the live spec.

- **`package-facades`** — rewrite four requirements that mention
  `yascheduler.scheduler`:
  1. "Outside-layer-set exemptions" — remove `yascheduler.scheduler` from
     the composition-root list (keep `yascheduler.di`, `yascheduler.client`;
     `yascheduler.db` stays on its own line as legacy-scheduled-for-deletion).
  2. "Cross-package facade imports (R2)" — update the "Composition root
     imports use layer facades" scenario to reference `yascheduler.di` and
     `yascheduler.client` only.
  3. "Extended facade contents (lazy publication driven by consumers)" —
     in the prose listing `yascheduler.scheduler` as a consumer of
     `CloudProvisionerImpl`, `CloudAdapter`, `Orchestrator`, `submit_task`,
     drop `yascheduler.scheduler` and keep `yascheduler.di`.
  4. "Documented private-symbol carve-outs" — reduce the carve-out for
     `_resolve_adapter` to `yascheduler/di.py` only.
- **`testing-unit`** — rewrite "Scheduler characterization tests" into
  "Client queue-submit characterization" with the single surviving
  scenario: `Yascheduler.queue_submit_task_async` calls `deps.submit()`
  via `make_cli_deps`. The Scheduler-specific scenarios are dropped. (Per
  Round 2 of the proposal review: full removal was rejected because no
  other requirement covers `queue_submit_task_async`.)
- **`db-wrapper`** — rewrite the "DB provides task and node CRUD"
  requirement's "Existing scheduler code compiles unchanged" scenario to
  name `yascheduler/client.py` as the surviving
  `get_tasks_by_status` consumer (verified at `client.py:151`). The
  requirement itself and its other scenarios stay.

**Rationale.** `MODIFIED` is preferred over `REMOVED`+`ADDED` because
each affected requirement is being edited in place — the change is
scoped and traceable in the spec history.

### D5. Knowledge-graph update: remove `M-SCHEDULER` block, all four outgoing `CrossLink`s, and scrub `LINKS:` references in 12 surviving source files

**Decision.** Three coupled cleanups:

**(a) XML graph** — in `docs/knowledge-graph.xml`:

- Remove the `<M-SCHEDULER ...> ... </M-SCHEDULER>` block (lines 39-52).
- Remove the four `<CrossLink from="M-SCHEDULER" ...>` entries (lines 882,
  909, 910, 934).
- Audit every other `<depends>` element for `M-SCHEDULER` references —
  none exist (verified via grep; recorded as a defensive no-op in
  `proposal.md`).

**(b) Source `LINKS:` scrub** — remove the `M-SCHEDULER` token from the
`LINKS:` line in each of the 12 surviving source files (verified via
`rg "LINKS:.*M-SCHEDULER"`). The other M-IDs on each line stay. The 12
files:

```
yascheduler/webhook.py                       — LINKS: M-SCHEDULER, M-APPLICATION-ORCHESTRATOR
yascheduler/queue.py                         — LINKS: M-SCHEDULER
yascheduler/time.py                          — LINKS: M-SCHEDULER
yascheduler/db.py                            — LINKS: M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL, M-SCHEDULER
yascheduler/domain/services.py               — LINKS: M-DOMAIN-MODEL, M-SCHEDULER
yascheduler/config/__init__.py               — LINKS: M-CONFIG, M-SCHEDULER
yascheduler/config/local.py                  — LINKS: M-SCHEDULER
yascheduler/config/config.py                 — LINKS: M-CONFIG-HUB, M-SCHEDULER
yascheduler/config/engine_repository.py      — LINKS: M-CONFIG-ENGINE, M-SCHEDULER
yascheduler/application/allocate_task.py     — LINKS: ..., M-SCHEDULER, ...
yascheduler/application/consume_task.py      — LINKS: ..., M-SCHEDULER, ...
yascheduler/application/submit_task.py       — LINKS: ..., M-SCHEDULER
```

(The three test files that also reference `M-SCHEDULER` —
`test_scheduler.py`, `test_characterization.py`, `mock_scheduler.py` —
are deleted/edited by D3 and so do not add to the surviving count.)

**Rationale.** The knowledge graph is the navigational truth and `LINKS:`
is the file-local → graph-M-ID bridge (AGENTS.md "Navigation Order").
Leaving stale `LINKS` references would emit `source-links-ref` warnings
from `scripts/grace_check.py` and undermine GRACE-lite navigation. Today
the baseline has 0 such warnings; the change must keep it at 0.

### D6. Apply is a single atomic commit; no partial-state migration

**Decision.** All code, test, doc, and spec edits land in one commit
(or one squash-set). No intermediate state where `scheduler.py` is gone
but `daemonize.py` still imports from it.

**Rationale.** There is no value in a staged rollout for an internal-API
deletion with no production consumer. Bisect-friendliness is preserved by
keeping the atomic change small (~5 files edited, 3 deleted, plus spec
deltas).

**`daemonize.py` GRACE-lite update.** Inlining `_get_logger` adds a new
module-level callable; the file's contract must reflect this. Concretely:

- `MODULE_CONTRACT` SCOPE (`daemonize.py:5`) — widen from
  "daemonize command — creates Orchestrator via DI, runs event loop" to
  also mention logger configuration.
- `MODULE_MAP` (`daemonize.py:10-12`) — add
  `_get_logger - Configure and return the yascheduler logger (inlined from scheduler.py)`.
- `CHANGE_SUMMARY` (`daemonize.py:14-15`) — append a v1.1.0 entry
  recording the inline.
- `MODULE_CONTRACT` DEPENDS (`daemonize.py:6`) — no change; `logging` is
  stdlib with no M- entry.

### D7. Apply-phase critical path (informative — sequencing rationale only; concrete steps owned by `tasks.md`)

The only ordering constraint that matters: `_get_logger` inlining into
`daemonize.py` MUST precede deletion of `scheduler.py`, or
`daemonize.py:42` will dangle. All other edits (test deletions, spec
deltas, doc updates, `LINKS:` scrub) are order-independent within the
atomic commit. `tasks.md` will enumerate the concrete steps; this
decision records only the dependency edge that cannot be reordered.

## Risks / Trade-offs

- **[Unknown external consumer of `class Scheduler`]** → Mitigation: the
  consumer audit was exhaustive within the repo and across
  `[project.scripts]`, `[project.entry-points]`, and `__init__.py`
  exports. External risk is limited to third-party code that imports an
  undocumented internal class; acceptable for a 0.x package. CHANGELOG
  update is out of scope for this change.
- **[Logging `basicConfig` placement regression]** → Mitigation: D1
  explicitly calls out that `basicConfig` must stay inside `_get_logger`,
  not move to `daemonize.py` module top-level. Verified by reading the
  current `scheduler.py:44` placement.
- **[`daemonize.py` size creep]** → The file grows by ~25 LOC. Still well
  under the 500-LOC soft limit. If `daemonize.py` later needs to slim,
  the logger setup is the first candidate for extraction — but not now.
- **[Interaction with `daemonize.py:17` FIXME]** → The file already
  carries `# FIXME: split adapter and application layer (business logic)`.
  Inlining `_get_logger` (a piece of daemon-setup logic) slightly
  exacerbates that FIXME. Mitigation: accepted as a small step in the
  wrong direction; revisit when the FIXME is addressed. The alternative
  (extract to `yascheduler/log.py`) was rejected as YAGNI for a single
  consumer.
- **[Spec drift on archive]** → After archive, the three
  `openspec/specs/<capability>/spec.md` files must reflect the new
  reality. The `openspec validate --all --json` step in `tasks.md` is the
  gate.
- **[GRACE-lite validation breakage]** → Knowledge-graph integrity check
  via `grace_check.py` could fail if the `M-SCHEDULER` removal misses a
  reference. The defensive grep in D5 plus the validator run are the
  safety net.

## Migration Plan

None required. The change is internal-only:

- No DB schema change.
- No config-format change.
- No public API change.
- No deployment ordering constraint (single commit).

Rollback is `git revert`.

## Open Questions

None. All decisions were closed during the explore phase or in the
proposal review loop.
