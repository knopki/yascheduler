## Context

yascheduler has no formalized development conventions. Rules exist informally in AGENTS.md and code configuration. This change captures them as a spec.

## Goals / Non-Goals

**Goals:**
- Single authoritative document for development rules
- Establish public interface stability guarantees
- Fix tooling: replace pyright with zuban

**Non-Goals:**
- Detailed ruff/zuban configuration (lives in pyproject.toml)
- Approved library list (rule-based, not list-based)
- Changing any public interface behavior

## Decisions

- **Zuban over pyright**: zuban is the chosen type checker. No configuration required. pyright and its `[tool.pyright]` section are removed.
- **Rule-based dependency policy**: Instead of an approved list, the rule is "no new dependency without explicit intent in the change proposal." This avoids duplicating pyproject.toml.
- **Single spec `development-conventions`**: All convention rules in one capability. They're tightly coupled (tooling, interface stability, methodology) and don't warrant separate specs.

## Risks / Trade-offs

- [Zuban may have different behavior than pyright] → Minimal risk: project uses basic type annotations, no advanced pyright features.
- [Convention spec may become stale if not updated with real changes] → Mitigated by OpenSpec workflow: any tooling/version change naturally goes through proposals.
