## 1. Code absorption (production)

- [x] 1.1 Open `yascheduler/infra/notifier/webhook.py`. Above the `webhook_handler` function (after the `logger = ...` line and before the `_get_semaphore` helper), add the `WebhookPayload` frozen dataclass verbatim from `yascheduler/webhook.py`:
  ```
  @dataclass(frozen=True)
  class WebhookPayload:
      task_id: int = field()
      status: int = field()
      custom_params: Mapping[str, Any] = field(default_factory=dict)
  ```
  Add `Mapping` import: `from collections.abc import Mapping` (module-level; file has no `TYPE_CHECKING` block today). Expand the existing `from dataclasses import asdict` (line 24) to `from dataclasses import asdict, dataclass, field`. Add `from typing import Any` (file currently has no `typing` import; the `from __future__ import annotations` at line 20 means `str | None` etc. still work, but `Any` needs an explicit import).
- [x] 1.2 In `yascheduler/infra/notifier/webhook.py`, delete the line `from yascheduler.webhook import WebhookPayload` (currently line 35).
- [x] 1.3 In `yascheduler/infra/notifier/webhook.py`, rewrite the GRACE-lite header per design D4:
  - Bump `# VERSION:` from `1.0.1` to `1.1.0`.
  - Update `START_MODULE_CONTRACT.PURPOSE` to: `Webhook event handler and outbound payload DTO — sends HTTP notifications for task lifecycle events.`
  - Update `START_MODULE_CONTRACT.SCOPE` to: `WebhookPayload frozen dataclass, webhook_handler async function dispatching webhooks per event type, _send_webhook retry helper.`
  - Update `START_MODULE_CONTRACT.DEPENDS` from `M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-WEBHOOK` to `M-DOMAIN-EVENTS, M-DOMAIN-MODEL` (drops `M-WEBHOOK`).
  - `START_MODULE_CONTRACT.LINKS` — verify unchanged: `M-DOMAIN-EVENTS, M-NOTIFIER-WEBHOOK` (no edit; `LINKS` is graph-side, validates as warning only per `relocate-root-utils` task 2.3 note).
  - Add `WebhookPayload - Webhook request data shape` line to `START_MODULE_MAP`.
  - Rewrite `START_CHANGE_SUMMARY.LAST_CHANGE` to: `v1.1.0 - Absorb WebhookPayload from yascheduler/webhook.py (relocate-webhook-payload); root module deleted, M-WEBHOOK graph record removed.`
  - Preserve the existing `PREVIOUS_CHANGE` entry by shifting it down one slot if the header format allows, or drop it if only `LAST_CHANGE`/`PREVIOUS_CHANGE` two-slot format is enforced (match `relocate-root-utils` queue.py header convention — single `LAST_CHANGE` is acceptable).
- [x] 1.4 In `yascheduler/infra/notifier/webhook.py`, update the per-contract `LINKS:` for `_send_webhook` per design D3: find `START_CONTRACT: _send_webhook` (~line 87) and change its `LINKS: M-WEBHOOK` to `LINKS: M-NOTIFIER-WEBHOOK` (self-reference, since `WebhookPayload` is now defined in the same module). Do NOT touch the `webhook_handler` contract's `LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL` (~line 61) — it's unaffected.
- [x] 1.5 `git rm yascheduler/webhook.py` (preserves rename-detection history for the absorbed content, mirroring `relocate-root-utils` task 1.2).

## 2. Test import rewrite

- [x] 2.1 Edit `tests/unit/test_webhook_handler.py` line 49: `from yascheduler.webhook import WebhookPayload` → `from yascheduler.infra.notifier.webhook import WebhookPayload`. Do NOT touch any test body, fixture, or assertion — including `TestWebhookPayload` class (lines 205+) — only this single import line moves. Verify no other `from yascheduler.webhook` line exists in `tests/` via `grep -rn "yascheduler\.webhook\|yascheduler/webhook" --include="*.py" tests/` after the edit (must be empty).

## 3. Knowledge graph update

- [x] 3.1 Edit `docs/knowledge-graph.xml`: remove the entire `<M-WEBHOOK NAME="Webhook payload" TYPE="CORE_LOGIC" STATUS="implemented">…</M-WEBHOOK>` block (currently lines 30–37, including the inner `<purpose>`, `<path>yascheduler/webhook.py</path>`, `<depends>none</depends>`, and `<annotations><class-WebhookPayload … /></annotations>` lines).
- [x] 3.2 Edit `docs/knowledge-graph.xml`: in `M-NOTIFIER-WEBHOOK`'s `<annotations>` block (near lines 707–708), add `<class-WebhookPayload PURPOSE="Webhook request data shape" />` so the symbol stays graph-navigable. This migrates the annotation from the deleted `M-WEBHOOK`.
- [x] 3.3 Edit `docs/knowledge-graph.xml` line 696: in `M-NOTIFIER-WEBHOOK`'s `<depends>`, change `M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-WEBHOOK` → `M-DOMAIN-EVENTS, M-DOMAIN-MODEL` (removes `M-WEBHOOK` token).
- [x] 3.4 Edit `docs/knowledge-graph.xml`: delete the `<CrossLink from="M-NOTIFIER-WEBHOOK" to="M-WEBHOOK" relation="uses WebhookPayload for HTTP request serialization" />` line (currently line 909).
- [x] 3.5 Re-run `grep -n "M-WEBHOOK" docs/knowledge-graph.xml` — must return zero matches. (Pre-edit it returns 4: line 30 `<M-WEBHOOK …>`, line 37 `</M-WEBHOOK>`, line 696 depends, line 909 CrossLink — all of which are removed by 3.1/3.3/3.4.)

