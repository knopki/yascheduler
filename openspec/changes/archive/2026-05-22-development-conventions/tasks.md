## 1. Tooling Migration

- [x] 1.1 Remove pyright from dev dependencies in pyproject.toml
- [x] 1.2 Remove `[tool.pyright]` section from pyproject.toml
- [x] 1.3 Add zuban to dev dependencies in pyproject.toml
- [x] 1.4 Verify zuban runs without configuration: `uv run zuban check`

## 2. Spec Installation

- [x] 2.1 Verify spec file at `openspec/specs/development-conventions/spec.md` is created by the archive step (or create if needed)

## 3. Validation

- [x] 3.1 Run `openspec validate --all --json` and confirm no errors
- [x] 3.2 Run `uv run ruff check .` and confirm no errors
- [x] 3.3 Run `uv run zuban check` and confirm no errors (or document expected issues)
- [x] 3.4 Verify GRACE-lite validation passes
