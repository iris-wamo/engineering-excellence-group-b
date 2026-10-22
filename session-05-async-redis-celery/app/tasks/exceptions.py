"""Exceptions for Celery background tasks distinguishing retryable and non-retryable failures."""

from taskflow_shared.errors import PermanentError, TransientError


class NotificationError(Exception):
    """Base exception for notification background task failures."""


class NotificationTransientError(NotificationError, TransientError):
    """Temporary/transient failure that SHOULD be retried (e.g. network blip, DB timeout)."""


class NotificationPermanentError(NotificationError, PermanentError):
    """Permanent/fatal failure that should NOT be retried (e.g. entity not found, invalid data)."""


class NotificationNotFoundError(NotificationPermanentError):
    """Raised when the notification row the job was dispatched for does not exist."""


class TaskNotFoundError(NotificationPermanentError):
    """Raised when the target task does not exist."""


class RecipientNotFoundError(NotificationPermanentError):
    """Raised when the notification recipient does not exist."""


class InvalidAssignmentNotificationError(NotificationPermanentError):
    """Raised when the assignment data is invalid or cannot be notified."""
