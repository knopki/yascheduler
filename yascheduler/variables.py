# FILE: yascheduler/variables.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Global constants for config file, PID file, and log file paths.
#   SCOPE: Path constants only.
#   DEPENDS: none
#   LINKS: M-MAIN, M-UTILS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CONFIG_FILE - Default config file path
#   PID_FILE - Default PID file path
#   LOG_FILE - Default log file path
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

"""Variables"""

from os import getenv

CONFIG_FILE = getenv("YASCHEDULER_CONF_PATH", "/etc/yascheduler/yascheduler.conf")
LOG_FILE = getenv("YASCHEDULER_LOG_PATH", "/var/log/yascheduler.log")
PID_FILE = getenv("YASCHEDULER_PID_PATH", "/var/run/yascheduler.pid")
