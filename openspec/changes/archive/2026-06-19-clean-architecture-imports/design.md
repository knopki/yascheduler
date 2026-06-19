## Context

The proposal (frozen) establishes WHY: cross-layer imports bypass `__init__.py` facades today, hiding the dependency direction and letting R3 violations slip in. This design explains HOW: which `import-linter` contract type, why the dependency is pinned, how `ignore_imports` is used pragmatically, and what the migration looks like.

Two architectural inputs constrain this design:

- The OpenSpec specs already encode a layered architecture (`domain-ports`, `domain-services`, `use-cases`, `platform-adapters`). This change does not invent layering — it makes the existing layering enforceable.
- The codebase has two real R3 violations in `application/consume_task.py` and `application/orchestrator.py`. Properly fixing them requires a gateway SFTP refactor (`get_sftp()` leaks a raw asyncssh `SFTPClient`); that work is deferred to follow-up change `gateway-sftp-wrapping` (scaffolded). Until then, the two violations are documented residual.

## Goals / Non-Goals

**Goals:**
- Convert R3 (layer direction `adapters → application → domain`) from convention to hard-enforced via `import-linter`.
- Establish each subpackage's `__init__.py` as its only public surface (R2), with a lazy publication policy.
- Establish relative-within-package as the import style (R1).
- Make existing R3 violations explicit (`ignore_imports`) rather than hidden.
- Provide a single CI-checkable artifact (`lint-imports` exit 0/1) that protects the layer direction going forward.

**Non-Goals:**
- Enforce R1 or R2 with tooling. Linter's only hard job is R3. R1/R2 are convention + spec.
- Fix the two residual R3 edges. That is the follow-up change's job.
- Touch `db.py`, `aiida_plugin.py`, `client.py`, `compat.py`, or trim `adapters/ssh/platform/__init__.py`.
- Bump Python version or introduce a custom `import-linter` contract type.
- Refactor the SSH gateway's SFTP surface.

## Layering

```
                  ┌────────────────────────────────────────────┐
                  │  composition root (R2 only, exempt R3)      │
                  │  scheduler.py  di.py  client.py             │
                  │  db.py (legacy, untouchable)                │
                  └─────────────────────┬──────────────────────┘
                                        │  uses facades only
                                        ▼
   ╔═════════════════════════════════════════════════════════════╗
   ║  layers contract (R3 enforced via import-linter)             ║
   ║                                                              ║
   ║  ┌────────────────────┐   ← adapters/__init__.py             ║
   ║  │ yascheduler.       │     (currently empty — facade)       ║
   ║  │   adapters         │                                      ║
   ║  └─────────┬──────────┘                                      ║
   ║            │ uses                                             ║
   ║            ▼                                                  ║
   ║  ┌────────────────────┐   ← application/__init__.py           ║
   ║  │ yascheduler.       │     (currently empty — facade)       ║
   ║  │   application      │                                      ║
   ║  └─────────┬──────────┘                                      ║
   ║            │ uses                                             ║
   ║            ▼                                                  ║
   ║  ┌────────────────────┐   ← domain/__init__.py                ║
   ║  │ yascheduler.       │     (extended: model + DomainError    ║
   ║  │   domain           │      tree + ports, in addition to     ║
   ║  └────────────────────┘      events already exported)         ║
   ╚═════════════════════════════════════════════════════════════╝

       shared infra (outside layer set, anyone may import):
         yascheduler.config    yascheduler.data

       top-level single-file modules (outside layer set, R2 applies):
         yascheduler.compat       (internal utility)
         yascheduler.aiida_plugin (separate stable entry point)

   Documented R3 residual (suppressed via ignore_imports
   until follow-up gateway-sftp-wrapping):
       application.consume_task ──→ adapters.ssh.exceptions
       application.orchestrator ──→ adapters.ssh.exceptions
```

The full enumeration of outside-layer-set modules and their treatment is pinned in the `package-facades` spec; the diagram above is the summary.

## Decisions

### D1. Use `layers` contract type, not `forbidden` or custom

The `import-linter` library offers `layers`, `forbidden`, `protected`, `independence`, and a custom-contract API.

- `layers` matches our mental model directly: declare an ordered list, the contract enforces "higher may import lower, lower may not import higher" including indirect imports. One config block, zero custom code.
- `forbidden` would require enumerating every forbidden deep path per layer (`yascheduler.domain.model`, `yascheduler.domain.exceptions`, `yascheduler.domain.ports`, …). Brittle — every new submodule needs a new line; easy to forget.
- Custom contract (e.g., to enforce R2 facade-only imports) is overkill for the only hard rule we care about (R3). Rejected in explore phase.

**Alternative considered**: maintain a static `forbidden_modules` list and accept the brittleness. Rejected because the value of `layers` (zero-maintenance direction enforcement) is much higher than the value of `forbidden` (per-path granularity we do not need).

### D2. Pin `import-linter >=2.5,<2.6`

