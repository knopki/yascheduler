## Context

`yascheduler/webhook.py` (33 lines) holds a single frozen dataclass
`WebhookPayload(task_id: int, status: int, custom_params: Mapping[str, Any])`
at the package root. Its lone production consumer is
`yascheduler/infra/notifier/webhook.py` (`webhook_handler` adapter); its lone
test consumer is `tests/unit/test_webhook_handler.py`. The file carries a
standing `# FIXME: decide: move to domain?`.

Current call path (unchanged by this change):

```
DomainEvent (task_id, webhook_url, webhook_custom_params)
    │
    ▼
webhook_handler(event, http)         [infra/notifier/webhook.py]
    │  maps event → TaskStatus.value
    │  builds WebhookPayload(task_id, status, custom_params)  ← imported from root today
    ▼
_send_webhook(url, payload, http)
    │  asdict(payload) → HTTP POST body
    ▼
external HTTP endpoint
```

The dataclass is a wire-format DTO: `status` stores `TaskStatus.value` (int),
not the enum; `custom_params` is a loose `Mapping[str, Any]`. It is not a
domain concept — `domain/` already holds `TaskContext.webhook_url` and
`TaskContext.webhook_custom_params`, which is where client-supplied webhook
inputs live legitimately (Task carries them from submission; user confirmed
this is correct). The DTO at the root is just the outbound HTTP body shape.

The package root is mid-migration: `variables.py`/`compat.py` moved to
`shared/` (v1.6.0); `time.py`/`queue.py` are being relocated by the in-flight
`relocate-root-utils` change. `yascheduler/webhook.py` is the same category
of misplaced root utility.

Stakeholders / constraints:
- `AGENTS.md`: public interface stability (CLI, `class Yascheduler`, INI,
  DB schema, AiiDA entrypoint) — import paths not enumerated → fair game.
- GRACE-lite: `docs/knowledge-graph.xml` must remain consistent;
  `scripts/grace_check.py` enforces `<depends>` and `CrossLink` references
  resolve to existing M-IDs.
- OpenSpec: behavior-preserving relocates that touch no spec-level
  requirements produce no `specs/` delta (precedent:
  `openspec/changes/relocate-root-utils`).

## Goals / Non-Goals

**Goals:**
- Colocate `WebhookPayload` with its sole production consumer
  (`webhook_handler` in `infra/notifier/webhook.py`).
- Delete the root `yascheduler/webhook.py` and its misleading
  `M-WEBHOOK` graph record (`TYPE=CORE_LOGIC`, bogus `LINKS:
  M-APPLICATION-ORCHESTRATOR`).
- Keep the call graph, runtime behavior, and public surface byte-identical.
- Keep `docs/knowledge-graph.xml` and `docs/ARCHITECTURE.md` consistent with
  the new file layout.

**Non-Goals:**
- No change to `DomainEvent` field shape — `webhook_url` /
  `webhook_custom_params` stay on the base event. The standing `# FIXME`
  at `domain/events.py` remains as the open thread. Resolving whether
  delivery-channel fields belong on domain events is a separate design
  question (deferred per user instruction).
- No change to `Task` / `TaskContext` — these legitimately carry webhook
  inputs from client submission (user confirmed).
- No new `infra/notifier/payload.py` split (rejected A.2 in exploration;
  YAGNI at one consumer + one test consumer + three fields).
- No re-export of `WebhookPayload` from `infra/notifier/__init__.py` or
  `infra/__init__.py` — payload is internal to notifier. Tests use the deep
  import path `from yascheduler.infra.notifier.webhook import …`
  (precedent: `relocate-root-utils` treats orchestrator internals
  `UniqueQueue`/`UMessage` the same way).
- No backward-compatibility shim or deprecation at `yascheduler.webhook`
  (internal relocate; precedent: `relocate-root-utils` non-goal).
