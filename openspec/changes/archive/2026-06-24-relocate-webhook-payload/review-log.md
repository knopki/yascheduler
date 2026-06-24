# Review Log — relocate-webhook-payload

## proposal Round 1 — 2026-06-24

### 🔴 Fixed

- None (first review, no prior issues).

### 🟡 Addressed

- **`_send_webhook` contract still links M-WEBHOOK** — `yascheduler/infra/notifier/webhook.py:93` has `LINKS: M-WEBHOOK` inside `START_CONTRACT: _send_webhook`. After the merge, this LINKS entry must be removed (or changed to `M-NOTIFIER-WEBHOOK`) since `WebhookPayload` is now defined locally. The proposal covers file-level MODULE_CONTRACT/MAP/CHANGE_SUMMARY rewrites but doesn't explicitly mention this per-contract link. Easy to miss; the implementer should update it.

- **Rejected alternative B (inline dict) not listed as non-goal** — The brief rejected deleting the DTO and inlining a raw dict in `_send_webhook`. The proposal's positive "What Changes" clearly describes absorbing the class (the opposite of inlining), but the non-goal list doesn't explicitly rule it out. Minor — the positive language suffices.

- **webhook-handler spec reference phrasing** — Proposal claims webhook-handler/spec.md "mandates the `WebhookPayload` field contract (`task_id`/`status`/`custom_params`)". The spec describes the POST body shape through handler scenarios but never names the `WebhookPayload` symbol. This doesn't affect the correctness of the "Modified Capabilities: None" conclusion (the spec indeed has no import-path references), but the wording is slightly loose.

### 🔴 Outstanding

- None.

## design Round 1 — 2026-06-24

### 🔴 Fixed

- None.

### 🟡 Addressed

- **`_send_webhook` per-contract LINKS (proposal Round 1 🟡)** — D3 explicitly rewrites `LINKS: M-WEBHOOK` → `M-NOTIFIER-WEBHOOK` in the `_send_webhook` contract. The `webhook_handler` contract (`LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL`) is confirmed unaffected. Resolved.

- **Rejected alternative B as non-goal (proposal Round 1 🟡)** — Non-Goals section now includes "No inline-dict replacement of the DTO (rejected as alternative B in exploration — loses named constructor and existing construction/default-params tests)." Also listed under D1 alternatives. Resolved.

- **Spec phrasing looseness (proposal Round 1 🟡)** — Design does not inherit or compound the loose phrasing about `webhook-handler/spec.md`. The word "mandates" does not appear in design.md. Resolved.

### 🔴 Outstanding

- **D2 grep count mismatch** — D2 (line 135) claims `grep -n "M-WEBHOOK" docs/knowledge-graph.xml` "returns exactly 3 matches: line 30 (record opening), line 696 (`<depends>` token), line 909 (`CrossLink`)." Actual output has **4** matches — line 37 (`</M-WEBHOOK>`) is also a match and is not listed. This is a factual inaccuracy. **Not a blocker**: line 37 is the closing tag of the `<M-WEBHOOK>` record (lines 30–37); deleting the entire block removes it implicitly. The implementation is unaffected. An implementer should be aware the count is 4 (or just trust the block range 30–37).

No other 🔴 issues found. All risks are appropriately identified and mitigated. Architectural alignment is preserved (infra → domain dependency direction unchanged). No scope violations — design stays within proposal boundaries. All proposal "What Changes" bullets map to concrete D1–D6 decisions. All three Round 1 🟡 items are explicitly resolved.

## specs Round 1 — 2026-06-24

### 🔴 Fixed

- None.

### 🟡 Addressed

- None.

### 🔴 Outstanding

- None.

### Note

No `specs/` delta files produced. Per the frozen proposal's Capabilities
section ("New Capabilities: None" / "Modified Capabilities: None"),
this change is a behavior-preserving internal relocate with no spec-level
requirement changes. Verified `openspec/specs/webhook-handler/spec.md`
references the `WebhookPayload` field contract only through handler
scenarios (no import-path pin), and `openspec/specs/testing-unit/spec.md`
line 231 references the `WebhookPayload` *symbol* (constructor +
default-`custom_params` scenario), not its import path. The symbol's name
and shape are unchanged by this relocate. Precedent:
`openspec/changes/relocate-root-utils` (no `specs/` subdir either).
