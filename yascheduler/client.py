# FILE: yascheduler/client.py
# VERSION: 3.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Compat shim re-exporting Yascheduler from yascheduler.entrypoints.client; real implementation lives in entrypoints/client.py.
#   SCOPE: Re-export Yascheduler only (no Config, no internal helpers).
#   DEPENDS: M-ENTRYPOINTS-CLIENT
#   LINKS: M-ENTRYPOINTS-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Yascheduler - Public client class (compat re-export from yascheduler.entrypoints.client)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v3.0.0 - Reduce to compat shim re-exporting Yascheduler from yascheduler.entrypoints.client; real implementation relocated to entrypoints/client.py.
#   PREVIOUS_CHANGE: v2.4.0 - Extract to_sync to yascheduler.shared.async_utils.
# END_CHANGE_SUMMARY

"""Compat shim: re-exports Yascheduler from yascheduler.entrypoints.client.

This file exists solely to preserve the deep import path
``from yascheduler.client import Yascheduler`` for external downstream consumers.
"""

from yascheduler.entrypoints import Yascheduler

__all__ = ["Yascheduler"]
