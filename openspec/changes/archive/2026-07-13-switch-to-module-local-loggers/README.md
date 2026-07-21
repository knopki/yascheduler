# switch-to-module-local-loggers

Remove injected `log` parameters from collaborator classes and functions; switch to module-local `get_logger(__name__)` binding so each module logs under its own M-ID namespace, restoring log provenance and reducing constructor ceremony.
