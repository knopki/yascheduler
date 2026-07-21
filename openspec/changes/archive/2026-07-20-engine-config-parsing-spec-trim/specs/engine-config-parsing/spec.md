# Delta: engine-config-parsing

## MODIFIED Requirements

### Requirement: Engine INI parser functions

The system SHALL provide three free functions in
`yascheduler.entrypoints.config_parser`:
`parse_engine_section(sec: SectionProxy, engines_dir: PurePath) -> Engine`,
`parse_engines(cfg: ConfigParser, engines_dir: PurePath) -> EngineRepository`,
and `engine_valid_fields() -> Sequence[str]`.

`parse_engine_section` SHALL validate the section and raise `ValueError` on
invalid INI.

#### Scenario: parse_engine_section builds Engine from INI

- **WHEN** `parse_engine_section(cfg["engine.fleur"], engines_dir)` is called with a section containing `spawn`, `input_files`, `output_files`, `platforms`, `check_cmd`, `deploy_local_archive=fleur.tar`
- **THEN** an `Engine` is returned with `name="fleur"`, `deployable=(LocalArchiveDeploy(file=engines_dir/"fleur"/"fleur.tar"),)`, and the other fields populated from the section

#### Scenario: parse_engine_section rejects unknown spawn placeholders

- **WHEN** `parse_engine_section` is called with a `spawn` value containing `{unknown_placeholder}`
- **THEN** `ValueError` is raised by the parser-side validator

#### Scenario: parse_engine_section rejects missing check methods

- **WHEN** `parse_engine_section` is called with neither `check_cmd` nor `check_pname` set
- **THEN** `ValueError` is raised by the parser-side validator

#### Scenario: parse_engines collects all engine sections

- **WHEN** `parse_engines(cfg, engines_dir)` is called with a `ConfigParser` containing `[engine.fleur]` and `[engine.cp2k]` sections
- **THEN** an `EngineRepository` is returned with `data` containing both engines keyed by name

#### Scenario: engine_valid_fields returns INI key list

- **WHEN** `engine_valid_fields()` is called
- **THEN** the returned sequence includes `spawn`, `input_files`, `output_files`, `platforms`, `platform_packages`, `check_cmd`, `check_pname`, `check_cmd_code`, `sleep_interval`, `deploy_local_files`, `deploy_local_archive`, `deploy_remote_archive` and excludes `name` and `deployable`
