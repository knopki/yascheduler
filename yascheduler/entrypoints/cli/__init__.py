# FILE: yascheduler/entrypoints/cli/__init__.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Subpackage facade for the init and show_nodes CLI entry points.
#   SCOPE: no re-exports — init and show_nodes are invoked by console_script, not imported across layers.
#   DEPENDS: none
#   LINKS: M-ENTRYPOINTS-CLI-INIT, M-ENTRYPOINTS-CLI-SHOW-NODES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   none
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - show_nodes now a sibling resident (moved from infra/cli/ in relocate-show-nodes-command); no re-exports added.
#   PREVIOUS_CHANGE: v1.0.0 - Initial subpackage facade for the relocated init command; init moved from infra/cli/ in relocate-init-command.
# END_CHANGE_SUMMARY

"""Init and show_nodes CLI entry point subpackage facade."""
