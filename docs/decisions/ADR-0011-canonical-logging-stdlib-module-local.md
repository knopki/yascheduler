# ADR-0011: Canonical logging via stdlib module-local loggers

- **Status:** Accepted
- **Date:** 2026-07-15
- **Supersedes:**
- **Superseded by:**

## Context

The project needed a logging architecture that would let an operator
read a log line and map it back to the source location that produced
it, without consulting any auxiliary mapping artifact.

Two forces shaped the decision:

- **Observability.** Logs are the primary diagnostic surface for a
  long-running daemon. If the logger name does not point at the
  producing module, an operator chasing a misbehaviour has no anchor
  into the codebase.
- **Trace discipline.** To reason about runtime trajectory at debug
  time, the project needs block-boundary trace records with structured
  fields. The mechanism for emitting them must be uniform across every
  module; ad-hoc conventions drift.

## Decision

1. **Module-local logger binding via stdlib.** Every module binds its
  logger with `logging.getLogger(__name__)`, yielding names of the
  form `yascheduler.<dotted.module.path>`. The logger name is the
  provenance: no auxiliary mapping file is needed to find the source.

2. **Structured trace records at block boundaries.** Modules emit
  `logger.debug("BLOCK", extra={...})` at block boundaries. The
  positional message is the block marker; the structured fields ride
  in the flat `extra` dict, sorted alphabetically at render time. No
  wrapper function, no nested sentinel key — the stdlib `extra=`
  channel is used directly.

3. **One formatter discriminates trace records from regular records.**
  A record is rendered as a trace when all of: level is DEBUG, it
  carries user-supplied `extra` attributes beyond stdlib's native
  `LogRecord` set, and its logger is in-package. The native attribute
  set is derived by introspection at import time, so the
  discriminator adapts automatically to Python version changes.

## Alternatives Considered

### A custom `Logger` subclass with a project-specific trace method

Rejected — duplicates stdlib capability that `Logger.debug(msg, extra=...)`
already provides, and forces every module through a project-specific import and
factory.

### A wrapper function for trace emission

Rejected — adds an indirection over the stdlib call without enabling
anything `extra=` does not.

### A sentinel key inside `extra` to mark trace records

Rejected — reserves a name and forces every callsite to spell the
sentinel. The discriminator based on level + presence of extra + logger
provenance identifies traces without any reserved name.

### A hardcoded native `LogRecord` attribute set

Rejected — breaks silently when the Python version adds new native
attributes (e.g. `taskName` in 3.12). Introspection self-adapts.

## Consequences

- **Positive:** Logger names map directly to source paths; an operator
  reading a log line can locate the producing module without any
  mapping artifact.
- **Positive:** One uniform trace mechanism across the codebase;
  missing trace logging on a critical branch is a verification defect,
  not a style preference.
- **Positive:** The discriminator auto-adapts to Python version
  changes via introspection, with no hardcoded native attribute set.
- **Negative / trade-offs:** The three-condition discriminator is more
  complex than a sentinel key. Acceptable — it removes the reserved
  name and the wrapper function.
- **Accepted risks:** An `extra` key that collides with a native
  `LogRecord` attribute is silently overwritten by stdlib. Guarded by
  a static test that rejects colliding `extra={...}` literals.
