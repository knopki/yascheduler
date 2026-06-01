# FILE: yascheduler/webhook.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Webhook payload data transfer object.
#   SCOPE: WebhookPayload frozen dataclass.
#   DEPENDS: none
#   LINKS: M-SCHEDULER, M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   WebhookPayload - Webhook request data shape
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extract WebhookPayload from scheduler.py and orchestrator.py; replace attrs with dataclasses.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class WebhookPayload:
    task_id: int = field()
    status: int = field()
    custom_params: Mapping[str, Any] = field(default_factory=dict)
