"""Process-global file-path constants (config, log, pid) consumed by the entrypoints layer."""
# FILE: yascheduler/entrypoints/paths.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Process-global file-path constants (config, log, pid) consumed by the entrypoints layer.
#   SCOPE: Path constants only — derived from environment with filesystem defaults.
#   DEPENDS: none
#   LINKS: M-ENTRYPOINTS-PATHS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CONFIG_FILE - Default config file path
#   PID_FILE - Default PID file path
#   LOG_FILE - Default log file path
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Relocated from yascheduler/shared/variables.py to yascheduler/entrypoints/paths.py.
#   PREVIOUS_CHANGE: v1.6.0 - Moved from yascheduler/variables.py to yascheduler/shared/variables.py.
# END_CHANGE_SUMMARY

from os import getenv

CONFIG_FILE = getenv("YASCHEDULER_CONF_PATH", "/etc/yascheduler/yascheduler.conf")
LOG_FILE = getenv("YASCHEDULER_LOG_PATH", "/var/log/yascheduler.log")
PID_FILE = getenv("YASCHEDULER_PID_PATH", "/var/run/yascheduler.pid")
