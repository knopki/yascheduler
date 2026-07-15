"""yainit CLI command — install service unit files and/or apply DB schema + migrations, with --schema/--daemon subset-selector flags."""
# FILE: yascheduler/entrypoints/cli/init.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: yainit CLI command — install service unit files and/or apply DB schema + migrations, with --schema/--daemon subset-selector flags.
#   SCOPE: init command — service install and/or DB schema+migrations application.
#   DEPENDS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS, M-ENTRYPOINTS-CONFIG, M-ENTRYPOINTS, M-ENTRYPOINTS-CLI-ARGS
#   LINKS: M-ENTRYPOINTS-CLI-INIT, M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   init - Parse --schema/--daemon flags, install service and/or apply schema+migrations, exit 0/1/2
#   _init_systemd - Render and write the systemd unit file (overwrite if exists)
#   _init_sysv - Render and write the SysV init script (overwrite + chmod 0755)
#   _init_schema - Apply schema.sql then pending migrations (config_path param honors --config)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Call apply_migrations(config.db) after apply_schema(config.db) in _init_schema (add-db-migrations).
#   PREVIOUS_CHANGE: v1.2.2 - Import CONFIG_FILE from yascheduler.entrypoints facade.
# END_CHANGE_SUMMARY

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pg8000 import DatabaseError

from yascheduler.entrypoints import CONFIG_FILE
from yascheduler.entrypoints.config_parser import parse_config
from yascheduler.infra import apply_migrations, apply_schema

from .args import add_config_arg, add_log_level_arg


# START_CONTRACT: _init_systemd
#   PURPOSE: Render and write the systemd unit file, overwriting if it exists.
#   INPUTS: { install_path: Path - yascheduler/ package root, unit_file: Path - target unit path (default /etc/systemd/system/yascheduler.service, injectable for tests) }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Writes the unit file; raises SystemExit(1) on OSError.
#   LINKS: M-ENTRYPOINTS-CLI-INIT
# END_CONTRACT: _init_systemd
def _init_systemd(
    install_path: Path,
    unit_file: Path = Path("/etc/systemd/system/yascheduler.service"),
) -> None:
    sys.stdout.write("Installing systemd service\n")
    src_unit_file = install_path / "data/yascheduler.service"
    daemon_file = install_path / "entrypoints/cli/daemon_systemd.py"
    systemd_script = src_unit_file.read_text("utf-8").replace(
        "%YASCHEDULER_DAEMON_FILE%",
        str(daemon_file),
    )
    try:
        unit_file.write_text(systemd_script, "utf-8")
    except OSError as e:
        sys.stderr.write(f"Error: cannot write to {unit_file}: {e}\n")
        sys.exit(1)


# START_CONTRACT: _init_sysv
#   PURPOSE: Render and write the SysV init script, overwriting if it exists, and chmod 0755.
#   INPUTS: { install_path: Path - yascheduler/ package root, startup_file: Path - target init.d path (default /etc/init.d/yascheduler, injectable for tests) }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Writes the init script and sets mode 0755; raises SystemExit(1) on OSError.
#   LINKS: M-ENTRYPOINTS-CLI-INIT
# END_CONTRACT: _init_sysv
def _init_sysv(
    install_path: Path,
    startup_file: Path = Path("/etc/init.d/yascheduler"),
) -> None:
    sys.stdout.write("Installing SysV service\n")
    src_startup_file = install_path / "data/yascheduler.sh"
    daemon_file = install_path / "entrypoints/cli/daemon_sysv.py"
    sysv_script = src_startup_file.read_text("utf-8").replace(
        "%YASCHEDULER_DAEMON_FILE%",
        str(daemon_file),
    )
    try:
        startup_file.write_text(sysv_script, "utf-8")
        startup_file.chmod(0o755)
    except OSError as e:
        sys.stderr.write(f"Error: cannot write to {startup_file}: {e}\n")
        sys.exit(1)


# START_CONTRACT: _init_schema
#   PURPOSE: Apply schema.sql via apply_schema then pending migrations via apply_migrations, honoring --config via config_path.
#   INPUTS: { config_path: str | Path - path to the config file (default CONFIG_FILE) }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates DB tables and the yascheduler_migrations tracker; applies pending migrations; raises SystemExit(1) on DatabaseError.
#   LINKS: M-PERSISTENCE-SCHEMA, M-PERSISTENCE-MIGRATIONS
# END_CONTRACT: _init_schema
def _init_schema(config_path: str | Path = CONFIG_FILE) -> None:
    config = parse_config(config_path)
    try:
        # START_BLOCK_APPLY_SCHEMA
        apply_schema(config.db)
        # END_BLOCK_APPLY_SCHEMA
        # START_BLOCK_APPLY_MIGRATIONS
        apply_migrations(config.db)
        # END_BLOCK_APPLY_MIGRATIONS
    except DatabaseError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


# START_CONTRACT: init
#   PURPOSE: Parse --schema/--daemon flags, install service and/or apply schema per the selected subset, exit 0/1/2.
#   INPUTS: { argv: list[str] | None - optional argv for argparse, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - no return value, calls sys.exit }
#   SIDE_EFFECTS: Writes service unit files, creates DB tables, calls sys.exit
#   LINKS: M-ENTRYPOINTS-CLI-INIT, M-PERSISTENCE-SCHEMA
# END_CONTRACT: init
def init(argv: list[str] | None = None) -> None:
    """Parse --schema/--daemon flags, install service and/or apply schema per the selected subset, exit 0/1/2."""
    parser = argparse.ArgumentParser(
        prog="yainit",
        description="Install yascheduler service and initialize the database schema",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Apply only the database schema",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Install only the service unit file",
    )
    add_config_arg(parser)
    add_log_level_arg(parser, default="WARNING")

    # START_BLOCK_VALIDATE_FLAGS
    args = parser.parse_args(argv)
    # END_BLOCK_VALIDATE_FLAGS

    install_path = Path(__file__).parent.parent.parent  # yascheduler/

    # START_BLOCK_HANDLE_FAILURE
    try:
        # START_BLOCK_CONFIGURE_LOGGER
        root = logging.getLogger()
        root.setLevel(logging.getLevelName(args.log_level))
        if not root.handlers:
            root.addHandler(logging.StreamHandler(sys.stderr))
        # END_BLOCK_CONFIGURE_LOGGER

        # START_BLOCK_DISPATCH
        run_daemon = not args.schema or args.daemon
        run_schema = not args.daemon or args.schema
        # END_BLOCK_DISPATCH

        if run_daemon:
            # START_BLOCK_DETECT_INIT_SYSTEM
            has_systemd = Path("/run/systemd/system").is_dir()
            # END_BLOCK_DETECT_INIT_SYSTEM
            if has_systemd:
                _init_systemd(install_path)
            else:
                _init_sysv(install_path)

        if run_schema:
            _init_schema(args.config)

        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE


if __name__ == "__main__":
    init()
