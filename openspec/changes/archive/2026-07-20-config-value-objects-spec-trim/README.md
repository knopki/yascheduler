# config-value-objects-spec-trim

Trim config-value-objects spec to requirements-only; relocate design rationale, invariants, and the invented `SHALL NOT` / redundant-prose language into GRACE markup on `yascheduler/domain/settings.py`, `yascheduler/infra/persistence/db_config.py`, `yascheduler/entrypoints/config.py`, `yascheduler/shared/compat.py`, and the `[remote]`-parser region of `yascheduler/entrypoints/config_parser.py`.
