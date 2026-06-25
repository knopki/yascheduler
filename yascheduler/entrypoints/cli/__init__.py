# FILE: yascheduler/entrypoints/cli/__init__.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Subpackage facade for the init, show_nodes, submit, and manage_node CLI entry points.
#   SCOPE: no re-exports — init, show_nodes, submit, and manage_node are invoked by console_script, not imported across layers.
#   DEPENDS: none
#   LINKS: M-ENTRYPOINTS-CLI-INIT, M-ENTRYPOINTS-CLI-SHOW-NODES, M-ENTRYPOINTS-CLI-SUBMIT, M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   none
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - manage_node now a sibling resident (moved from infra/cli/ in relocate-manage-node-command); no re-exports added.
#   PREVIOUS_CHANGE: v1.2.0 - submit now a sibling resident (moved from infra/cli/ in relocate-submit-command); no re-exports added.
# END_CHANGE_SUMMARY

"""Init, show_nodes, submit, and manage_node CLI entry point subpackage facade."""
