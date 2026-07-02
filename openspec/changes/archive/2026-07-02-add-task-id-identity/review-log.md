## proposal Round 1 — 2026-07-02

### Reviewer: @k-reviewer-fast

### Verdict: PASS (no 🔴 outstanding)

### 🟡 Addressed (minor clarity gaps, fixed before freeze)
- **`query_tasks` use case missing from "Use cases" section** — the proposal
  listed `submit_task`, `allocate_task`, `consume_task` but omitted
  `query_tasks(jobs: Sequence[int] | None, ...)`, which routes
  `queue_get_tasks_async` → `list_by_jobs`. Added it with the
  `Sequence[int] -> Sequence[TaskId]` entry change and the facade-wraps-input
  note. (Verified against `application/query_tasks.py:46`.)
- **`_task_to_dict` extraction implicit** — the facade section described the
  `.value` extraction intent but didn't name the concrete helper that does it.
  Named `_task_to_dict` (`client.py:89`) explicitly as the extraction site.
- **`_NodeView.task_id` annotation not mentioned** — added the
  `int | None -> TaskId | None` narrowing for `_NodeView.task_id`
  (`show_nodes.py:56`), mirroring how `add-node-id-identity` carries `NodeId`
  through `_NodeView` and extracts `.value` only at the JSON renderer
  (`show_nodes.py:241`). Design choice: carry `TaskId` through the view, extract
  at JSON (consistent with the Node precedent), NOT extract-at-construction.

### 🔴 Outstanding
- (none)

### Notes
- The 8 rejected alternatives from the explore-brief are not restated as a
  dedicated section in the proposal; this matches the `add-node-id-identity`
  precedent (its proposal also has no rejected-alternatives section — they live
  in the brief). No change made.
- All factual line-number citations verified against the codebase
  (`model.py:197`, `events.py:33`, `submit_task.py:81`, `postgres.py:159`,
  `ports.py:48-69`, `query_tasks.py:46`, `show_nodes.py:56/152/205/241`,
  `client.py:89`).
- The "no DB migration, no sql-queries delta" claim verified:
  `task/insert.sql` already ends with `RETURNING task_id, label, ip, status,
  metadata`; `yascheduler_tasks.task_id SERIAL PRIMARY KEY` already exists.

## proposal Round 2 — 2026-07-02

### Reviewer: @k-reviewer-fast

### Verdict: PASS (no 🔴 outstanding in round 2)

### 🟡 Addressed (one new gap found in round 2, fixed before freeze)
- **`yastatus` `_render_json` would crash at runtime** — round-1 review and the
  proposal both claimed `yastatus` renders via `__str__` with no change. This is
  true for the two TEXT renderers (`_render_default` f-string at line 145,
  `_render_info` `.format` at line 159 — both call `__str__`). But the JSON
  renderer `_render_json` (`"task_id": task.task_id` at line 181, then
  `json.dumps(objects)`) does NOT call `__str__`; `json.dumps` on a frozen
  dataclass raises `TypeError: Object of type TaskId is not JSON serializable`.
  Fixed: proposal's `yastatus` bullet now requires line 181 to become
  `task.task_id.value`, and the brief's CLI row updated accordingly.