- No rename of the symbol (`WebhookPayload` keeps its name).
- No relocation of `tests/unit/test_webhook_handler.py`; no change to test
  bodies, fixtures, or assertions — only one import line moves.
- No inline-dict replacement of the DTO (rejected as alternative B in
  exploration — loses named constructor and existing construction/default-
  params tests).

## Decisions

### D1: Merge into the existing `infra/notifier/webhook.py` (A.1)

**Choice**: Absorb `WebhookPayload` as a top-level dataclass in
`yascheduler/infra/notifier/webhook.py`, placed above `webhook_handler`. Drop
the `from yascheduler.webhook import WebhookPayload` import (currently line 35
of that file).

**Alternatives considered**:
- *A.0 keep at root*: Rejected. Root is mid-migration; same category as
  `time.py`/`queue.py`. Keeping it perpetuates the drift.
- *A.2 new sibling `infra/notifier/payload.py`*: Rejected. Adds a 33-line
  file for one consumer + one test consumer + 3 fields. Earns its own file
  only if a second consumer appears. YAGNI.
- *A.3 facade re-export via `infra/notifier/__init__.py`*: Rejected. Payload
  is not cross-layer contract; facade is for cross-layer consumers
  (`webhook_handler` is registered by `di.py`, which imports the handler —
  not the payload — via `from .infra import webhook_handler`).
- *B inline dict in `_send_webhook`*: Rejected. Loses named constructor and
  the existing `TestWebhookPayload` tests of construction / default
  `custom_params`. `asdict()` works cleanly on dataclasses; manual dict
  assembly is a regression in readability.
- *Move to `domain/`*: Rejected. Payload is outbound wire format (ints +
  loose dict), not a domain concept. Domain already has
  `TaskContext.webhook_url` / `webhook_custom_params`.

