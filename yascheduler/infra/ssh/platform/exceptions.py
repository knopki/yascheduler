"""Custom exceptions for remote machine operations."""
# region MODULE_CONTRACT
# PURPOSE: Exception types for platform detection and remote machine operations.
# SCOPE: PlatformGuessFailedError exception class.
# KEYWORDS: exceptions, platform detection, PlatformGuessFailedError
# endregion MODULE_CONTRACT

__all__ = ["PlatformGuessFailedError"]


class PlatformGuessFailedError(Exception):
    """Raised when the remote platform cannot be determined."""
