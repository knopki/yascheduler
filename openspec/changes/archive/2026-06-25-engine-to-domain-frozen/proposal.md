## Why

`Engine`, `EngineRepository`, and the `Deploy*` value objects live in
`yascheduler/config/` despite being domain value objects: the
`domain-entities` spec already defines an `Engine` value object requirement,
`yascheduler/domain/model.py` already defines a frozen `Engine` (7 fields +
`validate_inputs`) consumed by `test_domain_model.py` / `test_domain_services.py`,
and `config/engine.py::Engine` is a *separate* attrs class (11 fields, no
`validate_inputs`, INI-parsing classmethods) — a duplicate. Separately,
`infra/ssh/platform/protocol.py` carries structural `PEngine` /
`PEngineRepository` Protocol duplicates that exist only because infra cannot
import the real classes from config without a layer crossing, and
`EngineRepository` is a `UserDict` with neutralized mutators plus an unused
`__hash__` built on `attrs.asdict(value_serializer=)`. This is the second step
(P2) of the config-layer split plan
(`docs/config-layer-split-plan.md`): merge the two `Engine` classes by extending
`domain.model.Engine` with the 4 missing fields, relocate the merged `Engine`
+ `Deploy*` + `EngineRepository` to `yascheduler/domain/engine.py`, make them
frozen stdlib dataclasses, separate INI parsing into
`entrypoints/config_parser.py`, and delete the `PEngine` / `PEngineRepository`
Protocol duplicates. Predecessor P1 (`ssh-keys-extraction-vastai-parser-fix`)
is archived.

## What Changes

- Extend the existing `domain.model.Engine` (frozen, 7 fields,
  `validate_inputs`) with 4 fields (`deployable: tuple[Deploy, ...] = ()`,
  `platform_packages: tuple[str, ...] = ()`, `check_cmd_code: int = 0`,
  `sleep_interval: int = 10`) and relocate `Engine`, `LocalFilesDeploy`,
  `LocalArchiveDeploy`, `RemoteArchiveDeploy`, `Deploy` (Union alias), and a
  new `EngineRepository` into a new `yascheduler/domain/engine.py`, re-exported
  from `domain.model` and `yascheduler.domain` for backward compatibility with
  existing `from yascheduler.domain.model import Engine` imports. **BREAKING**
  for direct `from yascheduler.config.engine import Engine` imports (test
  files); they migrate to `from yascheduler.domain import Engine`.
- Replace `config.EngineRepository` (a `UserDict` with neutralized mutators and
  an unused `__hash__` built on `attrs.asdict(value_serializer=)`) with a new
  `domain.EngineRepository` as `@dataclass(frozen=True)` carrying
  `data: Mapping[str, Engine]`. Drop `__hash__` (no production callers), drop
  `engines_dir` (parser concern, not a runtime field), drop `UserDict`
  inheritance. **BREAKING** for code that relies on `UserDict`-inherited methods
  (`items`, `keys`, `__len__`); the target surface is `get`, `__getitem__`,
  `__contains__`, `values`, `filter`, `filter_platforms`, `get_platform_packages`.
- Move `Engine.from_config_parser_section`, `EngineRepository.from_config_parser`,
  and `Engine.get_valid_config_parser_fields` out of the value objects into a
  new `entrypoints/config_parser.py` as free functions
  (`parse_engine_section`, `parse_engines`, `engine_valid_fields`). Domain
  value objects no longer import `ConfigParser` / `SectionProxy`. Validation
  (`_check_spawn`, `_check_check_`, `_check_at_least_one_elem`) runs in the
  parser, not in `__post_init__` — value objects stay pure. **BREAKING** for
  direct `Engine.from_config_parser_section(...)` / `EngineRepository.from_config_parser(...)`
  calls; they migrate to `parse_engine_section(...)` / `parse_engines(...)`.
  (`make_default_field` stays in `config/utils.py` — `config/remote.py`,
  `config/db.py`, `config/cloud.py` still consume it until P3/P4.)
- Delete `PEngine` and `PEngineRepository` Protocols from
  `infra/ssh/platform/protocol.py`. Consumers
  (`infra/ssh/platform/linux.py`, `infra/ssh/platform/windows.py`,
  `infra/ssh/gateway.py`) import `Engine` / `EngineRepository` /
  `Deploy*` from `yascheduler.domain` directly.
- Delete `yascheduler/config/engine.py` and
  `yascheduler/config/engine_repository.py`. The `yascheduler.config` facade
  (`__init__.py`) stops re-exporting `Engine`, `EngineRepository`, `Deploy`,
  `LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`.
  `yascheduler.domain` already re-exports `Engine` and adds `EngineRepository`
  + `Deploy*` to its `__all__`.
- Migrate the composition root `entrypoints/di.py` to build `EngineRepository`
  via `parse_engines(cfg, engines_dir)` from `entrypoints/config_parser.py`
  and assign it to `Config.engines`. `Config` itself stays in
  `yascheduler/config/config.py` until P4.
- Migrate ~10 test files from `engine.name = "g09"; engine.spawn = "run.sh"; ...`
  mutation (on the *config* `Engine`) to the merged `domain.Engine(...)`
  full constructor or `dataclasses.replace`. Audit all ~15
  `MagicMock(spec=EngineRepository)` sites for reliance on `UserDict`-inherited
  methods (`items`, `keys`, `__len__`); add explicit methods to the new
  `EngineRepository` only where a production or test consumer needs them.

