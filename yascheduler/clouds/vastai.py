# FILE: yascheduler/clouds/vastai.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Backward-compatible re-export shim for VastAI cloud methods.
#   SCOPE: Re-exports create/delete node functions from the new adapters location.
#   DEPENDS: M-CLOUD-VASTAI
#   LINKS: M-CLOUD-VASTAI
# END_MODULE_CONTRACT
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - Converted to re-export shim; implementation moved to adapters/cloud/providers/vastai.py.
# END_CHANGE_SUMMARY

"""VastAI cloud methods — re-export shim"""

from yascheduler.adapters.cloud.providers.vastai import (  # noqa: F401
    vastai_create_node,
    vastai_delete_node,
)
