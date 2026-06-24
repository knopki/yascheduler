# FILE: yascheduler/entrypoints/cli/init.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: yainit CLI command — install service unit files and/or apply DB schema, with --schema/--daemon subset-selector flags.
#   SCOPE: init command + argparse + systemd/sysv service install + DB schema application delegation.
#   DEPENDS: M-PERSISTENCE-SCHEMA, M-CONFIG, M-SHARED
#   LINKS: M-ENTRYPOINTS-CLI-INIT, M-PERSISTENCE-SCHEMA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   init - Parse --schema/--daemon flags, install service and/or apply schema, exit 0/1/2
#   _init_systemd - Render and write the systemd unit file (overwrite if exists)
#   _init_sysv - Render and write the SysV init script (overwrite + chmod 0755)
#   _init_schema - Apply schema.sql via apply_schema adapter
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Reimplemented at entrypoints/cli/ in relocate-init-command: moved from infra/cli/init.py, added --schema/--daemon argparse flags, exit-code contract 0/1/2, overwrite-if-exists service files, /run/systemd/system detection, OSError handling.
# END_CHANGE_SUMMARY

import argparse
import os
import sys
from pathlib import Path

from pg8000 import DatabaseError

from yascheduler.config import Config
from yascheduler.infra import apply_schema
from yascheduler.shared import CONFIG_FILE


# START_CONTRACT: init
#   PURPOSE: Parse --schema/--daemon flags, install service and/or apply schema per the selected subset, exit 0/1/2.
#   INPUTS: { argv: list[str] | None - optional argv for argparse, None reads sys.argv (console_script default) }
#   OUTPUTS: { None - no return value, calls sys.exit }
#   SIDE_EFFECTS: Writes service unit files, creates DB tables, calls sys.exit
#   LINKS: M-ENTRYPOINTS-CLI-INIT, M-PERSISTENCE-SCHEMA
# END_CONTRACT: init
def init(argv: list[str] | None = None) -> None:
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

    # START_BLOCK_VALIDATE_FLAGS
    args = parser.parse_args(argv)
    # END_BLOCK_VALIDATE_FLAGS

    install_path = Path(__file__).parent.parent.parent  # yascheduler/

    # START_BLOCK_HANDLE_FAILURE
    try:
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
            _init_schema()

        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    # END_BLOCK_HANDLE_FAILURE


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
    print("Installing systemd service")
    src_unit_file = install_path / "data/yascheduler.service"
    daemon_file = install_path / "entrypoints/daemon/daemon_systemd.py"
    systemd_script = src_unit_file.read_text("utf-8").replace(
        "%YASCHEDULER_DAEMON_FILE%", str(daemon_file)
    )
    try:
        unit_file.write_text(systemd_script, "utf-8")
    except OSError as e:
        print(f"Error: cannot write to {unit_file}: {e}")
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
    print("Installing SysV service")
    src_startup_file = install_path / "data/yascheduler.sh"
    daemon_file = install_path / "entrypoints/daemon/daemon_sysv.py"
    sysv_script = src_startup_file.read_text("utf-8").replace(
        "%YASCHEDULER_DAEMON_FILE%", str(daemon_file)
    )
    try:
        startup_file.write_text(sysv_script, "utf-8")
        os.chmod(startup_file, 0o755)
    except OSError as e:
        print(f"Error: cannot write to {startup_file}: {e}")
        sys.exit(1)


# START_CONTRACT: _init_schema
#   PURPOSE: Apply schema.sql via apply_schema adapter.
#   INPUTS: { None - reads config from CONFIG_FILE }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: Creates DB tables; raises SystemExit(1) on DatabaseError.
#   LINKS: M-PERSISTENCE-SCHEMA
# END_CONTRACT: _init_schema
def _init_schema() -> None:
    config = Config.from_config_parser(CONFIG_FILE)
    try:
        # START_BLOCK_APPLY_SCHEMA
        apply_schema(config.db)
        # END_BLOCK_APPLY_SCHEMA
    except DatabaseError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
