"""Retry classification for background jobs.

These are not AppErrors: they never reach an HTTP response. A job runner retries a
TransientError and gives up at once on a PermanentError.
"""


class TransientError(Exception):
    """Temporary failure that may succeed on a later attempt (network blip, timeout)."""


class PermanentError(Exception):
    """Failure that will happen again on every attempt (missing entity, invalid data)."""
