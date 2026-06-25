# FILE: yascheduler/entrypoints/__init__.py
# VERSION: 2.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Layer facade for the entrypoints layer (outermost hexagonal layer: driving adapters + composition root).
#   SCOPE: Re-exports public symbols from entrypoints residents: Yascheduler, make_daemon, make_cli_deps, CLIDeps.
#   DEPENDS: M-ENTRYPOINTS-CLIENT, M-DI
#   LINKS: M-ENTRYPOINTS-CLIENT, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Public client class (re-exported from .client)
#   make_daemon - Async Orchestrator factory (re-exported from .di)
#   make_cli_deps - Sync CLIDeps factory (re-exported from .di)
#   CLIDeps - Lightweight CLI dependency container (re-exported from .di)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.3.0 - relocate-di-to-entrypoints: di.py moved into entrypoints; facade now re-exports make_daemon, make_cli_deps, CLIDeps alongside Yascheduler. The "only di.py remains deferred" caveat in the previous entry is superseded.
#   PREVIOUS_CHANGE: v2.2.0 - consolidate-daemon-entrypoints: daemonize is now a resident of entrypoints/cli/ (moved from infra/cli/); yascheduler/infra/cli/ is liquidated; no deferred infra/cli migration remains.
#   PREVIOUS_CHANGE: v2.1.0 - client.py and aiida_plugin.py flat residents; daemon_systemd.py and daemon_sysv.py now residents of entrypoints/cli/ (moved from entrypoints/daemon/ in relocate-daemon-launchers-to-cli; the entrypoints/daemon/ subpackage was liquidated); only di.py and infra/cli/ remain deferred for follow-up.
# END_CHANGE_SUMMARY

"""Entrypoints layer facade."""

from .client import Yascheduler
from .di import CLIDeps, make_cli_deps, make_daemon

__all__ = ["Yascheduler", "make_daemon", "make_cli_deps", "CLIDeps"]