`import-linter 2.6` (released 2025-11-10) dropped Python 3.9 support. Project pins `python >=3.9` in `pyproject.toml`.

- We pin `>=2.5,<2.6` to keep the constraint satisfied without forcing a Python bump.
- When the project later moves to `python >=3.10`, the pin can be lifted in the same change that bumps Python.

**Alternative considered**: bump Python to 3.10 as part of this change. Rejected — Python bump is a separate decision with its own scope (CI matrices, dev environments, downstream consumers).

### D3. `exclude_type_checking_imports = true`

Four files in `application/` import adapter symbols under `if TYPE_CHECKING:` guards for type annotations only. These are not runtime dependencies — they do not violate the layer direction in any meaningful sense, because no runtime call crosses the boundary.

- With `exclude_type_checking_imports = true`, the layers contract ignores them.
- The two real module-level violations in `consume_task.py` and `orchestrator.py` are still caught.

**Alternative considered**: leave the flag off and convert all `TYPE_CHECKING` imports to runtime imports under `ignore_imports`. Rejected — `TYPE_CHECKING` is the correct idiom for type-only references, and `exclude_type_checking_imports` is the library's intended mechanism for exactly this case.

### D4. Two `ignore_imports` entries as documented residual

The layers contract will include:

```toml
ignore_imports = [
    "yascheduler.application.consume_task -> yascheduler.adapters.ssh.exceptions",  # superseded post-migration → "yascheduler.adapters" (layer facade)
    "yascheduler.application.orchestrator -> yascheduler.adapters.ssh.exceptions",  # superseded post-migration → "yascheduler.adapters" (layer facade)
]
```

This is the pragmatic choice given the gateway SFTP refactor deferral. The alternatives explored in explore phase:

- **Variant b (tuples inherit)**: impossible — `SFTPRetryExc` is a tuple of third-party classes.
- **Variant c done in this change**: requires gateway `get_sftp` removal + wrapped SFTP methods + 4+ call-site migrations. Scope creep.
- **Variant D (`abc.register` magic)**: works but unreadable.
- **Variant E (accept violation via `ignore_imports`)**: chosen, with the explicit commitment that follow-up `gateway-sftp-wrapping` removes both entries.
- **Variant F (move all retry into gateway, drop application backoff)**: cleanest architecturally but changes retry semantics (currently two-layer: gateway internal + application backoff). Out of scope for this change. The follow-up `gateway-sftp-wrapping` brief re-opens F as a deferred decision; that change may adopt it.

The follow-up change is scaffolded with a full explore-brief at `openspec/changes/gateway-sftp-wrapping/explore-brief.md` so the design context is preserved.

**Mitigation against permanent residue**: the `package-facades` spec will document these two edges as a known wart that must be removed by the follow-up change. The follow-up change is tracked in `openspec/changes/` and visible in `openspec list`.

### D5. Lazy facade policy (Variant B)

Each subpackage's `__init__.py` exposes only the symbols that external consumers actually need. Adding to a facade is a deliberate act.

**Alternative considered**: Variant A — re-export everything not prefixed with `_`. Rejected because it produces grab-bags (see existing `adapters/ssh/platform/__init__.py`, 180 lines, where trimming is now a separate cleanup change). Variant A loses the encapsulation benefit and turns `__init__.py` into a maintenance burden.

Consequence: four currently-empty facades (`application/__init__.py`, `adapters/__init__.py`, `adapters/notifier/__init__.py`, `adapters/ssh/__init__.py`) stay empty until a real consumer needs a symbol. The spec will state this explicitly so reviewers do not interpret emptiness as incompleteness.

### D6. Capability name `package-facades`

Name inherited from the frozen proposal. Rationale (recorded there): the facade is the central concept that ties R1/R2/R3 together; naming the capability after the facade rather than the layers emphasizes the structural device over one of its rules.

### D7. Normalize `adapters/cli/__init__.py` to relative imports

Currently uses `from yascheduler.adapters.cli.check_status import check_status` (absolute self-reference). Per R1, should be `from .check_status import check_status`. Trivial mechanical change, included in this change as the only existing R1 violation the audit found at a package's own `__init__.py`.

