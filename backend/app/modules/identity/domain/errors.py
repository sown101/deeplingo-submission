class AuthenticationError(Exception):
    """Raised when a token cannot be authenticated."""


class AuthenticationUnavailable(AuthenticationError):
    """Verification could not reach a usable upstream authentication service."""
