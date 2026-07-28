## Purpose

Parse engine INI sections into engine value objects. Keeps INI
parsing in the entrypoints layer so the domain model does not
reference an entrypoints module.

## Requirements

### Requirement: Engine INI parser

The system SHALL provide an engine INI parser that reads engine
sections from the configuration and builds the engine collection.
Each section SHALL be validated. An invalid section SHALL raise a
value error before any engine is built.

The parser SHALL reject a spawn template that references an unknown
placeholder. The parser SHALL require at least one check method
(check command or process name) per engine.

The parser SHALL report the set of INI keys it accepts, so unknown
keys can be warned about.

#### Scenario: a valid section builds an engine

- **WHEN** a section is parsed with a spawn template, input files, output files, platforms, a check method, and a deploy source
- **THEN** an engine is built with the section's values, including the deploy source resolved against the engines directory

#### Scenario: an invalid section is rejected

- **WHEN** a section is parsed with a spawn template that references an unknown placeholder, or with no check method set
- **THEN** the parser raises a value error and no engine is built

#### Scenario: all engine sections collect into the engine collection

- **WHEN** the configuration contains multiple engine sections
- **THEN** the parser returns an engine collection keyed by engine name, with one entry per section
