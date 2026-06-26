# Explore Brief — engine-to-domain-frozen (P2)

> Umbrella: `docs/config-layer-split-plan.md` §4 P2.
> Predecessor: `ssh-keys-extraction-vastai-parser-fix` (P1, archived).

## Rejected alternatives

1. **Keep `Engine` mutable in domain.** Rejected — a mutable domain value object
   contradicts the domain-entities spec ("immutable with encapsulated business
   rules") and the rest of `domain/` is frozen. The mutation-based test pattern
   (`engine.name = "g09"`) must migrate to constructor / `dataclasses.replace`.
2. **Keep `PEngine`/`PEngineRepository` Protocols as ISP.** Rejected — the
   interface is 5 methods; ISP savings are negligible and the structural
   duplication (Protocol = subset of class) is a maintenance cost. Direct
   import from domain after the move makes the Protocols redundant.
3. **Keep `EngineRepository` as `UserDict`.** Rejected — `UserDict` with
   `__setitem__`/`__delitem__` raising `NotImplementedError` is a "secretly
   mutable" hack. A frozen dataclass with `data: Mapping[str, Engine]` is
   cleaner and idiomatic for domain.
4. **Keep `EngineRepository.__hash__`.** Rejected — zero production callers;
   the `attrs.asdict(value_serializer=)` dependency is the only blocker for a
   clean stdlib dataclass migration. Removing it simplifies P2.
5. **Keep `engines_dir` on `EngineRepository`.** Rejected — only the parser
   and `filter()` (which forwards it) use it; runtime methods do not. It is a
   parser concern, not a domain collection field.
6. **Keep `from_config_parser_section` as a classmethod on the domain value
   object.** Rejected — domain value objects must not import `ConfigParser` /
   `SectionProxy`. Parsing is an adapter concern; it moves to
   `entrypoints/config_parser.py`.
7. **Use `MappingProxyType` for `EngineRepository.data`.** Rejected —
   unpicklable, non-dataclass-idiomatic; `Mapping` typing + frozen dataclass is
   sufficient (mypy blocks content mutation, frozen blocks reassignment).
8. **Merge P2 into P4.** Rejected — combining Engine move + aggregate
   relocation + settings move into one proposal exceeds the "no oversized
   proposals" constraint. P2 is self-contained and testable alone.
9. **Keep `config.Engine` and `domain.model.Engine` as two separate classes.**
   Rejected — discovered during design review: `domain.model.Engine` (7 fields,
   frozen, `validate_inputs`) and `config.Engine` (11 fields, attrs, no
   `validate_inputs`, parser methods) already overlap on 7 fields. Two classes
   with overlapping fields and no shared contract is the bug P2 fixes. The
   merged `domain.Engine` carries all 11 fields; the 4 added fields have
   defaults so existing `Engine(name=..., spawn=..., input_files=..., platforms=...)`
   calls in `test_domain_model.py` / `test_domain_services.py` / `conftest.py`
   continue to work unchanged.

## Final approach: complete label / mapping tables

### Module relocation table

| Symbol                          | Current module                    | Target module                  | Form change                                                        |
|---------------------------------|-----------------------------------|--------------------------------|--------------------------------------------------------------------|
| `Engine`                        | `yascheduler/config/engine.py`    | `yascheduler/domain/engine.py` | attrs mutable → `@dataclass(frozen=True)`; drop `from_config_parser_section`, `get_valid_config_parser_fields` |
| `LocalFilesDeploy`              | `yascheduler/config/engine.py`    | `yascheduler/domain/engine.py` | attrs frozen → `@dataclass(frozen=True)`                           |
| `LocalArchiveDeploy`            | `yascheduler/config/engine.py`    | `yascheduler/domain/engine.py` | attrs frozen → `@dataclass(frozen=True)`                           |
| `RemoteArchiveDeploy`           | `yascheduler/config/engine.py`    | `yascheduler/domain/engine.py` | attrs frozen → `@dataclass(frozen=True)`                           |
| `Deploy` (Union alias)          | `yascheduler/config/engine.py`    | `yascheduler/domain/engine.py` | Union alias over the 3 frozen deploy classes                        |
| `EngineRepository`             | `yascheduler/config/engine_repository.py` | `yascheduler/domain/engine.py` | attrs `UserDict` → `@dataclass(frozen=True)` with `data: Mapping[str, Engine]`; drop `__hash__`, `engines_dir`, `UserDict` inheritance, `from_config_parser` |
| `Engine.from_config_parser_section` | method on Engine              | `entrypoints/config_parser.py::parse_engine_section` | Free function; takes `(sec, engines_dir)` → `Engine`     |
| `EngineRepository.from_config_parser` | classmethod on EngineRepository | `entrypoints/config_parser.py::parse_engines` | Free function; takes `(cfg, engines_dir)` → `EngineRepository` |
| `Engine.get_valid_config_parser_fields` | classmethod on Engine       | `entrypoints/config_parser.py::engine_valid_fields` | Module-level constant or function                                |
| `PEngine` Protocol              | `infra/ssh/platform/protocol.py`   | **deleted**                    | Consumers import `Engine` from `yascheduler.domain` directly       |
| `PEngineRepository` Protocol     | `infra/ssh/platform/protocol.py`   | **deleted**                    | Consumers import `EngineRepository` from `yascheduler.domain` directly |

### Engine field set (target — no removals, validation moves to parser)

| Field               | Type                          | Default     | Notes                                                            |
|---------------------|-------------------------------|-------------|------------------------------------------------------------------|
| `name`              | `str`                         | required    |                                                                  |
| `spawn`             | `str`                         | required    | Parser validates template placeholders                           |
| `check_cmd`         | `str \| None`                 | `None`      | Parser enforces at-least-one of `check_cmd`/`check_pname`        |
| `check_pname`       | `str \| None`                 | `None`      | Parser enforces at-least-one                                     |
| `deployable`        | `tuple[Deploy, ...]`          | `()`        |                                                                  |
| `input_files`       | `tuple[str, ...]`             | `()`        | Parser enforces non-empty                                        |
| `output_files`      | `tuple[str, ...]`             | `()`        | Parser enforces non-empty                                        |
| `platforms`         | `tuple[str, ...]`             | `()`        |                                                                  |
| `platform_packages` | `tuple[str, ...]`             | `()`        |                                                                  |
| `check_cmd_code`    | `int`                         | `0`         |                                                                  |
| `sleep_interval`    | `int`                         | `10`        |                                                                  |

`validate_inputs(ctx)` stays on `Engine` — it is pure domain logic (checks
`ctx.extra` for `input_files`), not INI parsing. Already in `domain-entities`
spec (`Engine.validate_inputs` scenario).

### EngineRepository target surface

```python
@dataclass(frozen=True)
class EngineRepository:
    data: Mapping[str, Engine] = field(default_factory=dict)

    def get(self, name: str) -> Engine | None: ...
    def __getitem__(self, name: str) -> Engine: ...
    def __contains__(self, name: object) -> bool: ...
    def values(self) -> ValuesView[Engine]: ...
    def filter(self, fn: Callable[[Engine], bool]) -> EngineRepository: ...
    def filter_platforms(self, platforms: Sequence[str]) -> EngineRepository: ...
    def get_platform_packages(self) -> list[str]: ...
```

No `engines_dir`. No `__hash__`. No `UserDict` inheritance. `filter` returns a
new frozen instance: `EngineRepository(data={k: v for k, v in self.data.items() if fn(v)})`.

### Consumer call sites (production, runtime)

| File                                  | Current import / usage                       | After P2                                                              |
|---------------------------------------|---------------------------------------------|-----------------------------------------------------------------------|
| `application/allocate_task.py:48`      | `from yascheduler.config import Engine, EngineRepository` (TYPE_CHECKING) | `from yascheduler.domain import Engine, EngineRepository` (TYPE_CHECKING) |
| `application/consume_task.py:34`      | `from yascheduler.config import EngineRepository` (TYPE_CHECKING) | `from yascheduler.domain import EngineRepository` (TYPE_CHECKING)    |
| `application/submit_task.py:38`        | `from yascheduler.config import EngineRepository` (TYPE_CHECKING) | `from yascheduler.domain import EngineRepository` (TYPE_CHECKING)    |
| `application/orchestrator.py:54`      | `from yascheduler.config import Config, ConfigCloud, EngineRepository` (TYPE_CHECKING) | `Config`/`ConfigCloud` stay (P3/P4); `EngineRepository` → `yascheduler.domain` |
| `infra/cloud/manager.py:52,68,88`     | `EngineRepository` (TYPE_CHECKING)           | `from yascheduler.domain import EngineRepository` (TYPE_CHECKING)   |
| `infra/ssh/platform/protocol.py:70,111-134` | imports `Deploy*`; defines `PEngine`/`PEngineRepository` | `Deploy*` → `yascheduler.domain`; `PEngine`/`PEngineRepository` deleted |
| `infra/ssh/platform/linux.py:40`       | `from yascheduler.config import LocalArchiveDeploy, LocalFilesDeploy, RemoteArchiveDeploy` (runtime) | `from yascheduler.domain import ...` (infra→domain, R3-legal)         |
| `infra/ssh/platform/windows.py:42`    | same as linux.py                             | same as linux.py                                                      |
| `infra/ssh/gateway.py:828`             | `engines.filter_platforms(state.platforms)`  | unchanged (method preserved on new EngineRepository)                  |
| `entrypoints/di.py:59`                 | `from yascheduler.config import Config, ConfigCloud, EngineRepository` (TYPE_CHECKING) | `EngineRepository` → `yascheduler.domain`; `Config`/`ConfigCloud` stay |
| `entrypoints/cli/submit.py:36`         | `from yascheduler.config import Config, Engine` (runtime) | `Engine` → `yascheduler.domain`; `Config` stays (P4 moves it)        |

### Config facade delta (`yascheduler/config/__init__.py`)

After P2 the facade no longer re-exports `Engine`, `EngineRepository`,
`Deploy`, `LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`.
The physical files `config/engine.py` and `config/engine_repository.py` are
**deleted**. The facade keeps re-exporting `Config`, `ConfigDb`, `ConfigLocal`,
`ConfigRemote`, `ConfigCloud*` (those move in P3/P4).

`config/engine.py` validators (`_check_spawn`, `_check_check_`,
`_check_at_least_one_elem`) move into `entrypoints/config_parser.py` as
parser-side validation. `config/utils.py::make_default_field`,
`get_valid_config_parser_fields` helper logic moves to the parser module too.
`warn_unknown_fields` stays in `config/utils.py` (used by cloud config parsing
in P3, not touched here).

### Cross-module data flows

**Submit path (runtime):**
`entrypoints/cli/submit.py` → `config.engines[engine_name]` → `EngineRepository.__getitem__`
→ `Engine.input_files` → `submit_task` validates inputs → `Task` created.

After P2: `config.engines` is still a `Config` attribute (the aggregate stays
in config until P4), but `config.engines` is now of type `EngineRepository`
imported from `yascheduler.domain`. The composition root `entrypoints/di.py`
constructs `EngineRepository` via `parse_engines(cfg, engines_dir)` from
`entrypoints/config_parser.py` and assigns it to `Config.engines`.

**SSH setup path (runtime):**
`infra/ssh/gateway.py::setup_node` → `engines.filter_platforms(state.platforms)`
→ new `EngineRepository` → `for engine in engines.values()` →
`Engine.deployable` → deploy strategies.

After P2: `EngineRepository.filter_platforms` returns a new frozen instance
(same behavior). `Deploy*` types come from `yascheduler.domain`. No
`PEngineRepository` indirection.

**Cloud config build path (runtime):**
`infra/cloud/manager.py::_get_cloud_config_data` → `self.engines.filter(...)`
→ `supported_engines.get_platform_packages()` → `CloudConfig(packages=pkgs)`.

After P2: `self.engines` is `EngineRepository` from domain; `filter` and
`get_platform_packages` methods preserved.

### Test migration map

| Test file                              | Current pattern                              | After P2                                                              |
|---------------------------------------|---------------------------------------------|-----------------------------------------------------------------------|
| `tests/unit/conftest.py:48`           | `Engine(...)` constructor                    | Update to frozen dataclass; full kwargs constructor                    |
| `tests/unit/test_domain_model.py`     | `Engine(name=..., spawn=..., input_files=...)` | Already uses constructor; add `replace` where mutation was used       |
| `tests/unit/test_domain_services.py`  | `Engine(name="fleur", spawn="fleur_MPI", platforms=("linux",))` | Already constructor-based; verify `filter_platforms` returns new instance |
| `tests/unit/test_cli_behavioral.py:47-51` | `engine.name = "g09"; engine.spawn = "run.sh"; engine.input_files = ("input",); engine.output_files = ("OUTPUT",); engine.platforms = ("linux",)` | `engine = Engine(name="g09", spawn="run.sh", input_files=("input",), output_files=("OUTPUT",), platforms=("linux",))` |
| `tests/unit/test_cli_submit.py:52-56` | same mutation pattern                        | same constructor migration                                            |
| `tests/unit/test_cli_show_nodes.py:52-56` | same mutation pattern                  | same constructor migration                                            |
| `tests/unit/test_cli_check_status.py:76-77` | `engine.name = "g09"; engine.spawn = "run.sh"` | `engine = Engine(name="g09", spawn="run.sh", ...)`                  |
| `tests/unit/test_cli_manage_node.py:50` | `engine.name = "g09"`                      | `engine = Engine(name="g09", ...)` (check full constructor needed)    |
| `tests/unit/test_ssh_gateway.py:234`  | `engine.name = "test_engine"`                | `engine = Engine(name="test_engine", ...)`                            |
| `tests/integration/test_ssh_gateway.py:302` | `engine.name = "test_engine"`          | `engine = Engine(name="test_engine", ...)`                            |
| `tests/unit/test_config.py` lines around `Engine(...)` | `Engine.from_config_parser_section` direct calls | Migrate to `parse_engine_section` from `entrypoints/config_parser.py`; keep Engine-constructor tests but assert frozen + no parser method |
| ~15 `MagicMock(spec=EngineRepository)` sites | `spec=EngineRepository` checks interface    | Verify spec still passes; methods `get`/`values`/`filter`/`filter_platforms`/`get_platform_packages` preserved. `UserDict`-inherited methods (`items`, `keys`, `__len__`) are NOT on the new class — any test using those needs an explicit method. Audit needed in tasks. |
| `tests/unit/test_ssh_gateway.py:908,969` | `MagicMock(spec=PEngineRepository)`          | Replace with `MagicMock(spec=EngineRepository)` from domain           |

## Open questions

None remaining — all five architectural questions (Q5–Q9) are locked in
`docs/config-layer-split-plan.md` §3, and the call-site audit is complete
above. The only implementation-time discovery risk is the
`MagicMock(spec=EngineRepository)` interface audit (does any test rely on
`UserDict`-inherited methods like `items`/`keys`/`__len__`?); tasks include an
explicit grep for that.