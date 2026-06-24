# FILE: yascheduler/entrypoints/__init__.py
# VERSION: 2.0.0
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
#   LAST_CHANGE: v2.0.0 - client.py and aiida_plugin.py flat residents; daemon/ subpackage resident (daemon_systemd.py, daemon_sysv.py relocated from package root in relocate-daemon-launchers); only di.py and infra/cli/ remain deferred for follow-up.
#   PREVIOUS_CHANGE: v1.0.0 - Initial entrypoints layer facade; only client.py resident. di.py, aiida_plugin.py, daemon_*.py, infra/cli/ migrate in follow-up changes.
# END_CHANGE_SUMMARY

"""Entrypoints layer facade."""

from .client import Yascheduler

__all__ = ["Yascheduler"]
