# FILE: yascheduler/clouds/__init__.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Public re-exports from clouds submodules.
#   SCOPE: Re-exports of top-level cloud symbols.
#   DEPENDS: M-CLOUD-MANAGER
#   LINKS: M-CLOUD-MANAGER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   CloudAPIManager - Cloud API manager class
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY

"""Clouds module"""

from .cloud_api_manager import CloudAPIManager

__all__ = [
    "CloudAPIManager",
]
