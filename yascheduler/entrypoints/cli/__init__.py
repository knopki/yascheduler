"""Init, show_nodes, submit, manage_node, check_status CLI entry points and daemonize/daemon_systemd/daemon_sysv daemon launcher subpackage facade."""
# region MODULE_CONTRACT
# PURPOSE: Serve as the CLI subpackage facade — all console_script entry points and daemon launchers are siblings under this package.
# SCOPE: Subpackage facade — no re-exports; all entry points invoked by console_script or service template path substitution.
# endregion MODULE_CONTRACT
