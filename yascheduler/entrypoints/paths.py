"""Process-global file-path constants (config, log, pid) consumed by the entrypoints layer."""
# region MODULE_CONTRACT
# PURPOSE: Provide process-global file-path constants (config, log, pid) consumed by the entrypoints layer, derived from environment variables with filesystem defaults.
# SCOPE: Path constants only — CONFIG_FILE, LOG_FILE, PID_FILE.
# KEYWORDS: paths, constants, config, log, pid, environment
# endregion MODULE_CONTRACT

from os import getenv

CONFIG_FILE = getenv("YASCHEDULER_CONF_PATH", "/etc/yascheduler/yascheduler.conf")
LOG_FILE = getenv("YASCHEDULER_LOG_PATH", "/var/log/yascheduler.log")
PID_FILE = getenv("YASCHEDULER_PID_PATH", "/var/run/yascheduler.pid")
