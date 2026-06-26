## ADDED Requirements

### Requirement: PostgresDbConfig value object

The system SHALL provide a `PostgresDbConfig` frozen stdlib dataclass in
`yascheduler/infra/persistence/db_config.py` with fields `user: str` (default
`"yascheduler"`), `password: str` (default `"password"`), `database: str`
(default `"database"`), `host: str` (default `"localhost"`), `port: int`
(default `5432`).

The dataclass SHALL be `@dataclass(frozen=True)` with no INI parsing methods
(`from_config_parser_section`, `get_valid_config_parser_fields`) and no attrs
dependency. Validation (`port` `ge(1)`) SHALL run in `__post_init__` raising
`ValueError` on violation.

`PostgresDbConfig` SHALL be importable from `yascheduler.infra.persistence`.
`postgres_uow.py` and `postgres_schema.py` SHALL import it via an intra-package
relative import (`from .db_config import PostgresDbConfig`), not from
`yascheduler.config`.

#### Scenario: PostgresDbConfig frozen
- **WHEN** an attempt is made to assign `cfg.port = 5433` on a `PostgresDbConfig` instance
- **THEN** `dataclasses.FrozenInstanceError` is raised

#### Scenario: PostgresDbConfig importable from persistence facade
- **WHEN** a consumer imports `from yascheduler.infra.persistence import PostgresDbConfig`
- **THEN** the symbol resolves without ImportError

#### Scenario: PostgresDbConfig rejects invalid port
- **WHEN** `PostgresDbConfig(port=0)` is constructed
- **THEN** `ValueError` is raised in `__post_init__`

#### Scenario: PostgresUnitOfWork uses intra-package import
- **WHEN** `postgres_uow.py` is inspected for its `ConfigDb` import
- **THEN** it imports `PostgresDbConfig` from `.db_config` (intra-package), not from `yascheduler.config`

#### Scenario: apply_schema uses intra-package import
- **WHEN** `postgres_schema.py::apply_schema` is inspected for its config type
- **THEN** the signature is `apply_schema(config: PostgresDbConfig)` and the import is `from .db_config import PostgresDbConfig`