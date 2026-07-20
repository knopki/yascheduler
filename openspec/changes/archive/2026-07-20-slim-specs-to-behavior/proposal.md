## Why

Several capabilities in `openspec/specs/` carry content that no longer pays for
its keep:

- Backward-compat assertions about legacy code that was removed long ago (e.g.
  `yascheduler.db.TaskStatus`, `yascheduler.aiida_plugin`, `[local]
  cloud_package_upgrade`). They assert absence of artifacts nobody remembers
  existed.
- Redundancy between capabilities — the `logging` contract is restated inside
  `e2e-testing`'s `log_records` requirement (two places, same rule, drift risk).
- Implementation-level detail (exact filesystem paths the init probe reads,
  introspection mechanics of `LogFormatter`) that already lives in the
  corresponding code contracts (`MODULE_CONTRACT` INVARIANTS / SCOPE).

The project has an established pattern — "the spec keeps the behavioral rule;
the exhaustive detail lives in code contracts" — applied inconsistently. This
change applies it more uniformly so specs stay lean and behavior-focused.

## What Changes

Three kinds of edits, all spec-only (no behavior, no API, no schema change):

1. **Drop outdated backward-compat assertions** — scenarios whose only point
   is to forbid use of removed legacy symbols; the positive behavior they
   accompany is already covered by another scenario in the same capability.
2. **Drop duplication between capabilities** — a scenario in one capability
   that re-asserts a contract owned by another capability is removed; the
   authoritative capability keeps the contract.
3. **Move implementation hints out of specs** — scenarios whose only assertion
   is "the code is NOT a hardcoded literal" or restatements of code-internal
   branching become the job of the code contract; behavioral scenarios stay.

No requirements are added; a small number of scenarios are dropped or merged.
Modified capabilities: `config-value-objects`, `e2e-testing`, `logging`,
`package-facades`, `test-db-integration`, `cli`.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `config-value-objects`: drop the historical "legacy `[local]
  cloud_package_upgrade` warns as unknown" scenario (relocation is finalized).
- `e2e-testing`: collapse the two `log_records` propagation scenarios into one
  fixture-description line that defers the propagation contract to the
  `logging` capability; remove the duplicated restatement.
- `logging`: drop the "is NOT a hardcoded literal" / "is derived by
  introspection" implementation-hint scenarios — these describe code-internal
  mechanics already captured by the formatter module's contract; keep the
  behavioral rendering scenarios.
- `package-facades`: drop the "Old deep paths are gone" scenario and the
  historical "BREAKING change" framing in the `Yascheduler facade public
  contract`; both are transition artifacts.
- `test-db-integration`: drop the "Test asserts status against
  `domain.TaskStatus`" scenario — its positive content is already implied by
  "Status assertions SHALL use `yascheduler.domain.TaskStatus`" in the same
  requirement.
- `cli`: tighten the `yainit` service-install scenarios (`yainit detects
  systemd via /run/systemd/system`, `yainit detects non-systemd host`, and
  `daemon_sysv configure_logger inside DaemonContext`) so they assert
  behavior (which file gets written under which condition, that
  `configure_logger` runs inside the daemon context) without restating the
  exact probe path strings the code uses.

## Impact

- `openspec/specs/` — six capability spec files lose scenarios or lines; no
  requirements added, no behavioral requirements removed.
- Code contracts (`yascheduler/**/*.py` `MODULE_CONTRACT` regions) — no
  mandatory edits; where a removed scenario's content already lives in a code
  contract, that contract is the canonical home and is left as-is. If a future
  task uncovers a gap (detail moved out of spec but not present in code), the
  corresponding code contract is enriched as part of that task — never by
  inventing new fields.
- Tests — existing tests that mirrored the dropped scenarios are expected to
  remain valid because the underlying behavior they assert is preserved by
  sibling scenarios; task planning will surface any test that needs adjustment.
- Public API, DB schema, INI format, CLI surface — unchanged.
