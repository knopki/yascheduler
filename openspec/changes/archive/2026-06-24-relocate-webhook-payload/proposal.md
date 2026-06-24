## Why

`yascheduler/webhook.py` defines a single 33-line frozen dataclass
`WebhookPayload` at the package root. Its sole production consumer is
`yascheduler/infra/notifier/webhook.py` (`webhook_handler` adapter); its sole
test consumer is `tests/unit/test_webhook_handler.py`. No other importer
exists. The file carries a standing `# FIXME: decide: move to domain?`.

Exploration concluded `WebhookPayload` is an outbound wire-format DTO
(`status` stores `TaskStatus.value` int, not the enum; `custom_params` is a
loose `Mapping[str, Any]`), not a domain concept — it does not belong in
`domain/`. It belongs next to its consumer in `infra/notifier/`. The root is
mid-migration: `variables.py`/`compat.py` already relocated to `shared/`
(v1.6.0), and `time.py`/`queue.py` are being relocated by the in-flight
`relocate-root-utils` change. `yascheduler/webhook.py` is the same category
of misplaced root utility and finishes the cleanup.

## What Changes

- **Merge** `WebhookPayload` frozen dataclass from `yascheduler/webhook.py`
  into the existing `yascheduler/infra/notifier/webhook.py` (above
  `webhook_handler`). Drop the `from yascheduler.webhook import
  WebhookPayload` line in that file.
- **Delete** `yascheduler/webhook.py` entirely (root emptied of this file).
- **Rewrite** the GRACE-lite `MODULE_CONTRACT`/`MODULE_MAP`/`CHANGE_SUMMARY`
  of `yascheduler/infra/notifier/webhook.py` to declare `WebhookPayload` as
  part of its scope and to record the relocation in `CHANGE_SUMMARY`.
- **Rewrite** the import in `tests/unit/test_webhook_handler.py` line 49:
  `from yascheduler.webhook import WebhookPayload` →
  `from yascheduler.infra.notifier.webhook import WebhookPayload`. No test
  bodies, fixtures, or assertions change. `TestWebhookPayload` (lines 205+)
  stays in this file — only its import line moves.
- **NOT re-export** `WebhookPayload` from
  `yascheduler/infra/notifier/__init__.py` nor from
  `yascheduler/infra/__init__.py`. Payload is internal to notifier; tests
  use the deep path `from yascheduler.infra.notifier.webhook import …`,
  consistent with the `relocate-root-utils` precedent for orchestrator
  internals (`UniqueQueue`/`UMessage`).
- **Update** `docs/knowledge-graph.xml`:
  - **Remove** the entire `<M-WEBHOOK>…</M-WEBHOOK>` record (lines 30–37).
    It is misclassified (`TYPE="CORE_LOGIC"` — it is a DTO) and carries a
    bogus `LINKS: M-APPLICATION-ORCHESTRATOR` (orchestrator never touches
    the payload). On merge, both ghosts dissolve: the payload's new home is
    `M-NOTIFIER-WEBHOOK` (`TYPE="INTEGRATION"`).
  - **Remove** the `M-WEBHOOK` token from `M-NOTIFIER-WEBHOOK`'s `<depends>`
    (line 696; becomes `M-DOMAIN-EVENTS, M-DOMAIN-MODEL`). Add a
    `<class-WebhookPayload PURPOSE="Webhook request data shape" />`
    annotation to `M-NOTIFIER-WEBHOOK`'s `<annotations>` block so the
    symbol stays navigable in the graph.
  - **Delete** the `<CrossLink from="M-NOTIFIER-WEBHOOK" to="M-WEBHOOK"
    relation="uses WebhookPayload for HTTP request serialization" />` entry
    (line 909). With `M-WEBHOOK` gone, this link points to a nonexistent
    module and `scripts/grace_check.py`'s `_check_depends_refs` would emit a
    hard ERROR (exit 1) on the unknown reference.
- **Fix doc drift** in `docs/ARCHITECTURE.md`: remove the root-level
  `webhook.py` / `WebhookPayload` entries — §1 layer diagram root block
  (~line 85), §3 layer-responsibility table (~line 121), §5 detailed prose
  (~lines 257–258), and §4 project tree (~line 457). `WebhookPayload` is now
  an internal of `infra/notifier/webhook.py`; no separate root entry.
- **Leave** `# FIXME: decide: move to domain?` at `DomainEvent` base
  (`yascheduler/domain/events.py`) untouched. That is a separate open
  question about whether domain events should carry delivery-channel fields
  (`webhook_url`/`webhook_custom_params`) — explicitly out of scope here.
  User confirmed `Task`/`TaskContext` legitimately carry these fields from
  client submission; the `DomainEvent` shape question is deferred.