**Why A.1**: Fewest files, filename collision at root resolves for free,
facades untouched, symbol stays navigable in the graph via
`M-NOTIFIER-WEBHOOK`'s annotations. The two "ghosts" in the current root
module — `M-WEBHOOK TYPE=CORE_LOGIC` (misclassified; it's a DTO) and
`LINKS: M-APPLICATION-ORCHESTRATOR` (orchestrator never touches it) —
dissolve on merge because `M-WEBHOOK` is deleted and `M-NOTIFIER-WEBHOOK`
inherits the symbol under its correct `TYPE=INTEGRATION`.

### D2: Graph record migration — delete `M-WEBHOOK`, fold annotation into `M-NOTIFIER-WEBHOOK`

**Choice**:
- Remove the entire `<M-WEBHOOK>…</M-WEBHOOK>` block (graph lines 30–37).
- Remove the `M-WEBHOOK` token from `M-NOTIFIER-WEBHOOK`'s `<depends>`
  (line 696) — becomes `M-DOMAIN-EVENTS, M-DOMAIN-MODEL`.
- Migrate the `<class-WebhookPayload PURPOSE="Webhook request data shape" />`
  annotation from `M-WEBHOOK` into `M-NOTIFIER-WEBHOOK`'s `<annotations>`
  block so the symbol stays graph-navigable.
- Delete the `<CrossLink from="M-NOTIFIER-WEBHOOK" to="M-WEBHOOK"
  relation="uses WebhookPayload for HTTP request serialization" />` (line
  909). With `M-WEBHOOK` gone, this link points to a nonexistent module and
  `scripts/grace_check.py`'s `_check_depends_refs` would emit a hard ERROR
  (exit 1).

**Verified no other graph references to `M-WEBHOOK`**:
`grep -n "M-WEBHOOK" docs/knowledge-graph.xml` returns exactly 3 matches:
line 30 (record opening), line 696 (`<depends>` token), line 909
(`CrossLink`). No `M-APPLICATION-ORCHESTRATOR` dependency on `M-WEBHOOK`;
its `<depends>` references `M-NOTIFIER-WEBHOOK` directly. Safe to delete.

**Alternative considered**: *Rewrite `M-WEBHOOK`'s path* to
`yascheduler/infra/notifier/webhook.py` while keeping the record. Rejected —
would leave two graph records pointing at the same file, duplicating the
`<class-WebhookPayload>` annotation between `M-WEBHOOK` and
`M-NOTIFIER-WEBHOOK`. The cleaner shape is one record per file.

### D3: Per-contract LINKS inside `infra/notifier/webhook.py` must drop `M-WEBHOOK`

Reviewer flagged (🟡): line 93 of
`yascheduler/infra/notifier/webhook.py` has `LINKS: M-WEBHOOK` inside
`START_CONTRACT: _send_webhook`. After the merge, `WebhookPayload` is
defined locally, so the contract's `LINKS:` must no longer reference the
deleted `M-WEBHOOK`.

**Choice**: Rewrite the `LINKS:` of the `_send_webhook` contract to
`M-NOTIFIER-WEBHOOK` (self-reference — the contract lives inside the same
module). `grace_check.py` only validates `LINKS:` as a warning (per
`relocate-root-utils` task 2.3 note), so a stale `M-WEBHOOK` would not fail
validation — but leaving a dangling reference violates GRACE-lite
navigation hygiene. Fold this into the contract rewrite in the
implementation batch.

The `webhook_handler` contract (line 61) has `LINKS: M-DOMAIN-EVENTS,
M-DOMAIN-MODEL` — unaffected; no change.

### D4: GRACE-lite header rewrite for `infra/notifier/webhook.py`

**Choice**: After absorbing `WebhookPayload`:
- Bump `VERSION` from `1.0.1` to `1.1.0` (minor: additive).
- Widen `MODULE_CONTRACT.PURPOSE` to mention both the handler and the
  payload DTO. New PURPOSE: "Webhook event handler and outbound payload
  DTO — sends HTTP notifications for task lifecycle events."
- Widen `MODULE_CONTRACT.SCOPE` to include `WebhookPayload` frozen
  dataclass alongside `webhook_handler` / `_send_webhook`.
- `MODULE_CONTRACT.DEPENDS` becomes `M-DOMAIN-EVENTS, M-DOMAIN-MODEL`
  (drops `M-WEBHOOK` — mirrors the graph `<depends>` change in D2).
- `MODULE_MAP` adds the line
  `WebhookPayload - Webhook request data shape`.
- `CHANGE_SUMMARY.LAST_CHANGE` becomes:
  `v1.1.0 - Absorb WebhookPayload from yascheduler/webhook.py (relocate-webhook-payload); root module deleted, M-WEBHOOK graph record removed.`

### D5: Doc drift fix in `docs/ARCHITECTURE.md`

Four locations reference the root `webhook.py` / `WebhookPayload`:
- §1 layer diagram root block (~line 85): `webhook.py  WebhookPayload frozen
  dataclass` row.
- §3 layer-responsibility table (~line 121): `webhook.py` row.
- §4 project tree (~line 457): `├── webhook.py # WebhookPayload dataclass`.
- §5 detailed prose (~lines 257–258): "**`webhook.py`** — `WebhookPayload`
  frozen dataclass, consumed by `notifier/webhook.py`."

**Choice**: Remove all four. `WebhookPayload` is now internal to
`infra/notifier/webhook.py`, which is already documented in §1 (line 70:
`notifier/webhook.py  Webhook event handler`) and §5. No new entry needed;
the existing `notifier/webhook.py` line at §1 line 70 implicitly covers the
absorbed payload. Fix box-drawing `├──`/`└──` prefixes in §4 if the removed
entry makes the last child change.

### D6: Test import rewrite

**Choice**: Single edit in `tests/unit/test_webhook_handler.py` line 49:
`from yascheduler.webhook import WebhookPayload` →
`from yascheduler.infra.notifier.webhook import WebhookPayload`.

No other test file imports `WebhookPayload` (verified by
`grep -rln "WebhookPayload" tests/`). `TestWebhookPayload` class (lines
205+) stays in place — its constructor and default-`custom_params` tests
remain valid because the dataclass shape is unchanged.

## Risks / Trade-offs

- **[Risk] `asdict(payload)` serialization changes** → *Mitigation*: none
  needed. The dataclass definition is byte-identical (same fields, same
  types, same `frozen=True`); only its containing module changes. `asdict`
  behavior is determined by the class, not its import path. Existing
  `test_send_webhook_*` tests cover the POST path.

- **[Risk] `from yascheduler.webhook import …` lingering somewhere** →
  *Mitigation*: task 5.1 in `tasks.md` runs
  `grep -rn "yascheduler\.webhook\|yascheduler/webhook" --include="*.py"
  --include="*.xml" --include="*.md"` and must return zero matches (except
  the legitimate `infra/notifier/webhook` path). This mirrors
  `relocate-root-utils` task 5.1/5.2.

- **[Risk] Graph references to `M-WEBHOOK` outside the three known sites** →
  *Mitigation*: D2 verifies with `grep -n "M-WEBHOOK"
  docs/knowledge-graph.xml` that exactly 3 matches exist before edit.
  Implementation task re-runs the same grep after edit; must return zero.
  `grace_check.py`'s `_check_depends_refs` is the hard gate (exit 1 on
  dangling refs).

