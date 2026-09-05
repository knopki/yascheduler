# ADR-0018: Restore the mapping protocol on EngineRepository

- **Status:** Accepted
- **Date:** 2026-09-02
- **Supersedes:**
- **Superseded by:**

## Context

The original `EngineRepository` inherited from `UserDict[str, Engine]`, which
provided the full Python mapping protocol (`keys`, `items`, `__len__`,
`__iter__`). Commit `0bfa1eac` (2026-06-26, "refactor(config): split") moved
engine types from `config/` to `domain/`, replaced the class with a frozen
dataclass, and documented:

> UserDict-inherited methods (`items`, `keys`, `__len__`, `__iter__`) are
> intentionally NOT carried over.

The removal was a design-purity decision: the new class would expose only the
seven methods the application layer actually used. The refactor did not account
for external clients that call `yac.config.engines.keys()` to discover available
engines. Those clients now get `AttributeError`.

Three options were considered:

- **Restore only `keys()`** — minimal, but leaves `items`, `len`, and
  iteration broken for any other external caller.
- **Restore all four methods + `Mapping` registration** — full
  read-only mapping protocol, prevents further compat reports.
- **Inherit from `UserDict` again** — restores everything but
  reintroduces mutators and the `data` dict coupling the refactor
  removed.

## Decision

Restore `keys()`, `items()`, `__iter__`, and `__len__()` on `EngineRepository`
as explicit methods delegating to the internal `data` mapping. Register
`EngineRepository` as a `collections.abc.Mapping` virtual subclass via
`Mapping.register(EngineRepository)`.

- `keys()` returns `list[str]` (not `KeysView`) — maximally compatible,
  supports indexing.
- `items()` returns `list[tuple[str, Engine]]` — consistent with
  `keys()`.
- `__iter__` yields `str` (engine names) — matches dict convention.
- `values()` is unchanged (still `ValuesView[Engine]`).
- The `data` field remains public.

## Alternatives Considered

### Restore only keys()

Rejected — other mapping methods (`items`, `len`, iteration) are likely used by
external clients too. Fixing only `keys` would invite a repeat report.

### Inherit from UserDict again

Rejected — reintroduces mutable mapping methods (`__setitem__`, `__delitem__`)
that the frozen dataclass deliberately rejects with `TypeError`. Also couples
the domain class to `collections.UserDict`, which the refactor moved away from.

## Consequences

- **Positive:** External clients that call `yac.config.engines.keys()`
  work again without modification.
- **Positive:** `isinstance(repo, Mapping)` returns `True`, enabling
  duck-typed code that checks for the Mapping protocol.
- **Negative / trade-offs:** `keys`/`items` return `list` while
  `values` returns `ValuesView` — a minor inconsistency accepted to
  avoid changing a working method.
- **Accepted risks:** A future contributor might re-remove these
  methods as "intentionally dropped." This ADR documents why they were
  restored.