Non-goals (explicitly out of scope):

- No public API change: `class Yascheduler`, CLI command names, INI format,
  DB schema, AiiDA entrypoint — all preserved. The `yascheduler.webhook`
  import path is NOT part of the public surface enumerated in `AGENTS.md`
  (CLI commands, `class Yascheduler`, INI config incl. `[engine.*]` and
  `%(key)s` interpolation, DB schema, AiiDA entrypoint).
- No backward-compatibility shim, no deprecation period, no re-export alias
  at `yascheduler.webhook`. Internal relocations do not get shims
  (precedent: `relocate-root-utils` non-goal).
- No rename of the symbol — `WebhookPayload` keeps its name; only its
  containing module changes.
- No change to `DomainEvent` / `TaskContext` field shape. The standing
  `# FIXME` at `DomainEvent` is left in place as the open thread.
- No change to test logic, fixtures, or assertions — only the single import
  path in `tests/unit/test_webhook_handler.py`.
- No relocation of `tests/unit/test_webhook_handler.py` itself — flat
  `tests/unit/` layout, no per-layer subdirectories, no precedent
  (`relocate-root-utils` non-goal).
- No splitting of `WebhookPayload` into its own `infra/notifier/payload.py`
  file — one consumer, one test consumer, three fields; YAGNI (rejected as
  A.2 in exploration).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. Verified by grep of `openspec/specs/` for `yascheduler.webhook`,
`yascheduler/webhook`, `WebhookPayload`, `M-WEBHOOK`: **zero import-path
references**. Two specs reference the symbol by name only:
- `webhook-handler/spec.md` — mandates the handler's import path
  (`yascheduler.infra.notifier.webhook`) and the `WebhookPayload` field
  contract (`task_id`/`status`/`custom_params`); neither changes here.
- `testing-unit/spec.md` line 231 — references `WebhookPayload` symbol
  (constructor + default-`custom_params` scenario); name unchanged.

No spec-level requirement changes; therefore no `specs/` delta files are
produced (precedent: `relocate-root-utils` "Modified Capabilities: None").

## Impact

- **Code**:
  - 1 deleted file: `yascheduler/webhook.py` (content merges into
    `infra/notifier/webhook.py`).
  - 1 modified file: `yascheduler/infra/notifier/webhook.py` — absorbs the
    `WebhookPayload` dataclass above `webhook_handler`; removes the
    `from yascheduler.webhook import WebhookPayload` line (currently line
    35); updates `MODULE_CONTRACT` (PURPOSE/SCOPE mention payload),
    `MODULE_MAP` (adds `WebhookPayload - Webhook request data shape`),
    `CHANGE_SUMMARY` (new entry recording the relocation). Bumps `VERSION`.
    File grows 107 → ~120 lines, within GRACE-lite 500-line soft limit.
- **Tests**: 1 modified file. `tests/unit/test_webhook_handler.py` line 49
  — single import rewrite. No test bodies, fixtures, or assertions change.
- **Docs**:
  - `docs/knowledge-graph.xml` — remove `M-WEBHOOK` record; migrate its
    `<class-WebhookPayload>` annotation into `M-NOTIFIER-WEBHOOK`;
    remove `M-WEBHOOK` token from `M-NOTIFIER-WEBHOOK` `<depends>`;
    delete the `M-NOTIFIER-WEBHOOK → M-WEBHOOK` `CrossLink`.
  - `docs/ARCHITECTURE.md` — fix root-level doc drift (remove stale root
    `webhook.py` / `WebhookPayload` entries from §1, §3, §4, §5;
    `WebhookPayload` is now internal to `infra/notifier/webhook.py`).
- **GRACE-lite anchors**: `# FILE:` / `MODULE_CONTRACT` / `MODULE_MAP` /
  `CHANGE_SUMMARY` inside `infra/notifier/webhook.py` rewritten to include
  `WebhookPayload` in scope and record the relocation.
- **Public API**: zero change.
- **Dependencies**: none added, none removed.
- **Verification**: `uv run pytest -m unit|integration|e2e`,
  `uv run lint-imports`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run zuban check`,
  `python3 scripts/grace_check.py`, and
  `openspec validate --all --json` must all pass after the relocation.
  Plus `grep -rn "yascheduler\.webhook\|yascheduler/webhook"
  --include="*.py" --include="*.xml" --include="*.md" yascheduler/ tests/
  docs/` must return zero matches after the relocation (except the
  `infra/notifier/webhook` path itself, which is legitimate).