## Context

Phase 5.6. Config package is the last code using attrs. Purely mechanical
replacement — no behavior change.

## Goals

- Replace attrs with stdlib dataclasses in config/.
- Preserve identical config parsing behavior.

## Decisions

### D1: Mechanical replacement

| attrs construct                  | dataclasses replacement          |
| -------------------------------- | -------------------------------- |
| `@attr.s(auto_attribs=True, frozen=True)` | `@dataclass(frozen=True)` |
| `attr.ib(default=...)`             | `field(default=...)`               |
| `attr.field(factory=...)`          | `field(default_factory=...)`       |
| `make_default_field(type, default)` | `field(default_factory=...)`       |
| `evolve(obj, **kw)`                | `replace(obj, **kw)`               |
| `asdict(obj)`                      | `dataclasses.asdict(obj)` (if needed) |

### D2: ConfigUtils removed

`config/utils.py` (`make_default_field`, `warn_unknown_fields`, `ConfigWarning`)
is simplified — `make_default_field` removed, validators moved to
`__post_init__`.

## Risks

- **__post_init__ vs attrs validators**: Attrs validators run during
  `__init__`. Dataclass `__post_init__` runs after. For frozen dataclasses,
  `__post_init__` cannot reassign fields — use `object.__setattr__` if needed.
- **hash behavior**: Frozen dataclasses auto-generate `__hash__` based on
  field values, matching attrs `frozen=True` behavior. Verify hash consistency
  for any cached config objects.
