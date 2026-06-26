## Context

`Engine`, `EngineRepository`, and the `Deploy*` value objects are domain types
misplaced in `yascheduler/config/`. They carry INI-parsing classmethods
(`from_config_parser_section`, `from_config_parser`), are the only non-frozen
attrs class in the config package (`Engine`), and are structurally duplicated as
`PEngine` / `PEngineRepository` Protocols in
`infra/ssh/platform/protocol.py` because infra cannot import the real classes
from config without a layer crossing. The `domain-entities` spec already
declares an `Engine` value object requirement, confirming the intended home.

Predecessor P1 (`ssh-keys-extraction-vastai-parser-fix`) extracted
`get_private_keys()` into `infra/ssh/keys.py::list_private_keys` and
introduced the `list_private_keys_fn` callable parameter on
`Orchestrator.__init__`. P2 does not touch that callable.

This change is governed by `docs/config-layer-split-plan.md` §4 (P2) and §3
(locked decisions Q5–Q9). The explore-brief
(`openspec/changes/engine-to-domain-frozen/explore-brief.md`) is the frozen
checklist of relocation targets, field sets, consumer call sites, and test
migrations.

Constraints:
- R3 layers contract (`entrypoints → infra → application → domain → shared`).
  After P2, `infra → domain` imports of `Engine` / `EngineRepository` / `Deploy*`
  are R3-legal (infra may import domain). `application → domain` TYPE_CHECKING
  imports remain R3-legal.
- GRACE-lite: new `yascheduler/domain/engine.py` carries a MODULE_CONTRACT,
  MODULE_MAP, function contracts, and CHANGE_SUMMARY; `docs/knowledge-graph.xml`
  gets a new `M-DOMAIN-ENGINE` node; deleted `M-CONFIG-ENGINE` and
  `M-CONFIG-ENGINE-REPO` are removed with their `CrossLink` edges repointed.
- `Engine` field set is preserved (no field removals); only the form
  (mutable attrs → frozen dataclass) and the parser location change.
- `EngineRepository` query surface is preserved (`get`, `__getitem__`,
  `__contains__`, `values`, `filter`, `filter_platforms`,
  `get_platform_packages`); `UserDict`-inherited methods (`items`, `keys`,
  `__len__`, `__iter__`) are NOT carried over unless an audited consumer needs
  them.

## Goals / Non-Goals

**Goals:**
- The existing `domain.model.Engine` (7 fields, frozen, `validate_inputs`) is
  extended with 4 fields (`deployable`, `platform_packages`, `check_cmd_code`,
  `sleep_interval`) and relocated with `Deploy*` and `EngineRepository` to a
  new `yascheduler/domain/engine.py` (re-exported from `domain.model` and
  `yascheduler.domain` for backward compatibility).
- `EngineRepository` is `@dataclass(frozen=True)` with
  `data: Mapping[str, Engine]`; no `UserDict` inheritance; no `__hash__`; no
  `engines_dir`.
- INI parsing of `engine.*` sections lives in
  `entrypoints/config_parser.py` as free functions
  (`parse_engine_section`, `parse_engines`, `engine_valid_fields`), with the
  `_check_spawn`, `_check_check_`, `_check_at_least_one_elem` validators running
  parser-side.
- `PEngine` / `PEngineRepository` Protocols are deleted from
  `infra/ssh/platform/protocol.py`; consumers import from `yascheduler.domain`.
- `yascheduler/config/engine.py` and `yascheduler/config/engine_repository.py`
  are deleted; the `yascheduler.config` facade stops re-exporting the moved
  symbols; `yascheduler.domain` already re-exports `Engine` and adds
  `EngineRepository` + `Deploy*` to its `__all__`.
- The composition root (`entrypoints/di.py`) assembles `Config.engines` via
  `parse_engines(cfg, engines_dir)` from `entrypoints/config_parser.py`.
- All test mutation patterns (`engine.name = "g09"`) on the *config* `Engine`
  migrate to the full `Engine(...)` constructor or `dataclasses.replace`; all
  `MagicMock(spec=PEngineRepository)` sites migrate to
  `MagicMock(spec=EngineRepository)`.

**Non-Goals:**
- Moving `ConfigCloud*` to `infra/cloud/` (P3).
- Moving `Config` aggregate / `ConfigLocal` / `ConfigRemote` / `ConfigDb` out of
  `yascheduler/config/` (P4).
- Removing `attrs` from the project dependency list (P5 — `ConfigCloud*` and
  cloud adapter modules still use attrs).
- Changing `Engine` field set (no removals; the 4 additions from the merge
  have defaults and do not break existing constructors — only form and
  location change).
- Changing the `Engine.validate_inputs(ctx)` method (pure domain logic, stays
  on `Engine`, already covered by `domain-entities` spec).