- **[Risk] Implementer forgets the `_send_webhook` per-contract LINKS** →
  *Mitigation*: D3 calls it out explicitly; the implementation task for the
  contract rewrite enumerates both the `webhook_handler` contract (no
  change) and the `_send_webhook` contract (`LINKS:` rewrite to
  `M-NOTIFIER-WEBHOOK`).

- **[Trade-off] `infra/notifier/webhook.py` grows from 107 to ~120 lines**.
  Still well within the GRACE-lite 500-line soft / 1000-hard limit. The
  file now holds a dataclass + 2 functions + lazy semaphore helper — a
  cohesive notifier unit.

- **[Trade-off] Deep import path for tests** (`from
  yascheduler.infra.notifier.webhook import WebhookPayload`). This is
  consistent with how tests already reach orchestrator internals
  (`from yascheduler.application.queue import …`, `from
  yascheduler.application import allocate_task`). No facade pollution.

## Migration Plan

This is a behavior-preserving internal relocate. No runtime migration, no
DB change, no config change.

**Deploy**: single commit/PR with all touched files in one atomic change
(code + tests + graph + docs). No phased rollout — internal import paths
are not public surface.

**Rollback**: revert the commit. No state to recover. The deleted
`yascheduler/webhook.py` is restored from git history.

**Order of edits** (implementation batch):
1. Absorb `WebhookPayload` into `infra/notifier/webhook.py`; rewrite its
   GRACE-lite header and the `_send_webhook` contract `LINKS:` (D3, D4);
   drop the `from yascheduler.webhook import` line.
2. `git rm yascheduler/webhook.py`.
3. Rewrite test import (D6).
4. Edit `docs/knowledge-graph.xml` (D2).
5. Edit `docs/ARCHITECTURE.md` (D5).

**Verification gates** (final batch):
- `python3 scripts/grace_check.py` exits 0 (graph consistency).
- `openspec validate --all --json` passes.
- `uv run pytest -m unit|integration|e2e` pass.
- `uv run lint-imports`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run zuban check` pass.
- `grep -rn "yascheduler\.webhook\b|yascheduler/webhook\b"` returns zero
  (excluding `infra/notifier/webhook`).
- `grep -n "M-WEBHOOK" docs/knowledge-graph.xml` returns zero.

## Open Questions

None beyond the explicitly-deferred `DomainEvent` shape question (recorded
in the brief and the proposal's non-goals; `# FIXME` stays in
`domain/events.py`). Resolving that is a separate change proposal.