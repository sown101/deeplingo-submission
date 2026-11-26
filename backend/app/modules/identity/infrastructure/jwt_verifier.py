from __future__ import annotations

import time
import logging
from typing import Any
from uuid import UUID

import httpx
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError, PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKSetError

from app.platform.config import Settings, settings
from app.modules.identity.domain.errors import AuthenticationError, AuthenticationUnavailable
from app.modules.identity.domain.principal import CurrentUser


logger = logging.getLogger(__name__)


class SupabaseJWTVerifier:
    def __init__(self, config: Settings = settings):
        self.config = config
        self._jwks_client: PyJWKClient | None = None

    @property
    def issuer(self) -> str:
        if self.config.SUPABASE_JWT_ISSUER:
            return self.config.SUPABASE_JWT_ISSUER.rstrip("/")
        return f"{self.config.SUPABASE_URL.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        if self.config.SUPABASE_JWT_JWKS_URL:
            return self.config.SUPABASE_JWT_JWKS_URL
        return f"{self.issuer}/.well-known/jwks.json"

    def verify(self, token: str) -> CurrentUser:
        mode = self.config.SUPABASE_JWT_VERIFICATION_MODE.lower()
        logger.debug("Verifying Supabase JWT with mode=%s", mode)
        if mode == "jwks":
            claims = self._verify_with_jwks(token)
        elif mode == "auth-server":
            claims = self._verify_with_auth_server(token)
        elif mode == "hs256":
            claims = self._verify_with_hs256(token)
        else:
            raise AuthenticationError("Unsupported JWT verification mode")
        return self._current_user_from_claims(claims)

    def _decode_options(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "audience": self.config.SUPABASE_JWT_AUDIENCE or None,
            "options": {"verify_aud": bool(self.config.SUPABASE_JWT_AUDIENCE)},
        }

    def _verify_with_jwks(self, token: str) -> dict[str, Any]:
        try:
            if self._jwks_client is None:
                self._jwks_client = PyJWKClient(
                    self.jwks_url,
                    lifespan=600,
                    timeout=5,
                )
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                **self._decode_options(),
            )
        except (PyJWKClientConnectionError, PyJWKSetError) as exc:
            logger.warning("Supabase JWKS unavailable error=%s", type(exc).__name__)
            raise AuthenticationUnavailable("Authentication service unavailable") from exc
        except ExpiredSignatureError as exc:
            raise AuthenticationError("Token expired") from exc
        except InvalidTokenError as exc:
            raise AuthenticationError("Invalid token") from exc
        except Exception as exc:
            raise AuthenticationError("Token verification failed") from exc

    def _verify_with_hs256(self, token: str) -> dict[str, Any]:
        if not self.config.SUPABASE_JWT_SECRET:
            raise AuthenticationError("JWT secret is not configured")
        try:
            return jwt.decode(
                token,
                self.config.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                **self._decode_options(),
            )
        except ExpiredSignatureError as exc:
            raise AuthenticationError("Token expired") from exc
        except InvalidTokenError as exc:
            raise AuthenticationError("Invalid token") from exc

    def _verify_with_auth_server(self, token: str) -> dict[str, Any]:
        if not self.config.SUPABASE_URL or not self.config.SUPABASE_KEY:
            raise AuthenticationError("Supabase Auth server verification is not configured")
        try:
            logger.info("Calling Supabase Auth /user for JWT verification")
            response = httpx.get(
                f"{self.config.SUPABASE_URL.rstrip('/')}/auth/v1/user",
                headers={
                    "apikey": self.config.SUPABASE_KEY,
                    "Authorization": f"Bearer {token}",
                },
                timeout=5,
            )
        except httpx.HTTPError as exc:
            raise AuthenticationError("Auth server verification failed") from exc
        logger.info("Supabase Auth /user returned status=%s", response.status_code)
        if response.status_code != 200:
            raise AuthenticationError("Invalid token")
        data = response.json()
        user_id = data.get("id")
        if not user_id:
            raise AuthenticationError("Auth server response did not include a user id")
        return {
            "sub": user_id,
            "role": "authenticated",
            "email": data.get("email"),
            "iss": self.issuer,
            "aud": self.config.SUPABASE_JWT_AUDIENCE,
            "exp": int(time.time()) + 60,
        }

    def _current_user_from_claims(self, claims: dict[str, Any]) -> CurrentUser:
        subject = claims.get("sub")
        if not subject:
            raise AuthenticationError("Token is missing subject")
        try:
            user_id = UUID(str(subject))
        except ValueError as exc:
            raise AuthenticationError("Token subject is not a UUID") from exc
        role = str(claims.get("role") or "authenticated")
        if role != "authenticated":
            raise AuthenticationError("Token role is not allowed for user requests")
        return CurrentUser(
            id=user_id,
            role=role,
            email=claims.get("email"),
            claims=claims,
        )