## Capabilities

### New Capabilities
- `domain-engine-types`: The `Engine` value object, `EngineRepository`
  collection, and `Deploy*` deploy-strategy value objects as frozen stdlib
  dataclasses in `yascheduler/domain/engine.py`, with no INI parsing on the
  value objects and no `UserDict` inheritance. Covers the target field set,
  the `EngineRepository` query surface (`get`, `__getitem__`, `__contains__`,
  `values`, `filter`, `filter_platforms`, `get_platform_packages`), and
  importability from `yascheduler.domain`.

### Modified Capabilities
- `domain-entities`: The existing `Engine value object` requirement is
  extended to the full field set (`deployable`, `platforms`,
  `platform_packages`, `check_cmd_code`, `sleep_interval`), frozen
  dataclass form, and `EngineRepository` as a frozen collection with
  `filter` / `filter_platforms` / `get_platform_packages`.
- `platform-adapters`: The `PEngine` / `PEngineRepository` Protocol
  duplicates are removed; platform modules import `Engine` /
  `EngineRepository` / `Deploy*` from `yascheduler.domain`.
- `package-facades`: The `yascheduler.config` facade stops re-exporting
  `Engine`, `EngineRepository`, `Deploy`, `LocalFilesDeploy`,
  `LocalArchiveDeploy`, `RemoteArchiveDeploy`; `yascheduler.domain` facade
  re-exports them. The `layers` contract exemption for `yascheduler.config`
  shrinks (cloud configs and the aggregate remain until P3/P4).
- `testing-unit`: The config-parsing requirement loses
  `Engine.from_config_parser_section` / `EngineRepository.from_config_parser`
  direct calls; engine construction and `EngineRepository.filter` /
  `filter_platforms` / immutability assertions move to a domain-engine-types
  test scope, while INI round-trip parsing of `engine.*` sections is asserted
  against `parse_engines` from `entrypoints/config_parser.py`.

## Impact

- **Code**: New `yascheduler/domain/engine.py`; new
  `entrypoints/config_parser.py`; deleted `yascheduler/config/engine.py`
  and `yascheduler/config/engine_repository.py`; modified
  `yascheduler/config/__init__.py`, `yascheduler/config/utils.py`,
  `yascheduler/config/config.py` (engine assembly via parser),
  `infra/ssh/platform/protocol.py` (Protocol deletion + import switch),
  `infra/ssh/platform/linux.py`, `infra/ssh/platform/windows.py`,
  `infra/ssh/gateway.py` (import switch), `application/{allocate_task,consume_task,submit_task,orchestrator}.py`
  (TYPE_CHECKING imports → `yascheduler.domain`), `infra/cloud/manager.py`
  (TYPE_CHECKING import → `yascheduler.domain`), `entrypoints/di.py`
  (engine assembly), `entrypoints/cli/submit.py` (runtime `Engine` import →
  `yascheduler.domain`).
- **APIs**: Direct `from yascheduler.config.engine import Engine` /
  `from yascheduler.config.engine_repository import EngineRepository` /
  `from yascheduler.config import Engine, EngineRepository, Deploy, ...`
  break; the canonical path becomes `from yascheduler.domain import ...`.
  `Engine.from_config_parser_section` / `EngineRepository.from_config_parser`
  break; the canonical path becomes
  `from yascheduler.entrypoints.config_parser import parse_engines`.
  `EngineRepository.engines_dir` and `EngineRepository.__hash__` are removed.
  No public API surface (`Yascheduler`, `CONFIG_FILE`, `LOG_FILE`,
  `PID_FILE`, `from yascheduler import Yascheduler`,
  `from yascheduler.client import Yascheduler`) is affected.
- **Dependencies**: `attrs` usage in `config/engine.py` and
  `config/engine_repository.py` removed; `attrs` remains a project dependency
  until P5 (other config and cloud modules still use it).
- **Specs**: New `domain-engine-types` capability spec. Delta specs for
  `domain-entities`, `platform-adapters`, `package-facades`, `testing-unit`.
- **Tests**: ~10 test files migrate `engine.name = "g09"` mutation to
  constructor / `replace`; ~15 `MagicMock(spec=EngineRepository)` sites audited
  for `UserDict`-method reliance; 2 `MagicMock(spec=PEngineRepository)` sites
  in `test_ssh_gateway.py` switch to `MagicMock(spec=EngineRepository)`;
  `tests/unit/test_config.py` engine-parsing tests migrate to
  `parse_engines` and assert frozen + no parser method.
- **Knowledge graph**: `M-DOMAIN-ENGINE` added; `M-CONFIG-ENGINE` and
  `M-CONFIG-ENGINE-REPO` removed; `CrossLink` from `M-PLATFORM-LINUX`,
  `M-PLATFORM-WINDOWS`, `M-SSH-GATEWAY`, `M-CLOUD-PROVISIONER`,
  `M-APPLICATION-*`, `M-ENTRYPOINTS-DI` updated to point at `M-DOMAIN-ENGINE`.