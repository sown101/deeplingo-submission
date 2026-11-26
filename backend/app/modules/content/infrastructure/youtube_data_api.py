"""Official YouTube Data API v3 metadata reader: duration, visibility and audio language.

The key travels in a header, never the URL, because HTTP client logs record request URLs.
"""
import re
from dataclasses import dataclass

import httpx

from app.modules.content.application.ports import ContentProviderFailure, SourceVideoUnavailable

VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_QUOTA_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded"}


@dataclass(frozen=True)
class YouTubeVideoInfo:
    video_id: str
    title: str
    description: str | None
    channel_id: str | None
    channel_title: str | None
    thumbnail_url: str | None
    published_at: str | None
    duration_seconds: int | None
    privacy_status: str | None
    live_broadcast_content: str | None
    default_audio_language: str | None


def parse_iso8601_duration(value: str | None) -> int | None:
    """Return whole seconds, or None when absent or not a plain ISO 8601 duration."""
    match = _ISO_DURATION.fullmatch(value or "")
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


class YouTubeDataApiClient:
    def __init__(self, api_key: str, *, timeout_seconds: float = 10.0, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise ValueError("YouTube Data API key is required")
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def get_video(self, video_id: str) -> YouTubeVideoInfo:
        try:
            response = self._client.get(
                VIDEOS_ENDPOINT,
                params={"part": "snippet,contentDetails,status", "id": video_id},
                headers={"x-goog-api-key": self._api_key},
            )
        except httpx.TimeoutException as exc:
            raise ContentProviderFailure("transient_timeout", transient=True) from exc
        except httpx.TransportError as exc:
            raise ContentProviderFailure("transient_network", transient=True) from exc
        if response.status_code != 200:
            raise _status_failure(response)
        try:
            items = response.json().get("items") or []
        except ValueError as exc:
            raise ContentProviderFailure("provider_temporary", transient=True) from exc
        if not items:
            raise SourceVideoUnavailable("YouTube video is unavailable")
        item = items[0]
        snippet, details, status = item.get("snippet") or {}, item.get("contentDetails") or {}, item.get("status") or {}
        thumbnails = snippet.get("thumbnails") or {}
        thumbnail = next((thumbnails[size]["url"] for size in ("high", "medium", "default")
                          if isinstance(thumbnails.get(size), dict) and thumbnails[size].get("url")), None)
        return YouTubeVideoInfo(
            video_id=video_id,
            title=snippet.get("title") or "Unknown Title",
            description=snippet.get("description") or None,
            channel_id=snippet.get("channelId"),
            channel_title=snippet.get("channelTitle"),
            thumbnail_url=thumbnail,
            published_at=snippet.get("publishedAt"),
            duration_seconds=parse_iso8601_duration(details.get("duration")),
            privacy_status=status.get("privacyStatus"),
            live_broadcast_content=snippet.get("liveBroadcastContent"),
            default_audio_language=snippet.get("defaultAudioLanguage"),
        )


def _status_failure(response: httpx.Response) -> ContentProviderFailure:
    status = response.status_code
    reasons: set[str] = set()
    try:
        reasons = {str(error.get("reason")) for error in response.json().get("error", {}).get("errors", [])}
    except (ValueError, AttributeError):
        pass
    if status == 429 or (status == 403 and reasons & _QUOTA_REASONS):
        return ContentProviderFailure("provider_rate_limit", transient=True)
    if status >= 500:
        return ContentProviderFailure("provider_temporary", transient=True)
    return ContentProviderFailure("configuration_error", transient=False)