- **`yastatus` `_query_tasks` int→TaskId wrap** — `_query_tasks`
  (`check_status.py:127`) passes `args.jobs` (`list[int]` from argparse) to
  `list_by_jobs` (now `list[TaskId]`). Fixed: proposal now requires
  `[TaskId(j) for j in args.jobs]` at line 127 (CLI-internal wrap, same pattern
  as the facade's `queue_get_tasks_async`).

### 🔴 Outstanding
- (none)

### Freeze decision
Round 2 PASS with no 🔴. Per the single-round pass rule (workflow 4a), the
**proposal batch is frozen**. Proceeding to batch 2 (`design.md`).

## design Round 1 — 2026-07-02

### Reviewer: @k-reviewer-fast

### Verdict: FAIL — one 🔴 factual error (webhook boundary)

### 🔴 Fixed (required unfreeze of the frozen proposal — decision-level correction)
- **Design (and proposal) wrongly claimed `event.task_id` is NOT serialized into
  the webhook body.** The webhook handler lives at `infra/notifier/webhook.py`
  (NOT `infra/webhook/` — that path does not exist; the claim's "verified"
  citation was to a nonexistent path). `webhook.py:86` builds
  `WebhookPayload(task_id=event.task_id, ...)` and `webhook.py:112` serializes
  via `dataclasses.asdict(payload)` into the HTTP POST body. With `event.task_id`
  now a `TaskId` (Scope B), `asdict` would recurse into the `TaskId` dataclass
  and the body would become `{"task_id": {"value": 42}, ...}` instead of
  `{"task_id": 42, ...}` — a silent wire-shape break (not a TypeError, but a
  wrong payload). Fixed in design (boundaries + events sections + touched-files
  list), and because this adds `infra/notifier/webhook.py` to scope (a
  one-line `.value` extraction at `webhook.py:86`), the frozen proposal was
  **unfrozen**, corrected (Domain-events bullet + Webhook-handler bullet +
  Out-of-scope/capabilities entry), and must be re-reviewed. The brief's
  Webhook decisions row was also corrected. `WebhookPayload.task_id: int`
  (`webhook.py:48`) stays `int` (correct target type); the wire payload shape
  is preserved by the `.value` extraction.

### 🟡 Addressed (minor, non-blocking)
- Touched-files list now includes `infra/notifier/webhook.py`.
- `task/insert.sql` Context anchor clarified to the full path
  (`infra/persistence/sql/task/insert.sql`).

### 🔴 Outstanding
- (none after the webhook fix — but the proposal unfreeze requires a re-review
  of the proposal batch before re-freezing, then a re-review of design.)

## design Round 2 — 2026-07-02

### Reviewer: @k-reviewer-fast

### Verdict: PASS (no 🔴 outstanding)

### Result
The 4-site webhook correction (Context anchor, Boundaries `asdict` bullet,
Events section, touched-files list) is complete, technically accurate, and
consistent with the re-frozen proposal. No regression in any non-webhook section.
No new decision-level issues. **Design batch is frozen.** Proceeding to batch 3
(`specs/`).

## specs Round 1 — 2026-07-02

### Reviewer: @k-reviewer-fast

### Verdict: PASS (no 🔴 outstanding)

### Result
All 8 spec delta files (domain-entities, domain-events, domain-exceptions,
domain-ports, postgres-repositories, use-cases, package-facades, webhook-handler)
are format-compliant, consistent with the frozen proposal + design, cover the
critical correctness claims with scenarios (TaskId(0) raises, __str__ renders
bare int, TaskId != int, webhook asdict wire-shape, NewTask has no task_id,
submit_task constructs NewTask), and introduce no contradictions with the
existing main specs. `openspec validate add-task-id-identity --json` returned
`valid: true`. No decision-level changes to frozen artifacts. **Specs batch is
frozen.** Proceeding to batch 4 (`tasks.md`).

## tasks Round 1 — 2026-07-02

### Reviewer: @k-reviewer-fast

### Verdict: PASS (no 🔴 outstanding)

### 🟡 Addressed (one factual nit, fixed before freeze)
- **Tasks 3.1, 3.2, and 6.5 wrongly assumed `from __future__ import annotations`
  is present** in `domain/exceptions.py`, `infra/persistence/exceptions.py`,
  and `application/allocation_tracker.py`. Verified: none of those three files
  has the future import (only `events.py`, `ports.py`, `postgres.py`,
  `submit_task.py`, `allocate_task.py`, `consume_task.py`, `query_tasks.py`,
  `webhook.py`, `check_status.py`, `show_nodes.py` do). So the `task_id: TaskId`
  annotations in those three files are runtime-evaluated → `TaskId` MUST be
  imported at runtime (`from yascheduler.domain.model import TaskId`), NOT under
  `TYPE_CHECKING` (which would cause `NameError` at class-definition time).
  Fixed in 3.1, 3.2, and 6.5 with explicit runtime-import guidance.

### 🔴 Outstanding
- (none)

### Freeze decision
Round 1 PASS with no 🔴. Per the single-round pass rule (workflow 4a), the
**tasks batch is frozen**. The `add-task-id-identity` change proposal is
**complete**: `.openspec.yaml`, `explore-brief.md`, `proposal.md` (frozen),
`design.md` (frozen), `specs/` (8 delta files, frozen), `tasks.md` (frozen),
`review-log.md`. `openspec validate add-task-id-identity --json` returns
`valid: true`. Ready for the apply (implementation) phase.