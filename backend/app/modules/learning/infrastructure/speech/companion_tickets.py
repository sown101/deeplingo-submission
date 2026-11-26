"""HMAC-signed companion session tickets: a short reference to a conversation kept on the server.

The ticket binds the learner, the conversation id and a single-use token id, and expires with the conversation (at
most `MAX_CONVERSATION_SECONDS` after it started). It carries no conversation content: that is in the
`SessionStore`, which also records each used token id so a turn cannot be replayed. Any change invalidates the
signature.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import UUID, uuid4

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.learning.application.agent.ports import InvalidCompanionTicket, SessionToken
from app.modules.learning.domain.companion import MAX_COMPANION_TICKET_CHARS

AUDIENCE = "deeplingo:speaking:companion"
ISSUER = "deeplingo-api"
MAX_TOKEN_CHARS = MAX_COMPANION_TICKET_CHARS
MAX_CONVERSATION_SECONDS = 900
VERSION = 2  # version 1 carried the whole conversation; such a ticket is refused (the conversation has ended)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iss: str
    aud: str
    sub: UUID
    iat: int
    exp: int
    jti: str = Field(min_length=8, max_length=64)
    v: int
    cid: UUID


class SignedCompanionTicketCodec:
    def __init__(self, secret: bytes, *, ttl_seconds: int = 1200,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        if len(secret) < 32:
            raise ValueError("Companion ticket secret must be at least 32 bytes")
        self._secret = secret
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock

    def issue(self, conversation_id: UUID, user_id: UUID, *, started_at: datetime) -> tuple[str, SessionToken]:
        now = self._clock()
        expires_at = min(now + self._ttl, started_at + timedelta(seconds=MAX_CONVERSATION_SECONDS))
        reference = SessionToken(conversation_id=conversation_id, user_id=user_id, token_id=uuid4().hex,
                                 expires_at=datetime.fromtimestamp(int(expires_at.timestamp()), UTC))
        payload = {"iss": ISSUER, "aud": AUDIENCE, "sub": str(user_id), "iat": int(now.timestamp()),
                   "exp": int(expires_at.timestamp()), "jti": reference.token_id, "v": VERSION,
                   "cid": str(conversation_id)}
        return jwt.encode(payload, self._secret, algorithm="HS256"), reference

    def read(self, token: str) -> SessionToken:
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_CHARS:
            raise InvalidCompanionTicket("Malformed ticket")
        try:
            claims = jwt.decode(
                token, self._secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
                options={"require": ["exp", "iat", "sub", "aud", "iss", "jti"]},
            )
            payload = _Payload.model_validate(claims)
        except (jwt.PyJWTError, ValidationError) as exc:
            raise InvalidCompanionTicket("Invalid ticket") from exc
        if payload.v != VERSION:
            raise InvalidCompanionTicket("Unsupported ticket version")
        return SessionToken(conversation_id=payload.cid, user_id=payload.sub, token_id=payload.jti,
                            expires_at=datetime.fromtimestamp(payload.exp, UTC))
