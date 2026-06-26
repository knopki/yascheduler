## MODIFIED Requirements

### Requirement: TaskContext JSONB serialization

The system SHALL provide `TaskContext.to_metadata() -> dict` and
`TaskContext.from_metadata(mapping) -> TaskContext` for JSONB round-trip
persistence.

Known fields (`engine`, `remote_folder`, `local_folder`, `webhook_url`,
`webhook_custom_params`, `error`) are serialized as top-level keys with
`None` values omitted. Unknown keys are preserved in `extra` and merged
into the flat dict on serialization. On deserialization, keys not matching
known fields populate `extra`.

`from_metadata` SHALL validate the types of the 4 `str | None` known fields
(`remote_folder`, `local_folder`, `webhook_url`, `error`) at the JSONB
boundary: a value that is neither `str` nor `None` SHALL raise `TypeError`
with a message identifying the field name and the offending type. The
`engine` field SHALL be coerced via `str(metadata.get("engine", ""))` (a
missing `engine` defaults to the empty string; a non-str value is coerced
through `str()`). The `webhook_custom_params` field SHALL be assigned only
when the metadata value is a `dict` (per the existing
`isinstance(wcp, dict)` guard); a non-dict value SHALL fall back to an
empty dict (preserving existing behavior — no `TypeError` for this field).

The 4 `str | None` field validations SHALL be routed through a single
module-private `_get_opt_str(metadata, key) -> str | None` helper (or
equivalent narrowing) that returns `None` for a missing key, returns the
`str` for a `str` value, and raises `TypeError` for any other type. This
removes the `# type: ignore[arg-type]` annotations on those 4 assignments;
the 5th previously-ignored assignment (`webhook_custom_params`) drops its
`# type: ignore` because the existing `isinstance(wcp, dict)` guard narrows
`object` to `dict`, which is assignable to `dict[str, object]`.

The `TypeError` is the defensive boundary behavior — a non-str value under a
str-typed key indicates upstream JSONB corruption (a botched migration, a
hand-edited row, a serialization bug). Failing fast at the deserialization
boundary, with the field name and offending type in the message, enables
quick diagnosis; silently coercing or passing through would shift the crash
to a downstream consumer's `.upper()` call where the corruption origin is
untraceable.

#### Scenario: Round-trip preserves all data
- **WHEN** `TaskContext(engine="fleur", webhook_url="https://...",
  extra={"fort.9": "data"})` is serialized then deserialized
- **THEN** all known fields and extra keys are preserved

#### Scenario: None values omitted from serialized dict
- **WHEN** `TaskContext(engine="fleur")` is serialized via `to_metadata()`
- **THEN** only `engine` appears as a key; `remote_folder`, `local_folder`,
  etc. are absent

#### Scenario: Extra keys merged into flat dict
- **WHEN** `to_metadata()` is called on a TaskContext with
  `extra={"fort.9": "base64data"}`
- **THEN** the returned dict contains `"fort.9": "base64data"` as a top-level
  key

#### Scenario: from_metadata raises TypeError on non-str remote_folder
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "remote_folder":
  123})` is called (an int value under a str-typed key)
- **THEN** `TypeError` is raised with a message mentioning the field name
  `remote_folder` and the offending type `int` (or `int`-derived name)

#### Scenario: from_metadata raises TypeError on non-str local_folder
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "local_folder":
  ["a", "b"]})` is called (a list value under a str-typed key)
- **THEN** `TypeError` is raised with a message mentioning the field name
  `local_folder`

#### Scenario: from_metadata raises TypeError on non-str webhook_url
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "webhook_url":
  {"k": "v"}}) is called (a dict value under a str-typed key)
- **THEN** `TypeError` is raised with a message mentioning the field name
  `webhook_url`

#### Scenario: from_metadata raises TypeError on non-str error
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "error": 4.5})
  is called (a float value under a str-typed key)
- **THEN** `TypeError` is raised with a message mentioning the field name
  `error`

#### Scenario: from_metadata accepts None for str-or-None fields
- **WHEN** `TaskContext.from_metadata({"engine": "fleur", "remote_folder":
  None, "error": None})` is called
- **THEN** a `TaskContext` is returned with `remote_folder=None`,
  `error=None`, and `engine="fleur"` (no `TypeError` — `None` is permitted
  for the `str | None` fields)

#### Scenario: from_metadata coerces engine to str
- **WHEN** `TaskContext.from_metadata({"engine": 42})` is called (an int
  `engine` value)
- **THEN** a `TaskContext` is returned with `engine="42"` (the `str()`
  coercion applies; no `TypeError` for the `engine` field)

#### Scenario: from_metadata accepts dict for webhook_custom_params
- **WHEN** `TaskContext.from_metadata({"engine": "fleur",
  "webhook_custom_params": {"k": "v"}})` is called
- **THEN** a `TaskContext` is returned with
  `webhook_custom_params={"k": "v"}` (the existing `isinstance(wcp, dict)`
  guard accepts a dict)

#### Scenario: from_metadata falls back to empty dict for non-dict webhook_custom_params
- **WHEN** `TaskContext.from_metadata({"engine": "fleur",
  "webhook_custom_params": "not-a-dict"})` is called (a str value under the
  dict-typed key)
- **THEN** a `TaskContext` is returned with
  `webhook_custom_params={}` (the existing `isinstance` guard falls back to
  the empty-dict default; no `TypeError` for this field)

#### Scenario: No type: ignore on the 5 from_metadata field assignments
- **WHEN** `yascheduler/domain/model.py::TaskContext.from_metadata` is
  inspected for `# type: ignore` annotations on the `remote_folder`,
  `local_folder`, `webhook_url`, `error`, and `webhook_custom_params`
  assignments
- **THEN** zero `# type: ignore` annotations are present on those 5
  assignments (the 4 `str | None` fields route through `_get_opt_str`;
  `webhook_custom_params` drops its over-cautious ignore because the
  existing `isinstance` guard already narrows to `dict`, which is
  assignable to `dict[str, object]`)