## 4. Architecture doc drift fix

- [x] 4.1 Edit `docs/ARCHITECTURE.md` §1 layer diagram root block (~line 85): remove the `│  webhook.py          WebhookPayload frozen dataclass             │` row. The `notifier/webhook.py` row at line 70 already documents the handler; no new row needed — `WebhookPayload` is now an internal of that file.
- [x] 4.2 Edit `docs/ARCHITECTURE.md` §3 layer-responsibility table (~line 121): remove the `| webhook.py | WebhookPayload frozen dataclass |` row.
- [x] 4.3 Edit `docs/ARCHITECTURE.md` §5 detailed prose (~lines 257–258): remove the `- **\`webhook.py\`** — \`WebhookPayload\` frozen dataclass, consumed by \`notifier/webhook.py\`.` bullet pair (two lines).
- [x] 4.4 Edit `docs/ARCHITECTURE.md` §4 project tree (~line 457): remove the `├── webhook.py                 # WebhookPayload dataclass` line. Fix the box-drawing `├──`/`└──` prefixes of surrounding entries if this removal makes a former middle entry the last child (visual-only; no semantic change).
- [x] 4.5 Re-read `docs/ARCHITECTURE.md` around the four edit sites to confirm no dangling reference to root `webhook.py` / `WebhookPayload` remains in the document. `grep -n "webhook\.py\|WebhookPayload" docs/ARCHITECTURE.md` may still legitimately show `infra/notifier/webhook.py` references — those are correct.

## 5. Verification

- [x] 5.1 Run `grep -rn "yascheduler\.webhook\b\|yascheduler/webhook\b" --include="*.py" yascheduler/ tests/` — must return zero matches. (The deep path `yascheduler.infra.notifier.webhook` is fine; this grep targets only the root module.) *(Satisfied by intent: 1 match is the CHANGE_SUMMARY provenance comment mandated by task 1.3, not a live path reference; live references zero — confirmed by `grep -rn "from yascheduler\.webhook\|import yascheduler\.webhook\b" --include="*.py" tests/ yascheduler/` returning empty.)*
- [x] 5.2 Run `grep -rn "yascheduler\.webhook\b\|yascheduler/webhook\b" --include="*.py" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/` — must return zero matches for the root module. Matches for `yascheduler/infra/notifier/webhook` / `yascheduler.infra.notifier.webhook` are legitimate and expected. *(Satisfied by intent: same single CHANGE_SUMMARY provenance comment as 5.1; all live references zero.)*
- [x] 5.3 Run `grep -n "M-WEBHOOK" docs/knowledge-graph.xml` — must return zero matches.
- [x] 5.4 Run `python3 scripts/grace_check.py` — must exit 0. This is the hard gate for graph consistency (validates `<depends>` refs, `CrossLink` endpoints, and reports dangling `LINKS:` as warnings).
- [x] 5.5 Run `uv run pytest -m unit` — must pass. Covers `tests/unit/test_webhook_handler.py` (import path + `TestWebhookPayload` construction tests) and any unit tests touching the graph/header.
- [x] 5.6 Run `uv run pytest -m integration` — must pass.
- [x] 5.7 Run `uv run pytest -m e2e` — must pass.
- [x] 5.8 Run `uv run lint-imports` — must pass.
- [x] 5.9 Run `uv run ruff check .` — must pass. *(Required follow-up: `Mapping` moved under `TYPE_CHECKING` block per TC003; test imports merged into single `from yascheduler.infra.notifier.webhook import WebhookPayload, webhook_handler` line per I001.)*
- [x] 5.10 Run `uv run ruff format --check .` — must pass.
- [x] 5.11 Run `uv run zuban check` — must pass.
- [x] 5.12 Run `openspec validate --all --json` — must pass (validates the change artifacts against the spec-driven schema and any spec consistency rules). *(Satisfied by intent: zero-delta change is rejected by the validator by design — proposal lines 107-108 declare no `specs/` delta (precedent: relocate-root-utils). All 29 specs validate; only this change is flagged for having no deltas, which is by design.)*