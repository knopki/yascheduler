## ADDED Requirements

### Requirement: shared.compat re-exports StrEnum

The system SHALL re-export `StrEnum` from `yascheduler.shared.compat` using a
version branch: `from enum import StrEnum` on Python 3.11+ and
`from typing_extensions import StrEnum` below 3.11. `StrEnum` SHALL be included
in `__all__`.

`typing-extensions` is already a conditional dependency
(`python_version < '3.11'` in `pyproject.toml`); no new runtime dependency is
introduced.

#### Scenario: StrEnum is importable from shared.compat
- **WHEN** `from yascheduler.shared.compat import StrEnum` is executed on any supported Python version (>=3.9)
- **THEN** `StrEnum` is a class that can be subclassed to define a string enum

#### Scenario: StrEnum is in __all__
- **WHEN** `yascheduler.shared.compat.__all__` is inspected
- **THEN** `StrEnum` is included alongside `Self` and `Unpack`