Other `__init__.py` files were audited and judged acceptable as-is (no mandatory change in this change):
- `yascheduler/config/__init__.py` — already a rich, reasonable facade.
- `yascheduler/adapters/persistence/__init__.py` — already exposes what consumers need.
- `yascheduler/adapters/cloud/__init__.py` and `yascheduler/adapters/cloud/providers/__init__.py` — reasonable.
- `yascheduler/adapters/ssh/platform/__init__.py` — over-exported (180 lines), but trimming is a separate concern (brief open question #4; out of scope).

### D8. Extend `domain/__init__.py` facade

Today only `events` is re-exported. The dominant cross-layer pattern is `from yascheduler.domain.model import Task` and `from yascheduler.domain.exceptions import ...` — bypassing the facade. The fix: re-export model, exceptions (existing `DomainError` tree only — no new symbols), and ports (`TaskRepository`, `NodeRepository`, `MachineGateway`, `CloudProvisioner`) from `domain/__init__.py`.

The exact symbol list is pinned in the spec; design only commits to "model, exceptions tree, ports" as the three buckets.

## Risks / Trade-offs

| Risk | Mitigation |
| --- | --- |
| `ignore_imports` becomes permanent (follow-up change never lands) | Follow-up `gateway-sftp-wrapping` is scaffolded with full explore-brief; spec documents the residual; visible in `openspec list`. |
| `lint-imports` surfaces a 3rd R3 edge not anticipated by static inspection (indirect imports are caught by the `layers` contract) | Policy: do NOT extend `ignore_imports` ad hoc. If the 3rd edge is the same shape (application→adapter transient exception), document it and add to `ignore_imports` with a matching follow-up note. If it is a different shape (real architectural leak), block the change and fix forward. |
| `import-linter 2.5.x` stops receiving security fixes | Acceptable for a dev-only linting tool. When project bumps Python to 3.10+, lift the pin. |
| `exclude_type_checking_imports` could mask a future runtime import that someone accidentally moves out of `TYPE_CHECKING` | The spec calls out that `TYPE_CHECKING` is for type-only references; runtime references must not live there. Code review enforces. |
| Empty facades (`application/__init__.py`, etc.) confuse contributors into adding symbols they should not | Spec states the lazy policy explicitly. AGENTS.md TRIGGER pointer references the spec. |
| `lint-imports` adds CI time | Tested on a project this size: sub-second runtime. Negligible. |

**Concentration note**: R1 and R2 have no tooling enforcement. Three rows above depend on the same mitigation chain: spec text + AGENTS.md TRIGGER pointer + code review. If the AGENTS.md edit is reverted or code review skips the check, R1/R2 are unenforced. This is intentional — the value of this change is R3 enforcement plus documented R1/R2; full R1/R2 enforcement is a separate decision (see design Open Questions).

## Migration Plan

Single-PR change. No runtime behavior change. No data migration. Steps in order:

**Code & config (1–4):**

1. Add `import-linter >=2.5,<2.6` to dev dependencies.
2. Add `[tool.importlinter]` section to `pyproject.toml` with `root_package`, `exclude_type_checking_imports`, single `layers` contract, and two `ignore_imports` entries.
3. Extend `yascheduler/domain/__init__.py` to re-export model, exceptions tree, and ports. Bump the file's `CHANGE_SUMMARY` (GRACE-lite).
4. Normalize `yascheduler/adapters/cli/__init__.py` to relative imports. Bump the file's `CHANGE_SUMMARY` (GRACE-lite).

**GRACE-lite knowledge graph (5–6):**

5. Update `docs/knowledge-graph.xml`: `<M-DOMAIN>` currently declares `<depends>M-DOMAIN-EVENTS</depends>` — extend to `M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-PORTS` to reflect the facade's expanded public surface. No new `M-*` entries needed (the modules already exist in the graph). Also update the existing `<CrossLink from="M-DOMAIN" to="M-DOMAIN-EVENTS" relation="re-exports event types from domain package" />` (knowledge-graph.xml:783) — broaden its `relation` text (e.g., "re-exports events, model, exceptions, ports from domain package") or add three new `M-DOMAIN → M-DOMAIN-{MODEL,EXCEPTIONS,PORTS}` CrossLinks.
6. Run `python3 scripts/grace_check.py` — must exit 0.

**Specs & docs (7–8):**

7. Acknowledge four empty facades (`application/__init__.py`, `adapters/__init__.py`, `adapters/notifier/__init__.py`, `adapters/ssh/__init__.py`) — no code change, just spec'd as official surface.
8. Add `openspec/specs/package-facades/spec.md` (Batch 3 of this proposal). Add TRIGGER pointer to `AGENTS.md`.

**CI (9):**

9. Add `lint-imports` invocation to `.github/workflows/lint.yml` (the existing lint workflow that runs `ruff format`, `ruff check`, `zuban check`).

**Verification (10–11):**

10. Standard verification ladder per AGENTS.md: `uv run pytest -m unit`, `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, plus `lint-imports` (must exit 0).
11. `openspec validate --all --json` (must pass), plus a smoke check that `from yascheduler.domain import Task, TaskRepository, DomainError, TaskCreated` resolves.

**Rollback**: revert the PR. No state to recover. The four empty facades and the existing R3 violations were already in the codebase before this change.

## Open Questions

1. **Partial R1 enforcement via ruff `TID251`?** The proposal defers this (R1 is convention-only for now). Could be added later as a small follow-up if convention proves insufficient. Not blocking.
2. **Should `adapters/ssh/platform/__init__.py` 180-line over-export be trimmed in a follow-up?** Out of scope here. The smell is acknowledged in the spec; a separate change can tackle it.
