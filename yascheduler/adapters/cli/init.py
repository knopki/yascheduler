# FILE: yascheduler/adapters/cli/init.py
# VERSION: 2.0.0
# START_MODULE_CONTRACT
#   PURPOSE: yainit CLI command — install service unit files and initialize DB schema.
#   SCOPE: init command + systemd/sysv service install + DB schema creation.
#   DEPENDS: M-CONFIG, M-VARIABLES, M-PERSISTENCE-SCHEMA
#   LINKS: M-CLI-COMMANDS, M-PERSISTENCE-SCHEMA
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   init - Service initialization (systemd/sysv + DB), sync
#   _init_systemd - Write systemd service unit file
#   _init_sysv - Write SysV init script
#   _init_db - Create DB schema via apply_schema adapter
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Sync init(); _init_db() calls apply_schema() instead of legacy DB class.
#   PREVIOUS_CHANGE: v1.0.0 - Extracted from adapters/cli/commands.py per-command split.
# END_CHANGE_SUMMARY

import os
from pathlib import Path

from yascheduler.adapters.persistence.postgres_schema import apply_schema
from yascheduler.config import Config
from yascheduler.variables import CONFIG_FILE


# START_CONTRACT: init
#   PURPOSE: Install systemd or sysv service and initialize the database schema
#   INPUTS: { None - reads config from CONFIG_FILE }
#   OUTPUTS: { None - no return value }
#   SIDE_EFFECTS: Writes service unit files, creates DB tables
#   LINKS: M-CLI-COMMANDS, M-PERSISTENCE-SCHEMA
# END_CONTRACT: init
def init() -> None:
    install_path = Path(__file__).parent.parent.parent  # yascheduler/
    has_systemd = not os.system("pidof systemd")
    if has_systemd:
        _init_systemd(install_path)
    else:
        _init_sysv(install_path)
    _init_db()


def _init_systemd(install_path: Path) -> None:
    print("Installing systemd service")
    src_unit_file = install_path / "data/yascheduler.service"
    unit_file = Path("/lib/systemd/system/yascheduler.service")
    if not unit_file.is_file():
        if not os.access(unit_file, os.W_OK):
            print(f"Error: cannot write to {unit_file}")
            return
        daemon_file = install_path / "daemon_systemd.py"
        systemd_script = src_unit_file.read_text("utf-8").replace(
            "%YASCHEDULER_DAEMON_FILE%", str(daemon_file)
        )
        unit_file.write_text(systemd_script, "utf-8")


def _init_sysv(install_path: Path) -> None:
    print("Installing SysV service")
    src_startup_file = install_path / "data/yascheduler.sh"
    startup_file = Path("/etc/init.d/yascheduler")
    if not startup_file.is_file():
        if not os.access(startup_file, os.W_OK):
            print(f"Error: cannot write to {startup_file}")
            return
        daemon_file = install_path / "daemon_sysv.py"
        sysv_script = src_startup_file.read_text("utf-8").replace(
            "%YASCHEDULER_DAEMON_FILE%", str(daemon_file)
        )
        startup_file.write_text(sysv_script, "utf-8")
        os.chmod(startup_file, 0o755)


def _init_db() -> None:
    config = Config.from_config_parser(CONFIG_FILE)
    apply_schema(config.db)
