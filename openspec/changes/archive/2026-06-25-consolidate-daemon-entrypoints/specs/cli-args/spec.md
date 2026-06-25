## ADDED Requirements

### Requirement: Shared argparse helpers for CLI entry points

The `yascheduler/entrypoints/cli/args.py` module SHALL provide reusable argparse helpers
consumed by all six CLI command entry points and the three daemon launchers:

- `existing_path(s: str) -> Path` — an argparse type validator that returns `Path(s)` if `s`
  is an existing file, else raises `argparse.ArgumentTypeError` (argparse converts this to
  exit 2). This is the single source of truth for the "file must exist" validator;
  `submit.py` SHALL import `existing_path` from `args.py` instead of defining its own
  `_existing_path`.
- `add_config_arg(parser: ArgumentParser, *, default: str = CONFIG_FILE, dest: str =
  "config") -> None` — adds a `--config PATH` argument with `type=existing_path`, so a
  missing config file exits 2 with a clear `not a file: <path>` message instead of a cryptic
  parse error from `Config.from_config_parser`. The default is `CONFIG_FILE` (which is
  env-aware via `YASCHEDULER_CONF_PATH`).
- `add_log_level_arg(parser: ArgumentParser, *, default: str = "WARNING") -> None` — adds a
  `--log-level` argument with an explicit `choices` list of
  `["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]`. The system SHALL NOT use the private
  `logging._levelToName` / `logging._nameToLevel` APIs; the resolved level is obtained via
  `logging.getLevelName(args.log_level)` (returns the int), which works on Python 3.9+.
- `add_log_file_arg(parser: ArgumentParser, *, default: str | None = None) -> None` — adds
  a `--log-file PATH` argument (path string, no existence check; the `FileHandler` will fail
  loudly if the path is unwritable). Used only by the three daemon entry points.

Each helper SHALL be a function that mutates the passed parser (composing with the caller's
bespoke parser), NOT a base `ArgumentParser` subclass and NOT a single shared dispatcher.
This composes with command-specific positional arguments and mutually-exclusive groups.

#### Scenario: existing_path returns Path for an existing file
- **WHEN** `existing_path("/etc/yascheduler/yascheduler.conf")` is called and that file exists
- **THEN** it returns `Path("/etc/yascheduler/yascheduler.conf")`

#### Scenario: existing_path raises ArgumentTypeError for a missing file
- **WHEN** `existing_path("/nonexistent.conf")` is called
- **THEN** it raises `argparse.ArgumentTypeError` with a message containing `not a file: /nonexistent.conf`

#### Scenario: add_config_arg adds --config with existing_path validator
- **WHEN** a parser built with `add_config_arg(parser)` is given `--config /nonexistent`
- **THEN** argparse prints `not a file: /nonexistent` to stderr and exits 2

#### Scenario: add_config_arg default is CONFIG_FILE
- **WHEN** a parser built with `add_config_arg(parser)` is given no `--config`
- **THEN** `args.config` equals `CONFIG_FILE` (env-aware via `YASCHEDULER_CONF_PATH`)

#### Scenario: add_log_level_arg choices are explicit
- **WHEN** a parser built with `add_log_level_arg(parser)` is given `--log-level WARN`
- **THEN** argparse rejects it with exit 2 (only `WARNING` is accepted, not the `WARN` alias)

#### Scenario: add_log_level_arg resolves via logging.getLevelName
- **WHEN** `args.log_level == "WARNING"`
- **THEN** `logging.getLevelName(args.log_level)` returns `30` (the integer level for `WARNING`); the private `logging._nameToLevel` API is not used

#### Scenario: add_log_file_arg adds --log-file
- **WHEN** a parser built with `add_log_file_arg(parser, default="/var/log/yascheduler.log")` is given no `--log-file`
- **THEN** `args.log_file` equals `"/var/log/yascheduler.log"`

#### Scenario: add_log_file_arg default None means stderr
- **WHEN** a parser built with `add_log_file_arg(parser, default=None)` is given no `--log-file`
- **THEN** `args.log_file` is `None`, meaning logs go to stderr (no FileHandler is created)

#### Scenario: submit.py imports existing_path from args.py
- **WHEN** `yascheduler/entrypoints/cli/submit.py` is inspected
- **THEN** it imports `existing_path` from `yascheduler.entrypoints.cli.args` and does NOT define a private `_existing_path`