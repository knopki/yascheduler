# FILE: yascheduler/adapters/cli/init.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: yainit CLI command — install service unit files and initialize DB schema.
#   SCOPE: init command + systemd/sysv service install + DB schema creation.
#   DEPENDS: M-CONFIG, M-DB, M-VARIABLES
#   LINKS: M-CLI-COMMANDS, M-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   init - Service initialization (systemd/sysv + DB)
#   _init_systemd - Write systemd service unit file
#   _init_sysv - Write SysV init script
#   _init_db - Create DB schema from SQL file
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from adapters/cli/commands.py per-command split.
# END_CHANGE_SUMMARY

import os
from pathlib import Path

from pg8000 import ProgrammingError

from yascheduler.client import to_sync
from yascheduler.config import Config
from yascheduler.db import DB
from yascheduler.variables import CONFIG_FILE


# START_CONTRACT: init
#   PURPOSE: Install systemd or sysv service and initialize the database schema
#   INPUTS: { None - reads config from CONFIG_FILE }
#   OUTPUTS: { None - no return value }
#   SIDE_EFFECTS: Writes service unit files, creates DB tables
#   LINKS: M-CLI-COMMANDS, M-DB
# END_CONTRACT: init
@to_sync
async def init() -> None:
    install_path = Path(__file__).parent.parent.parent  # yascheduler/
    has_systemd = not os.system("pidof systemd")  # noqa: ASYNC221
    if has_systemd:
        _init_systemd(install_path)
    else:
        _init_sysv(install_path)
    await _init_db(install_path)


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


async def _init_db(install_path: Path) -> None:
    config = Config.from_config_parser(CONFIG_FILE)
    db = await DB.create(config.db, automigrate=False)
    schema = (
        install_path / "adapters" / "persistence" / "sql" / "schema.sql"
    ).read_text()
    try:
        await db.run(schema)
        await db.commit()
        await db.close()
    except ProgrammingError as e:
        if "already exists" in str(e.args[0]):
            print("Database already initialized!")
        raise
