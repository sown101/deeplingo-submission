"""Gemini Live (native audio) on Vertex AI, behind the learning RealtimeVoice port.

A documented exception to the OpenAI-compatible provider path: the Live API is a bidirectional
WebSocket. Authentication uses Application Default Credentials (the VM's service account); no key is
configured and nothing reaches clients. Message shapes were checked in the G6.1 trial.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from collections.abc import AsyncIterator, Callable

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from app.modules.learning.application.agent.prompts import JOINED_CUE
from app.modules.learning.application.agent.tools import TOOL_SPECS
from app.modules.learning.application.agent.realtime_port import (
    AudioOut,
    GoAway,
    Interrupted,
    RealtimeEvent,
    RealtimeUnavailable,
    ResumptionUpdate,
    ToolCall,
    TranscriptPiece,
    TurnComplete,
)
from app.modules.learning.domain.realtime import INPUT_SAMPLE_RATE

SETUP_TIMEOUT_S = 15
DEFAULT_OUTPUT_RATE = 24_000
_RATE = re.compile(r"rate=(\d+)")
_SECONDS = re.compile(r"^(\d+(?:\.\d+)?)s$")


def adc_token(project: str) -> str:
    """A short-lived OAuth token from Application Default Credentials (blocking; call in a thread)."""
    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"],
                                         quota_project_id=project)
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token


def _gemini_schema(schema: dict) -> dict:
    """The registry's JSON schema in the Live API's dialect (upper-case type names)."""
    converted = {key: value for key, value in schema.items() if key not in ("type", "properties", "items")}
    converted["type"] = schema["type"].upper()
    if "properties" in schema:
        converted["properties"] = {name: _gemini_schema(value) for name, value in schema["properties"].items()}
    if "items" in schema:
        converted["items"] = _gemini_schema(schema["items"])
    return converted


# The only functions the model may call (the core's ToolRegistry); the server validates every argument.
TOOLS = [{"functionDeclarations": [
    {"name": spec.name, "description": spec.description, "parameters": _gemini_schema(spec.parameters)}
    for spec in TOOL_SPECS]}]


def parse_server_message(message: dict) -> list[RealtimeEvent]:
    """Provider message -> relay events, in order. Unknown fields are ignored."""
    events: list[RealtimeEvent] = []
    for call in (message.get("toolCall") or {}).get("functionCalls", []):
        if isinstance(call, dict) and call.get("id") and call.get("name"):
            events.append(ToolCall(id=str(call["id"]), name=str(call["name"]), args=call.get("args") or {}))
    content = message.get("serverContent") or {}
    for part in (content.get("modelTurn") or {}).get("parts", []):
        data = part.get("inlineData") or {}
        if data.get("data"):
            match = _RATE.search(data.get("mimeType", ""))
            events.append(AudioOut(pcm=base64.b64decode(data["data"]),
                                   sample_rate=int(match.group(1)) if match else DEFAULT_OUTPUT_RATE))
    learner = (content.get("inputTranscription") or {}).get("text")
    if learner:
        events.append(TranscriptPiece(role="learner", text=learner))
    companion = (content.get("outputTranscription") or {}).get("text")
    if companion:
        events.append(TranscriptPiece(role="companion", text=companion))
    if content.get("interrupted"):
        events.append(Interrupted())
    if content.get("turnComplete"):
        events.append(TurnComplete())
    update = message.get("sessionResumptionUpdate")
    if isinstance(update, dict):
        handle = update.get("newHandle")
        events.append(ResumptionUpdate(handle=handle if isinstance(handle, str) and handle else None,
                                       resumable=update.get("resumable") is True))
    away = message.get("goAway")
    if isinstance(away, dict):
        left = _SECONDS.match(str(away.get("timeLeft") or ""))
        events.append(GoAway(time_left_ms=int(float(left.group(1)) * 1000) if left else None))
    return events


# Every turn is billed for the whole context window, so old audio is evicted: about two minutes of talk stay.
CONTEXT_TRIGGER_TOKENS = 20000
CONTEXT_TARGET_TOKENS = 12000


class GeminiLiveConnection:
    def __init__(self, ws):
        self.ws = ws

    async def send_audio(self, pcm: bytes) -> None:
        try:
            await self.ws.send(json.dumps({"realtimeInput": {"audio": {
                "data": base64.b64encode(pcm).decode("ascii"), "mimeType": f"audio/pcm;rate={INPUT_SAMPLE_RATE}"}}}))
        except WebSocketException as exc:
            raise RealtimeUnavailable("provider closed") from exc

    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None:
        await self._send({"toolResponse": {"functionResponses": [
            {"id": call_id, "name": name, "response": response}]}})

    async def send_text(self, text: str) -> None:
        await self._send({"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}],
                                            "turnComplete": True}})

    async def send_context(self, text: str) -> None:
        # turnComplete false: the text joins the context and the model answers only the learner's next turn.
        await self._send({"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}],
                                            "turnComplete": False}})

    async def _send(self, message: dict) -> None:
        try:
            await self.ws.send(json.dumps(message))
        except WebSocketException as exc:
            raise RealtimeUnavailable("provider closed") from exc

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        try:
            async for raw in self.ws:
                for event in parse_server_message(json.loads(raw)):
                    yield event
        except WebSocketException as exc:
            raise RealtimeUnavailable("provider closed") from exc

    async def close(self) -> None:
        try:
            await self.ws.close()
        except Exception:
            pass


class GeminiLiveVoice:
    def __init__(self, *, project: str, region: str, model: str,
                 token_provider: Callable[[str], str] = adc_token):
        self.project = project
        self.region = region
        self.model_name = model
        self.token_provider = token_provider

    def _url(self) -> str:
        host = "aiplatform.googleapis.com" if self.region == "global" else f"{self.region}-aiplatform.googleapis.com"
        return f"wss://{host}/ws/google.cloud.aiplatform.v1.LlmBidiService/BidiGenerateContent"

    async def open(self, *, language_code: str, instruction: str, silence_ms: int,
                   resume_handle: str | None = None) -> GeminiLiveConnection:
        try:
            token = await asyncio.to_thread(self.token_provider, self.project)
            ws = await connect(self._url(), additional_headers={"Authorization": f"Bearer {token}"},
                               max_size=None, open_timeout=SETUP_TIMEOUT_S)
            await ws.send(json.dumps({"setup": {
                "model": f"projects/{self.project}/locations/{self.region}/publishers/google/models/{self.model_name}",
                "generationConfig": {"responseModalities": ["AUDIO"]},
                "systemInstruction": {"parts": [{"text": instruction}]},
                "inputAudioTranscription": {}, "outputAudioTranscription": {},
                "realtimeInputConfig": {"automaticActivityDetection": {"silenceDurationMs": silence_ms}},
                "contextWindowCompression": {"triggerTokens": CONTEXT_TRIGGER_TOKENS,
                                             "slidingWindow": {"targetTokens": CONTEXT_TARGET_TOKENS}},
                "tools": TOOLS,
                # The provider sends handles that continue this session on a new connection (goAway, a fault).
                "sessionResumption": {"handle": resume_handle} if resume_handle else {},
            }}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), SETUP_TIMEOUT_S))
        except (OSError, WebSocketException, asyncio.TimeoutError, ValueError) as exc:
            raise RealtimeUnavailable("provider setup failed") from exc
        if "setupComplete" not in reply:
            await ws.close()
            raise RealtimeUnavailable("provider setup refused")
        connection = GeminiLiveConnection(ws)
        if resume_handle:
            return connection  # the session goes on where it was: no new greeting
        # The companion speaks first, as in the turn-based mode.
        await ws.send(json.dumps({"clientContent": {"turns": [{"role": "user", "parts": [{"text": JOINED_CUE}]}],
                                                    "turnComplete": True}}))
        return connection
