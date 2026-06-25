## 1. Migrate `common.py` from attrs to stdlib dataclasses

- [x] 1.1 Replace `from attrs import define` with `from dataclasses import dataclass` and `@define` with `@dataclass` on `ProcessInfo`
- [x] 1.2 Update FILE VERSION (bump minor) and append LAST_CHANGE entry to CHANGE_SUMMARY
- [x] 1.3 Update MODULE_MAP: change "Attrs struct" → "dataclass struct" in the exportedSymbol description

## 2. Migrate `adapters.py` from attrs to stdlib dataclasses

- [x] 2.1 Replace `from attrs import define, evolve, field` with `from dataclasses import dataclass, field, replace`
- [x] 2.2 Replace `@define(frozen=True)` with `@dataclass(frozen=True)` on `RemoteMachineAdapter`
- [x] 2.3 Drop bare `field()` calls (no args) — convert `platform: str = field()` etc. to bare annotations
- [x] 2.4 Change `checks: Sequence[SSHCheck] = field(factory=tuple)` to `field(default_factory=tuple)`
- [x] 2.5 Replace all 14 `evolve()` calls with `replace()` (linux_adapter-derived: debian_like, debian, debian_10 through debian_15, darwin; windows_adapter-derived: windows7 through windows12)
- [x] 2.6 Update FILE VERSION (bump minor) and append LAST_CHANGE entry to CHANGE_SUMMARY; verify MODULE_MAP still says "Frozen dataclass" (no change needed)

## 3. Verify correctness

- [x] 3.1 Run `uv run pytest -m unit` — all tests must pass (expect green, no test changes needed)
- [x] 3.2 Run `uv run zuban check` — no static analysis issues
- [x] 3.3 Run `uv run ruff check .` — no lint errors introduced
- [x] 3.4 Run `uv run ruff format --check .` — no formatting violations
- [x] 3.5 Run `uv run lint-imports` — no import issues
- [x] 3.6 Run `python3 scripts/grace_check.py` — must exit 0
- [x] 3.7 Run `openspec validate --all --json` — must pass

## 4. Final review

- [x] 4.1 Confirm `pyproject.toml` is NOT modified (attrs still in `[project.dependencies]`)
- [x] 4.2 Confirm no files outside `yascheduler/infra/ssh/platform/` were touched
- [x] 4.3 Confirm `infra/cloud/adapters.py` FIXME is still present (not addressed by this change)
