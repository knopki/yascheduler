## MODIFIED Requirements

### Requirement: TaskContext typed metadata

The system SHALL provide a `TaskContext` value object as an immutable object
with fields: `engine: str`, `remote_folder: str | None`, `local_folder: str | None`,
`webhook_url: str | None`, `webhook_custom_params: dict[str, object]`,
`error: str | None`, `extra: dict[str, object]`.

The system SHALL provide a
`TaskContext.replace(self, **overrides: Unpack[TaskContextOverrides]) -> Self`
method that returns a new `TaskContext` with the given overrides applied.
`TaskContextOverrides` SHALL be a `TypedDict` with `total=False` and SHALL
contain exactly the fields actually overridden at call sites in the codebase:
`remote_folder: str | None`, `local_folder: str | None`,
`error: str | None`, `extra: dict[str, object]`. The method SHALL perform no
merge into a stored context, no validation guard, and no side effect — it is
a pure typed copy-with delegating to `dataclasses.replace(self, **overrides)`.
The method SHALL be additive-only: raw `dataclasses.replace(ctx, ...)`
continues to work.

#### Scenario: TaskContext creation with known fields
- **WHEN** a TaskContext is instantiated with `engine="fleur"` and `webhook_url="https://example.com/hook"`
- **THEN** those fields are accessible as attributes; `extra` defaults to empty dict

#### Scenario: TaskContext preserves unknown fields in extra
- **WHEN** a TaskContext is created with `extra={"fort.9": "base64data", "custom_param": 42}`
- **THEN** those values are accessible via `ctx.extra["fort.9"]` and `ctx.extra["custom_param"]`

#### Scenario: replace returns a new immutable TaskContext with a single field overridden
- **WHEN** `ctx.replace(remote_folder="/r/new")` is called on a `TaskContext` with `remote_folder=None`
- **THEN** a new `TaskContext` is returned with `remote_folder="/r/new"` and all other fields (`engine`, `local_folder`, `webhook_url`, `webhook_custom_params`, `error`, `extra`) preserved unchanged from the original

#### Scenario: replace returns a new immutable TaskContext with multiple fields overridden
- **WHEN** `ctx.replace(local_folder="/l", remote_folder="/r", extra={"k": "v"})` is called on a `TaskContext`
- **THEN** the returned `TaskContext` has `local_folder="/l"`, `remote_folder="/r"`, `extra={"k": "v"}`, and all non-overridden fields preserved unchanged

#### Scenario: replace leaves the original unchanged
- **WHEN** `ctx.replace(error="boom")` is called and the original `ctx.error` is inspected afterward
- **THEN** the returned TaskContext has `error="boom"` and the original `ctx.error` is unchanged (frozen dataclass)

#### Scenario: replace accepts no overrides and returns an equal copy
- **WHEN** `ctx.replace()` is called with no arguments
- **THEN** a new `TaskContext` is returned equal to the original (`==` holds) but not identical (`is` does not hold)

#### Scenario: replace type-checks override field names
- **WHEN** a caller writes `ctx.replace(remot_folder="/r")` (typo)
- **THEN** the type checker rejects the call with an unknown-argument error (the `TaskContextOverrides` TypedDict does not contain `remot_folder`); the call does not silently create a spurious field

#### Scenario: replace overrides only the 4 declared fields
- **WHEN** the set of keys in `TaskContextOverrides.__annotations__` is inspected
- **THEN** it equals exactly `{"remote_folder", "local_folder", "error", "extra"}` — the fields actually overridden at call sites in the codebase; `engine`, `webhook_url`, `webhook_custom_params` are excluded

#### Scenario: replace is additive-only
- **WHEN** `dataclasses.replace(ctx, remote_folder="/r")` is called directly (raw stdlib call, not the method)
- **THEN** it continues to work and returns a new `TaskContext` with `remote_folder="/r"` — the method's existence does not prohibit the raw primitive