- Introducing a `CloudConfig` domain Protocol (P3 — this change does not touch
  cloud configs).

## Decisions

### D1: Merge into existing `domain.model.Engine`, frozen stdlib dataclass

`yascheduler/domain/model.py:155` already defines a frozen `Engine` with 7
fields (`name`, `spawn`, `input_files`, `output_files`, `platforms`,
`check_cmd`, `check_pname`) and `validate_inputs(ctx)`. It is re-exported from
`yascheduler.domain` and consumed by `tests/unit/test_domain_model.py` and
`tests/unit/test_domain_services.py`.

`yascheduler/config/engine.py::Engine` is a *separate* attrs class with 11
fields (the 7 above plus `deployable`, `platform_packages`, `check_cmd_code`,
`sleep_interval`), no `validate_inputs`, and the INI-parsing classmethods. It
is consumed by 13 test files and 3 application use cases (TYPE_CHECKING).

**P2 merges the two**: extend `domain.model.Engine` with the 4 missing fields
(`deployable: tuple[Deploy, ...] = ()`, `platform_packages: tuple[str, ...] = ()`,
`check_cmd_code: int = 0`, `sleep_interval: int = 10`), move the extended
`Engine` + `Deploy*` + `EngineRepository` into a new
`yascheduler/domain/engine.py` (re-exported from `domain.model` and
`yascheduler.domain` for backward compatibility), delete `config/engine.py`
and `config/engine_repository.py`, and migrate all `config.Engine` consumers
to the merged `domain.Engine`.

The 4 added fields have defaults, so existing `Engine(name=..., spawn=..., input_files=..., platforms=...)`
calls in `test_domain_model.py` / `test_domain_services.py` / `conftest.py`
continue to work unchanged.

Rejected alternatives (see explore-brief §"Rejected alternatives"):

- **attrs frozen** — rejected: project policy is to migrate off attrs; config is
  the largest attrs consumer and P2 removes two attrs modules.
- **`MappingProxyType` for `EngineRepository.data`** — rejected: unpicklable,
  non-dataclass-idiomatic, redundant with the `Mapping` typing + frozen
  dataclass double guard (mypy blocks content mutation via the read-only
  `Mapping` protocol; frozen blocks field reassignment).
- **Keep `domain.model.Engine` and `config.Engine` separate** — rejected: two
  classes with overlapping fields and no shared contract is the current bug;
  merging is the point of P2.

### D2: Parser separation — free functions, not classmethods

`Engine.from_config_parser_section`, `EngineRepository.from_config_parser`,
and `Engine.get_valid_config_parser_fields` move to
`entrypoints/config_parser.py` as `parse_engine_section`, `parse_engines`,
`engine_valid_fields`. The validators (`_check_spawn`, `_check_check_`,
`_check_at_least_one_elem`) move alongside as parser-internal helpers
(prefixed `_` since they are not part of the public parser surface).

Rejected: keeping `from_config_parser_section` as a classmethod on the domain
value object. Domain value objects must not import `ConfigParser` /
`SectionProxy`; parsing is an adapter concern belonging at the composition
root boundary (entrypoints).

The parser module also inherits the engine-defaults responsibility
(`check_cmd_code=0`, `sleep_interval=10`) as plain dataclass defaults on the
merged `domain.Engine` — `make_default_field` is **not deleted** in P2 because
`config/remote.py`, `config/db.py`, and `config/cloud.py` still use it (they
move in P3/P4). `make_default_field` stays in `config/utils.py` until P3/P4
remove the last consumers. `warn_unknown_fields` likewise stays in
`config/utils.py` (P3 cloud parsing uses it).

### D3: `EngineRepository` surface — explicit methods, no dict inheritance

Target surface (from explore-brief):
```python
@dataclass(frozen=True)
class EngineRepository:
    data: Mapping[str, Engine] = field(default_factory=dict)

    def get(self, name: str) -> Engine | None: return self.data.get(name)
    def __getitem__(self, name: str) -> Engine: return self.data[name]
    def __contains__(self, name: object) -> bool: return name in self.data
    def values(self) -> ValuesView[Engine]: return self.data.values()
    def filter(self, fn: Callable[[Engine], bool]) -> EngineRepository:
        return EngineRepository(data={k: v for k, v in self.data.items() if fn(v)})
    def filter_platforms(self, platforms: Sequence[str]) -> EngineRepository:
        return self.filter(lambda e: bool(set(e.platforms) & set(platforms)))
    def get_platform_packages(self) -> list[str]: ...
```

`filter` returns a new frozen instance (same behavior as today's
`self.__class__(data=new_data, engines_dir=self.engines_dir)`, minus the
removed `engines_dir`).

Rejected: keep `UserDict` inheritance with neutralized mutators. The
`__setitem__` / `__delitem__` → `raise NotImplementedError` hack is a
"secretly mutable" anti-pattern; a frozen dataclass with explicit methods is
honest about its immutability.

