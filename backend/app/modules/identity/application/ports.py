from typing import Protocol

from app.modules.identity.domain.principal import CurrentUser


class TokenVerifier(Protocol):
    def verify(self, token: str) -> CurrentUser:
        """Return the verified principal or raise AuthenticationError."""
        ...
