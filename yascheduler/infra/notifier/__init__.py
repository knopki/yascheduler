"""Notifier subpackage facade — re-exports notification handlers for the adapters layer."""
# region MODULE_CONTRACT
# PURPOSE: Expose a stable import surface for the webhook handler so cross-layer consumers import from one place, decoupled from the notifier subpackage internals.
# SCOPE: Re-exports webhook_handler from .webhook for cross-layer consumers.
# KEYWORDS: notifier, facade, webhook
# endregion MODULE_CONTRACT

from .webhook import webhook_handler

__all__ = ["webhook_handler"]
