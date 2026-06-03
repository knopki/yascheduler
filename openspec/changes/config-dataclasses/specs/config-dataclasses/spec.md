## ADDED Requirements

### Requirement: Config classes use dataclasses

The system SHALL replace all attrs decorators and field definitions in
yascheduler/config/ with stdlib dataclasses equivalents.

#### Scenario: Config.from_config_parser() returns dataclass
- **WHEN** Config.from_config_parser(path) is called with a valid INI
- **THEN** the returned Config is a frozen dataclass, not an attrs class

#### Scenario: All sub-configs are dataclasses
- **WHEN** config.db, config.local, config.remote, config.clouds, config.engines are accessed
- **THEN** each is a frozen dataclass instance

### Requirement: Parsing behavior unchanged

The system SHALL preserve identical INI parsing behavior after the migration.

#### Scenario: Same INI produces same config
- **WHEN** the same INI file is parsed before and after the migration
- **THEN** all config field values are identical
