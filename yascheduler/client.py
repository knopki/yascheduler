"""Compat shim: re-exports Yascheduler from yascheduler.entrypoints.client."""
# region MODULE_CONTRACT
# PURPOSE: Preserve the deep import path ``yascheduler.client.Yascheduler`` for external consumers after the implementation moved to entrypoints/client.py.
# SCOPE: Single re-export of Yascheduler — compat shim only, no real code.
# KEYWORDS: compat, shim, re-export, client
# endregion MODULE_CONTRACT

from yascheduler.entrypoints import Yascheduler

__all__ = ["Yascheduler"]