**Interface audit risk**: `MagicMock(spec=EngineRepository)` in ~15 test sites
checks the class interface. `UserDict`-inherited methods (`items`, `keys`,
`__len__`, `__iter__`) disappear from the spec. Tasks include an explicit grep
for `.items(`, `.keys(`, `len(`, `for ... in <engine_repo_var>` on
`MagicMock(spec=EngineRepository)` variables; any hit requires adding the method
to the target surface or migrating the test. The production audit (explore-brief
call-site table) shows no production use of `items` / `keys` / `__len__`.

### D4: Delete `PEngine` / `PEngineRepository` Protocols

`infra/ssh/platform/protocol.py` defines `PEngine` and `PEngineRepository` as
structural Protocols that mirror a subset of `Engine` / `EngineRepository`.
After P2, `Engine` / `EngineRepository` live in `yascheduler.domain`, which
infra may import (R3-legal). The Protocols are pure duplication.

Consumers update:
- `infra/ssh/platform/linux.py`, `windows.py`: `Deploy*` import →
  `from yascheduler.domain import LocalArchiveDeploy, LocalFilesDeploy, RemoteArchiveDeploy`.
- `infra/ssh/platform/protocol.py`: `PEngine` / `PEngineRepository` deleted;
  the `from yascheduler.config import (LocalArchiveDeploy, LocalFilesDeploy, RemoteArchiveDeploy)`
  import becomes `from yascheduler.domain import ...`.
- `infra/ssh/gateway.py`: `engines.filter_platforms(...)` unchanged (method
  preserved); the `PEngineRepository` type hint, if any, becomes
  `EngineRepository`.
- `tests/unit/test_ssh_gateway.py:908, 969`:
  `MagicMock(spec=PEngineRepository)` → `MagicMock(spec=EngineRepository)`.

Rejected: keep Protocols as Interface Segregation. ISP savings (5 methods vs 7)
are negligible for a small collection, and the duplication cost exceeds the
segmentation benefit.

### D5: `EngineRepository.__hash__` removal

`__hash__` is defined via `attrs.asdict(value_serializer=_value_serializer)`
on `EngineRepository`. Grep for `hash(engines`, `engines in {`, `set(engines`,
`frozenset(engines`, `engines as dict key` returns zero production hits. The
hash exists for `UserDict`'s hashability default, not for a real consumer.

Removing it:
- Eliminates the only `attrs.asdict(value_serializer=)` usage, clearing the
  path to stdlib dataclass.
- Makes `EngineRepository` unhashable — correct for a "frozen" collection
  whose underlying `data` is a `Mapping` (mappings are unhashable by default in
  stdlib dataclasses with `eq=True`).

No test asserts `hash(EngineRepository(...))`; verified by grep. If a latent
caller exists, it surfaces as a `TypeError` at runtime and is fixed by hashing
`tuple(repo.data.items())` explicitly at the call site.

### D6: `engines_dir` removal from runtime `EngineRepository`

`engines_dir: PurePath` is on `EngineRepository` today. Usage:
- `Engine.from_config_parser_section` uses it to resolve
  `LocalFilesDeploy.files = engine_dir / x` and `LocalArchiveDeploy.file = engine_dir / archive`.
  After parsing, deploy paths are absolute — `engines_dir` is not needed at runtime.
- `EngineRepository.filter` forwards `engines_dir` to the new instance
  (`self.__class__(data=new_data, engines_dir=self.engines_dir)`).
- `EngineRepository.from_config_parser` passes `engines_dir` through.
- No runtime method (`get`, `values`, `filter_platforms`,
  `get_platform_packages`) reads `engines_dir`.

After P2, `engines_dir` lives only in parser scope (`parse_engines(cfg, engines_dir)`
parameter). The runtime `EngineRepository` drops the field. `filter` returns
`EngineRepository(data={...})` without forwarding `engines_dir`.

Rejected: keep `engines_dir` as an opaque "context" field. It is a parser
concern; storing it on the runtime collection couples domain to the INI
source. `LocalFilesDeploy.files` and `LocalArchiveDeploy.file` already hold
absolute paths post-parse.

### D7: Composition root engine assembly

`entrypoints/di.py` currently constructs `Config` via
`Config.from_config_parser(args.config)`, which internally calls
`EngineRepository.from_config_parser(cfg, engines_dir)`. After P2:

- `Config.from_config_parser` keeps its structure for the non-engine sections
  (db, local, remote, clouds) until P4. The engine assembly is extracted:
  `Config.from_config_parser` calls `parse_engines(cfg, engines_dir)` from
  `entrypoints/config_parser.py` and assigns the result to `Config.engines`.
