# FILE: yascheduler/entrypoints/__init__.py
# VERSION: 2.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Layer facade for the entrypoints layer (outermost hexagonal layer: driving adapters + composition root).
#   SCOPE: Re-exports public symbols from entrypoints residents.
#   DEPENDS: M-ENTRYPOINTS-CLIENT
#   LINKS: M-ENTRYPOINTS-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Public client class (re-exported from .client)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.1.0 - client.py and aiida_plugin.py flat residents; daemon_systemd.py and daemon_sysv.py now residents of entrypoints/cli/ (moved from entrypoints/daemon/ in relocate-daemon-launchers-to-cli; the entrypoints/daemon/ subpackage was liquidated); only di.py and infra/cli/ remain deferred for follow-up.
#   PREVIOUS_CHANGE: v2.0.0 - client.py and aiida_plugin.py flat residents; daemon/ subpackage resident (daemon_systemd.py, daemon_sysv.py relocated from package root in relocate-daemon-launchers); only di.py and infra/cli/ remain deferred for follow-up.
# END_CHANGE_SUMMARY

"""Entrypoints layer facade."""

from .client import Yascheduler

__all__ = ["Yascheduler"]
