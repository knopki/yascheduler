## Purpose

Define the immutable config value objects — database, local settings,
remote defaults, cloud configs, and the `Config` aggregate — and the
INI-to-value-object parsing rules they obey.

## Requirements

### Requirement: Config value objects

The system SHALL provide one immutable value object per INI section:
the database connection, the local daemon settings, the remote SSH
defaults, the cloud configs, and the `Config` aggregate that holds
them. Cross-cutting cloud configuration SHALL follow the `CloudConfig`
structural port; the authoritative field list and parsing rules live
in the `cloud` spec.

The `Config` aggregate SHALL be built once and SHALL stay immutable.
A change to a value SHALL return a new aggregate; the original is not
changed. Only the composition root SHALL hold the aggregate; use cases
and adapters SHALL receive only the value objects they need.

#### Scenario: aggregate change returns a new aggregate

- **WHEN** a value in the aggregate is changed
- **THEN** a new aggregate is returned and the original aggregate keeps its prior value

### Requirement: INI section parsing

The parser SHALL map each INI section to its value object. A key that
no value object in that section accepts SHALL emit a warning at parse
time. Cloud sections SHALL be dispatched through a per-provider parser
registry; adding a provider SHALL add one registry entry.

#### Scenario: unknown key emits a warning

- **WHEN** the parser meets a key that no value object in the section accepts
- **THEN** a warning is emitted and parsing continues

### Requirement: absent DB password warns

The `[db]` section SHALL emit a warning at parse time when the `password` key
is absent, so production deploys do not silently run against the insecure
default password. Parsing SHALL continue and return the default password.

#### Scenario: missing [db] password emits a warning

- **WHEN** the `[db]` section has no `password` key
- **THEN** a warning is emitted and the parsed config keeps the default password

### Requirement: jump_port range

The `[remote]` `jump_port` key SHALL be an integer in the closed range
1–65535. The default is 22 when the key is absent. A value outside the
range or not an integer SHALL fail parsing.

#### Scenario: out-of-range or non-integer jump_port fails parsing

- **WHEN** the parser meets a `jump_port` value outside 1–65535 or not an integer
- **THEN** parsing fails with an error

### Requirement: Azure forbids the root username

An Azure cloud section SHALL reject the username `root`. The parser
SHALL fail at parse time.

#### Scenario: Azure root username fails parsing

- **WHEN** an Azure cloud section sets the username to `root`
- **THEN** parsing fails with an error

#### Scenario: the Azure root ban does not fire on an inherited username

- **GIVEN** the `[remote]` default username is `root` and an Azure cloud section omits `az_user`
- **WHEN** the configuration is loaded
- **THEN** parsing succeeds
- **AND** the Azure username is inherited from `[remote]`
