"""Typed errors returned by Yandex Market Partner API operations."""


class YmApiError(RuntimeError):
    """Base error for Yandex Market API failures."""


class YmRateLimitError(YmApiError):
    """Yandex Market's HTTP 420 rate limit response."""


class YmAuthError(YmApiError):
    """Invalid or insufficient Yandex Market API credentials."""
