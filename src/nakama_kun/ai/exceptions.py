"""Custom exception classes for nakama_kun's AI/LLM integration."""


class AIError(Exception):
    """Base exception for all AI/LLM operations."""

    pass


class ConfigurationError(AIError):
    """Raised when configuration is invalid or missing."""

    pass


class APIKeyNotFoundError(ConfigurationError):
    """Raised when an API key is missing."""

    pass


class RateLimitError(AIError):
    """Raised when LLM provider rate limits are exceeded."""

    pass


class NetworkError(AIError):
    """Raised when unable to reach the provider."""

    pass


class InvalidModelError(AIError):
    """Raised when the configured model is invalid or unavailable."""

    pass
