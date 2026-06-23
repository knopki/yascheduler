# FILE: yascheduler/infra/notifier/__init__.py
# VERSION: 1.1.1
# START_MODULE_CONTRACT
#   PURPOSE: Notifier subpackage facade — re-exports notification handlers for the adapters layer.
#   SCOPE: Re-exports webhook_handler from .webhook.
#   DEPENDS: M-NOTIFIER-WEBHOOK
#   LINKS: M-NOTIFIER-WEBHOOK
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   webhook_handler - Async webhook event handler dispatching domain events to configured endpoint
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.1.0 - Re-export webhook_handler as public surface (clean-architecture-imports).
# END_CHANGE_SUMMARY

from .webhook import webhook_handler

__all__ = ["webhook_handler"]
