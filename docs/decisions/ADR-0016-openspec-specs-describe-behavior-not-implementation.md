# ADR-0016: OpenSpec specs describe behavior, not implementation

- **Status:** Accepted
- **Date:** 2026-07-28
- **Supersedes:**
- **Superseded by:**

## Context

The 22 specs in `openspec/specs/` grew to ~5 000 lines. An audit found
that ~60 % of the text does not describe system behavior. It restates
the code. The drift pattern is consistent across every spec:

- A requirement quotes Python signatures, parameter names, and return
  types.
- A scenario tests Python language mechanics. Examples: a function is
  `async def`; a class is a `@runtime_checkable` Protocol; a value is
  a `StrEnum`; `hash(obj)` raises `TypeError`.
- A field, an enum value, or an event type gets its own scenario. The
  requirement text already lists the full set in a table.
- A test plan or fixture name is written as a requirement. Examples:
  pytest markers, `session-scoped` fixtures, teardown SQL, container
  images.
- A log marker, an exception subclass, or an import path is locked in
  as a stable contract.

The result: a spec reads like a `pydoc` page with unit-test bodies
inside it. The text grows on every change. The text breaks on every
refactor. An operator cannot read it.

The choice: what an OpenSpec spec shall describe, and what it shall
not.

## Decision

1. **Specs describe behavior.** A requirement states what the system
   does, observed from outside. A scenario states one distinct,
   observable outcome. An observer is a user, a client, or a reader
   of a log line — never the source code.

2. **The verifier test.** A scenario is valid only if an external
   observer can verify it without reading the source. If two scenarios
   differ only in the field, the command, or the provider, they are
   one scenario.

3. **Implementation stays out of specs.** Specs do not quote Python
   signatures, parameter names, async markers, decorator names,
   class names, import paths, dict keys, or attribute names. Specs do
   not test Python language guarantees (`isinstance`, `hash`, `repr`,
   enum lookup, structural subtyping).

4. **One behavior, one scenario.** A requirement that has N branches
   gets at most two scenarios: the happy path and the failure path.
   A set listed in a table (enum values, event types, exception
   subclasses, JSON fields) gets zero scenarios per item. The table
   is the spec.

5. **Negative scenarios are forbidden when a positive statement
   covers them.** "Does NOT call X", "is never constructed", "no
   import of Y" — delete. The positive rule is the contract.

6. **Test artifacts are not specs.** Fixture names, scopes, teardown
   SQL, container images, and pytest markers belong in the test
   suite. A spec states the test boundary: "tests run against a real
   PostgreSQL instance with schema applied and per-test isolation."

7. **Algorithm choices go to ADRs, not specs.** Time bounds, retry
   counts, backoff formulas, lock mechanisms, and complexity claims
   are decisions with alternatives. They live in `docs/decisions/`.
   A spec states the outcome: "transient failures are retried."

8. **One concept, one word.** No synonyms. The same idea uses the
   same noun everywhere. ASD-STE100 Simplified Technical English is
   the target register: short sentences, active voice, one idea per
   sentence, no vague modifiers ("some", "various", "etc."),
   imperative for rules.

9. **Cross-file duplication is a defect.** A rule lives in one spec.
   Other specs reference it; they do not restate it.

## Alternatives Considered

### Keep the spec-as-test-case style

Rejected. The style already produced ~3 000 lines of bloat across 22
files. Every refactor breaks the spec. Every new field adds a
scenario. The drift is the pattern, not the exception.

### Split each spec into two documents: behavior spec + implementation doc

Rejected. Two documents drift. The implementation doc copies the
code. The spec copies the implementation doc. One source — the code
— is enough for signatures and structure. The spec covers only what
the code does not show: the observable contract.

### Delete the specs; let the code be the contract

Rejected. The code does not state the public surface. CLI flags, INI
keys, exit codes, JSON schemas, and DB shape are contracts that
survive refactors. A spec that lists only these is short and stable.

## Consequences

- **Positive:** Specs shrink to ~40 % of their current size. The
  surviving text states contracts that an operator, a client, and a
  reviewer can read in minutes.
- **Positive:** Refactors that change a signature, a class name, or
  an import path no longer touch the spec.
- **Positive:** A new field, event type, or exception subclass adds
  one row to a table — not one scenario.
- **Negative / trade-offs:** A reader who wants the exact Python
  signature reads the code. The spec does not answer that question.
  Accepted — `pydoc`, the type checker, and the IDE already answer
  it.
- **Negative / trade-offs:** ASD-STE100 discipline is manual. A
  reviewer must apply the verifier test on every change.
- **Accepted risks:** Without a guard, maintainers will re-bloat the
  specs. A pre-commit hook that rejects signature characters (`def`,
  `->`, `:`, `@`) inside `openspec/specs/` is the recommended
  follow-up; this ADR does not mandate it.