- The `engines_dir` value comes from `ConfigLocal` (which still lives in
  `config/local.py` until P4); `Config.from_config_parser` reads
  `local_section["engines_dir"]` and passes it to `parse_engines`.

This keeps `Config` constructible in one call and avoids requiring
`entrypoints/di.py` to assemble engines separately. The parser module becomes
the single seam between INI and domain types for the engine path.

## Risks / Trade-offs

- **`MagicMock(spec=EngineRepository)` interface drift** → Mitigation: explicit
  grep in tasks for `UserDict`-inherited method usage on `EngineRepository`
  mocks; add methods to the target surface only where a real consumer (prod or
  test) needs them. The production audit shows none; the test audit is the
  discovery surface.
- **Test mutation-pattern migration (~10 files)** → Mitigation: each test file
  migrates independently to the full `Engine(...)` constructor or
  `dataclasses.replace`; no shared fixture change required. The migration is
  mechanical and local.
- **Parser locality loss** → Trade-off: `from_config_parser_section` no longer
  lives next to the fields. Mitigation: `engine_valid_fields()` documents the
  INI key list (including deploy aliases) in the parser module;
  `warn_unknown_fields` is called from the parser. The INI contract is
  documented in one place (the parser), not split across value objects.
- **`Config.from_config_parser` partial extraction** → Trade-off: engine
  assembly is extracted to the parser module, but db/local/remote/clouds
  assembly stays in `Config.from_config_parser` until P3/P4. This leaves
  `Config.from_config_parser` as a hybrid for one proposal cycle. Mitigation:
  the hybrid is explicitly documented with a TODO referencing P3/P4; the
  engine path is the only extracted one, keeping the surface minimal.
- **`attrs` still in `config/utils.py` and other config modules** → Trade-off:
  `make_default_field` stays in `config/utils.py` because `config/remote.py`,
  `config/db.py`, and `config/cloud.py` still consume it (they move in P3/P4).
  P2 removes attrs from `config/engine.py` and `config/engine_repository.py`
  only. Mitigation: `utils.py` migration is deferred to P3/P4 when its last
  consumers move; P2 does not touch `config/utils.py`.
- **`Engine` frozen breaks mutation-based test setup** → Mitigation: the test
  migration is a hard requirement of P2 (listed in tasks); no test is left
  mutating `Engine` fields. The frozen form is enforced by the dataclass, so any
  missed mutation site fails loudly at collection time rather than silently.

## Migration Plan

Single-repo, single-PR change. No runtime migration, no DB migration, no
config-file format change. The INI format and `Config` public surface are
unchanged from the operator's perspective.

Steps (mirrors tasks.md ordering):
1. Extend `yascheduler/domain/model.py::Engine` with the 4 missing fields
   (`deployable`, `platform_packages`, `check_cmd_code`, `sleep_interval`),
   then relocate `Engine` + `Deploy*` + `EngineRepository` to a new
   `yascheduler/domain/engine.py`; keep `domain/model.py` re-exporting them for
   backward compatibility with the 7+ tests importing `from yascheduler.domain.model import Engine`.
2. Create `entrypoints/config_parser.py` with `parse_engine_section`,
   `parse_engines`, `engine_valid_fields`, and the validator helpers
   (`_check_spawn`, `_check_check_`, `_check_at_least_one_elem`).
3. Delete `config/engine.py` and `config/engine_repository.py`; update
   `config/__init__.py` re-exports; update `config/config.py` engine assembly
   to call `parse_engines`.
4. Delete `PEngine` / `PEngineRepository` from `infra/ssh/platform/protocol.py`;
   update `linux.py`, `windows.py`, `gateway.py` imports.
5. Update application TYPE_CHECKING imports and `infra/cloud/manager.py`
  TYPE_CHECKING import to `yascheduler.domain`.
6. Update `entrypoints/di.py` and `entrypoints/cli/submit.py` imports.
7. Update `docs/knowledge-graph.xml` (`M-DOMAIN-ENGINE` added;
   `M-CONFIG-ENGINE` / `M-CONFIG-ENGINE-REPO` removed; CrossLinks repointed).
8. Migrate test files: `config.Engine` mutation patterns → merged `domain.Engine`
   constructor / `replace`; `spec=PEngineRepository` → `spec=EngineRepository`;
   config parser tests → `parse_engines`.
9. Run `uv run pytest -m unit`, `uv run lint-imports`,
   `python3 scripts/grace_check.py`, `openspec validate --all --json`.

Rollback: revert the single PR. No data format or persisted-state change
exists, so rollback is clean.

## Open Questions

None. All architectural questions (Q5–Q9) are locked in
`docs/config-layer-split-plan.md` §3. The interface audit
(`MagicMock(spec=EngineRepository)` `UserDict`-method reliance) is an
implementation-time discovery task in tasks.md, not an open question.