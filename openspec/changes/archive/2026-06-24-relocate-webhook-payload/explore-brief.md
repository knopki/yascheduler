# Explore Brief: relocate-webhook-payload

## Context

`yascheduler/webhook.py` (33 lines) defines a single frozen dataclass
`WebhookPayload(task_id: int, status: int, custom_params: Mapping[str, Any])`.
It sits at the package root. Its sole production consumer is
`yascheduler/infra/notifier/webhook.py` (the `webhook_handler` adapter); its
sole test consumer is `tests/unit/test_webhook_handler.py`. No other importer
exists.

The file carries a standing `# FIXME: decide: move to domain?` annotation.
Exploration concluded the payload is a wire-format DTO (outbound HTTP POST body
shape: `status` stores `TaskStatus.value` int, not the enum), so it belongs
next to its consumer in `infra/notifier/`, not in `domain/`. Putting it in
`domain/` would import an infra wire-format contract into the domain layer.

## Rejected Alternatives

- **A.0 — keep at root.** Rejected: root is mid-migration (per
  `relocate-root-utils` proposal, `time.py`/`queue.py` are being relocated;
  `variables.py`/`compat.py` already moved to `shared/`). Root `webhook.py`
  is the same category of misplaced root utility.
- **A.2 — new `infra/notifier/payload.py`.** Rejected: adds a 33-line file
  for one consumer + one test consumer + 3 fields. YAGNI; filename collision
  resolution isn't worth the extra file. Earns its own file only if a second
  consumer appears.
- **A.3 — re-export `WebhookPayload` from `infra/notifier/__init__.py`
  facade.** Rejected: payload is internal to notifier, not a cross-layer
  contract. Consistent with `relocate-root-utils` non-goal ("NOT re-export
  `UniqueQueue`/`UMessage` — internal to orchestrator").
- **B — delete DTO, inline dict in `_send_webhook`.** Rejected: loses named
  constructor + tests of construction/default-params; `asdict()` works on
  dataclass, would need manual dict assembly.
- **C — remove `webhook_url`/`webhook_custom_params` from `DomainEvent`
  base.** Out of scope. Explicitly deferred: leaves `# FIXME` at
  `DomainEvent` as the open thread. User confirmed: Task carries webhook
  fields from client submission, so they belong in `Task`/`TaskContext`
  (already there). Whether `DomainEvent` should also carry them is a
  separate design question about event-channel shape, not about this file.
- **Move to `domain/`.** Rejected: payload is outbound wire format (ints
  and a loose dict), not a domain concept. Domain already has
  `TaskContext.webhook_url` / `webhook_custom_params`.

## Final Approach (A.1)

Merge `WebhookPayload` dataclass into the existing
`yascheduler/infra/notifier/webhook.py`, delete the root
`yascheduler/webhook.py`, update the one test import site, fix graph +
ARCHITECTURE.md.

### Mapping: files touched

| File                                    | Action                                                              |
| --------------------------------------- | ------------------------------------------------------------------- |
| `yascheduler/infra/notifier/webhook.py` | Absorb `WebhookPayload`; drop `from yascheduler.webhook import`; update MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY |
| `yascheduler/webhook.py`                | Delete (root emptied of this file)                                   |
| `tests/unit/test_webhook_handler.py`    | Line 49 import: `from yascheduler.webhook` → `from yascheduler.infra.notifier.webhook` |
| `docs/knowledge-graph.xml`              | Delete `M-WEBHOOK` (lines 30–37); remove `M-WEBHOOK` from `M-NOTIFIER-WEBHOOK`'s `<depends>` (line 696); delete `CrossLink` at line 909 |
| `docs/ARCHITECTURE.md`                  | Lines 85, 121, 257–258, 457: drop root `webhook.py`/`WebhookPayload`; it's now an internal of notifier |

### Cross-module data flow (unchanged)

```
DomainEvent (carries webhook_url, webhook_custom_params, task_id)
    │
    ▼
webhook_handler(event, http)         [infra/notifier/webhook.py]
    │  maps event → TaskStatus.value
    │  builds WebhookPayload(task_id, status, custom_params)   ← co-located now
    ▼
_send_webhook(url, payload, http)
    │  asdict(payload) → HTTP POST body
    ▼
external HTTP endpoint
```

No call-graph change. Only the definition site of `WebhookPayload` moves.

### Ghosts that dissolve on merge

1. `yascheduler/webhook.py:8` `LINKS: M-APPLICATION-ORCHESTRATOR` — wrong;
   orchestrator never touches payload. File deleted → ghost vanishes.
2. `M-WEBHOOK TYPE="CORE_LOGIC"` — misclassified; it's a DTO. Merged into
   `M-NOTIFIER-WEBHOOK` (TYPE=INTEGRATION) → correct type wins.

Both are auto-resolved by the merge; no separate fix tasks.

## Open Questions

1. **Should `WebhookPayload` be re-exported from
   `yascheduler/infra/notifier/__init__.py`?** Decision: NO. Payload is
   internal; tests use deep import path (precedent: `relocate-root-utils`
   tasks.md §1.3 / non-goal). Confirm during proposal review.

2. **Does deleting `M-WEBHOOK` from the graph leave any dangling
   `CrossLink`/`<depends>` tokens elsewhere?** Verified: only line 696
   (`M-NOTIFIER-WEBHOOK` depends) and line 909 (`CrossLink`) reference it.
   No `M-APPLICATION-ORCHESTRATOR` dependency on `M-WEBHOOK` — its
   `<depends>` uses `M-NOTIFIER-WEBHOOK`. Will re-grep during design.

3. **Backward-compat shim at `yascheduler.webhook`?** Decision: NO. Not
   public API (per `AGENTS.md` public-surface enumeration: CLI commands,
   `class Yascheduler`, INI format, DB schema, AiiDA entrypoint — import
   paths are not in the list). Precedent: `relocate-root-utils` non-goal
   "No backward-compatibility shim, no deprecation period, no re-export
   alias at the old paths. Internal relocations do not get shims."

4. **Should `TestWebhookPayload` test class (lines 205+) move to a separate
   test file?** Decision: NO. Stays in `test_webhook_handler.py`; only the
   import line changes. Precedent: `relocate-root-utils` "No relocation of
   `tests/unit/test_queue.py` itself — flat `tests/unit/` layout, no
   per-layer subdirectories, no precedent for one."