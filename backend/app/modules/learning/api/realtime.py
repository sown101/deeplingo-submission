"""The agent's voice channel WebSocket, and the learner's speaking session result.

Protocol: the client's first text message is {"type": "auth", "token": "<access token>"} (browsers
cannot set headers on a WebSocket, and a token in the URL would reach logs), then {"type": "start",
"entry": ..., "library_item_id": ..., "day": ...}; after {"type": "ready"} it streams binary 16 kHz
16-bit mono PCM and may send {"type": "end"}. The server sends binary PCM for the companion's speech
and JSON events: transcript, turn_complete, interrupted, resumed, ended, error. "ready" carries the
session_id: when the socket drops, a new one sends auth, then {"type": "resume", "session_id": ...,
"last_seq": <JSON events received>} within a few seconds and gets the missed events (else 4404).
"""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.bootstrap.wiring.session_events import get_session_events_service

from app.bootstrap.wiring.agent import get_voice_agent_service
from app.modules.learning.application.agent.voice import VoiceChannel

router = APIRouter()


@router.get("/learner/me/speaking-sessions/{session_id}")
def speaking_session_result(session_id: UUID, user: CurrentUser = Depends(require_authenticated_user),
                            service=Depends(get_session_events_service)):
    result = service.result(user.id, session_id) if service is not None else None
    if result is None:
        raise HTTPException(404, detail={"code": "speaking_session_not_found"})
    return result


class _WebSocketChannel:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def receive(self):
        try:
            message = await self.websocket.receive()
        except RuntimeError:
            return "closed", None
        if message.get("type") == "websocket.disconnect":
            return "closed", None
        if message.get("bytes") is not None:
            return "bytes", message["bytes"]
        if message.get("text") is not None:
            return "text", message["text"]
        return "closed", None

    async def send_json(self, message: dict) -> None:
        await self.websocket.send_text(json.dumps(message, ensure_ascii=False))

    async def send_bytes(self, data: bytes) -> None:
        await self.websocket.send_bytes(data)

    async def close(self, code: int) -> None:
        await self.websocket.close(code)


@router.websocket("/learner/me/companion/realtime")
async def companion_realtime(
    websocket: WebSocket,
    service: VoiceChannel = Depends(get_voice_agent_service),
):
    await websocket.accept()
    await service.run(_WebSocketChannel(websocket))
