"""Gemini YouTube-URL transcription source: adapter, bounds, failures, config, wiring."""
import json

import httpx
import pytest
from pydantic import ValidationError

from app.modules.content.application.ingestion import ContentIngestionError, ContentIngestionService
from app.modules.content.application.ports import (
    ContentProviderFailure,
    SourceProviderError,
    SourceVideoUnavailable,
    UnsupportedSourceContent,
)
from app.modules.content.application.prompts import YOUTUBE_TRANSCRIPTION_PROMPT_VERSION
from app.modules.content.domain.failures import ContentFailureClass as C
from app.modules.content.domain.library import ContentProcessingFailureCode
from app.modules.content.domain.normalizer import TranscriptNormalizer
from app.modules.content.infrastructure.gemini_transcription import (
    GeminiYouTubeContentProvider,
    GeminiYouTubeTranscriber,
    parse_clock,
)
from app.modules.content.infrastructure.youtube_data_api import (
    YouTubeDataApiClient,
    YouTubeVideoInfo,
    parse_iso8601_duration,
)
from app.modules.content.worker.failure_classification import classify_content_failure
from app.platform.config import Settings
from tests.content.test_content_ingestion import (
    FakeChannels,
    FakeLanguages,
    FakeRomanizationProvider,
    FakeRomanizations,
    FakeRomanizationSystems,
    FakeSegments,
    FakeTranscripts,
    FakeTranslations,
    FakeVideos,
)

SECRET = "test-secret-key-never-in-urls"
CATALOG = ["en", "vi", "zh", "ja", "ko"]


# ---------------------------------------------------------------- helpers


def gemini_reply(segments, *, language="en", finish="STOP", version="gemini-3.6-flash"):
    body = {"language": language, "segments": segments}
    return httpx.Response(200, json={
        "candidates": [{"finishReason": finish, "content": {"parts": [{"text": json.dumps(body)}]}}],
        "modelVersion": version,
    })


class GeminiStub:
    """MockTransport handler that records requests and answers per clip start offset."""

    def __init__(self, answer):
        self.answer = answer
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        start = int(body["contents"][0]["parts"][0]["video_metadata"]["start_offset"].rstrip("s"))
        return self.answer(start, len([r for r in self.requests if _start(r) == start]))


def _start(request: httpx.Request) -> int:
    return int(json.loads(request.content)["contents"][0]["parts"][0]["video_metadata"]["start_offset"].rstrip("s"))


def transcriber(handler, **kwargs) -> GeminiYouTubeTranscriber:
    return GeminiYouTubeTranscriber(
        api_key=SECRET, model="gemini-3.6-flash", catalog_languages=lambda: CATALOG,
        transport=httpx.MockTransport(handler), **kwargs,
    )


def info(**overrides) -> YouTubeVideoInfo:
    values = dict(video_id="vid", title="Title", description=None, channel_id="UC1", channel_title="Chan",
                  thumbnail_url=None, published_at=None, duration_seconds=130, privacy_status="public",
                  live_broadcast_content="none", default_audio_language=None)
    values.update(overrides)
    return YouTubeVideoInfo(**values)


class FakeDataApi:
    def __init__(self, video: YouTubeVideoInfo | Exception):
        self.video = video
        self.calls = 0

    def get_video(self, video_id):
        self.calls += 1
        if isinstance(self.video, Exception):
            raise self.video
        return self.video


class FakeTranscriber:
    model = "gemini-3.6-flash"
    clip_seconds = 60
    thinking_level = None

    def __init__(self, result):
        self.result = result

    def transcribe(self, video_id, duration_seconds):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def provider(video=None, result=None, *, allowed=("en",), max_seconds=900) -> GeminiYouTubeContentProvider:
    return GeminiYouTubeContentProvider(
        data_api=FakeDataApi(video or info()), transcriber=FakeTranscriber(result),
        allowed_languages=allowed, max_duration_seconds=max_seconds,
    )


# ---------------------------------------------------------------- parsing


@pytest.mark.parametrize("value,expected", [
    ("PT14M2S", 842), ("PT1H", 3600), ("PT45S", 45), ("P1DT1S", 86401), ("P0D", 0), ("", None), (None, None), ("PT1.5S", None),
])
def test_iso8601_duration(value, expected):
    assert parse_iso8601_duration(value) == expected


@pytest.mark.parametrize("value,expected", [("00:05.5", 5.5), ("1:02", 62.0), ("1:00:01", 3601.0), ("7.25", 7.25)])
def test_clock_parsing(value, expected):
    assert parse_clock(value) == expected


@pytest.mark.parametrize("value", ["", "a:b", "1:2:3:4", "-1:00"])
def test_clock_parsing_rejects_garbage(value):
    with pytest.raises(ValueError):
        parse_clock(value)


# ---------------------------------------------------------------- YouTube Data API


def data_api(handler) -> YouTubeDataApiClient:
    return YouTubeDataApiClient(SECRET, transport=httpx.MockTransport(handler))


def test_data_api_parses_video_and_keeps_key_out_of_url():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [{
            "snippet": {"title": "T", "channelId": "UC1", "channelTitle": "C", "defaultAudioLanguage": "en-GB",
                        "liveBroadcastContent": "none", "thumbnails": {"high": {"url": "https://i/h.jpg"}}},
            "contentDetails": {"duration": "PT6M8S"}, "status": {"privacyStatus": "public"},
        }]})

    video = data_api(handler).get_video("abc")
    assert (video.duration_seconds, video.privacy_status, video.default_audio_language) == (368, "public", "en-GB")
    assert video.thumbnail_url == "https://i/h.jpg"
    assert SECRET not in str(seen[0].url) and seen[0].headers["x-goog-api-key"] == SECRET
    assert seen[0].url.params["id"] == "abc"


def test_data_api_missing_video_is_unavailable():
    with pytest.raises(SourceVideoUnavailable):
        data_api(lambda r: httpx.Response(200, json={"items": []})).get_video("abc")


@pytest.mark.parametrize("response,code,transient", [
    (httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}}), "provider_rate_limit", True),
    (httpx.Response(429), "provider_rate_limit", True),
    (httpx.Response(503), "provider_temporary", True),
    (httpx.Response(400, json={"error": {"errors": [{"reason": "keyInvalid"}]}}), "configuration_error", False),
])
def test_data_api_status_failures_are_typed(response, code, transient):
    with pytest.raises(ContentProviderFailure) as raised:
        data_api(lambda r: response).get_video("abc")
    assert (raised.value.code, raised.value.transient) == (code, transient)


def test_data_api_timeout_is_transient():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ContentProviderFailure) as raised:
        data_api(handler).get_video("abc")
    assert raised.value.code == "transient_timeout" and raised.value.transient


# ---------------------------------------------------------------- transcriber


def test_clips_are_offset_ordered_and_versioned():
    stub = GeminiStub(lambda start, n: gemini_reply([{"start": "00:01.0", "end": "00:04.5", "text": f"clip {start}"}]))
    result = transcriber(stub).transcribe("vid", 130)

    assert sorted(_start(r) for r in stub.requests) == [0, 60, 120]
    last_clip = next(json.loads(r.content) for r in stub.requests if _start(r) == 120)
    assert last_clip["contents"][0]["parts"][0]["video_metadata"]["end_offset"] == "130s"
    assert [(s.start, s.end, s.text) for s in result.segments] == [
        (1.0, 4.5, "clip 0"), (61.0, 64.5, "clip 60"), (121.0, 124.5, "clip 120")]
    assert result.language == "en" and result.model_versions == ("gemini-3.6-flash",)
    for request in stub.requests:
        assert SECRET not in str(request.url) and request.headers["x-goog-api-key"] == SECRET
        schema = json.loads(request.content)["generationConfig"]["responseSchema"]
        assert schema["properties"]["language"]["enum"] == sorted(CATALOG)


def test_transient_clip_failure_is_retried_once():
    stub = GeminiStub(lambda start, n: httpx.Response(503) if (start, n) == (60, 1)
                      else gemini_reply([{"start": "0:01", "end": "0:02", "text": "ok"}]))
    result = transcriber(stub).transcribe("vid", 130)
    assert len(result.segments) == 3 and len(stub.requests) == 4


def test_clip_failing_twice_fails_the_whole_transcript():
    stub = GeminiStub(lambda start, n: gemini_reply([], finish="MAX_TOKENS") if start == 60
                      else gemini_reply([{"start": "0:01", "end": "0:02", "text": "ok"}]))
    with pytest.raises(ContentProviderFailure) as raised:
        transcriber(stub).transcribe("vid", 130)
    assert (raised.value.code, raised.value.transient) == ("provider_temporary", True)
    assert len([r for r in stub.requests if _start(r) == 60]) == 2


def test_request_errors_are_not_retried():
    stub = GeminiStub(lambda start, n: httpx.Response(400, json={"error": {"message": "secret detail"}}))
    with pytest.raises(ContentProviderFailure) as raised:
        transcriber(stub).transcribe("vid", 30)
    assert (raised.value.code, raised.value.transient) == ("configuration_error", False)
    assert len(stub.requests) == 1 and "secret detail" not in str(raised.value)


def test_rate_limit_is_typed_transient():
    with pytest.raises(ContentProviderFailure) as raised:
        transcriber(GeminiStub(lambda s, n: httpx.Response(429))).transcribe("vid", 30)
    assert raised.value.code == "provider_rate_limit"


@pytest.mark.parametrize("segment", [
    {"start": "00:05", "end": "00:01", "text": "reversed"},
    {"start": "00:01", "end": "01:10", "text": "past the clip end"},
    {"start": "00:01", "end": "00:02", "text": "   "},
    {"start": "soon", "end": "00:02", "text": "bad clock"},
])
def test_invalid_segments_fail_closed(segment):
    with pytest.raises(ContentProviderFailure) as raised:
        transcriber(GeminiStub(lambda s, n: gemini_reply([segment]))).transcribe("vid", 60)
    assert raised.value.code == "provider_temporary"


def test_language_outside_catalog_and_extra_fields_fail_closed():
    with pytest.raises(ContentProviderFailure):
        transcriber(GeminiStub(lambda s, n: gemini_reply([], language="xx"))).transcribe("vid", 30)

    def extra(start, n):
        body = {"language": "en", "segments": [], "notes": "injected"}
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(body)}]}}]})

    with pytest.raises(ContentProviderFailure):
        transcriber(GeminiStub(extra)).transcribe("vid", 30)


def test_zero_length_segment_gets_minimum_duration():
    result = transcriber(GeminiStub(lambda s, n: gemini_reply([{"start": "0:03", "end": "0:03", "text": "hi"}]))).transcribe("vid", 30)
    assert result.segments[0].end - result.segments[0].start == pytest.approx(0.1)


def test_silent_clips_do_not_vote_on_language():
    stub = GeminiStub(lambda start, n: gemini_reply([], language="ja") if start == 0
                      else gemini_reply([{"start": "0:01", "end": "0:02", "text": "speech"}], language="en"))
    assert transcriber(stub).transcribe("vid", 130).language == "en"


def test_deadline_fails_transiently():
    ticks = iter([0.0] + [10_000.0] * 50)
    with pytest.raises(ContentProviderFailure) as raised:
        transcriber(GeminiStub(lambda s, n: gemini_reply([])), clock=lambda: next(ticks)).transcribe("vid", 130)
    assert raised.value.code == "transient_timeout"


def test_empty_catalog_is_a_configuration_error():
    bad = GeminiYouTubeTranscriber(api_key=SECRET, model="m", catalog_languages=lambda: [],
                                   transport=httpx.MockTransport(lambda r: gemini_reply([])))
    with pytest.raises(ContentProviderFailure) as raised:
        bad.transcribe("vid", 30)
    assert raised.value.code == "configuration_error"


# ---------------------------------------------------------------- provider bounds


@pytest.mark.parametrize("video", [
    info(privacy_status="unlisted"), info(live_broadcast_content="live"), info(duration_seconds=None), info(duration_seconds=0),
    info(duration_seconds=901), info(default_audio_language="ja"),
])
def test_metadata_rejects_unsupported_videos(video):
    with pytest.raises(UnsupportedSourceContent):
        provider(video).get_video_metadata("https://www.youtube.com/watch?v=vid00000000")


def test_metadata_uses_data_api_without_youtube_pages():
    metadata = provider(info(default_audio_language="en-GB", duration_seconds=900)).get_video_metadata(
        "https://youtu.be/vid00000000")
    assert (metadata.external_video_id, metadata.duration_ms, metadata.original_language_code) == ("vid00000000", 900_000, "en")
    assert metadata.metadata["provider"] == "youtube_data_api"


def test_undeclared_language_is_provisional_with_one_enabled_language():
    assert provider(info()).get_video_metadata("https://youtu.be/vid00000000").original_language_code == "en"


class DetectingTranscriber(FakeTranscriber):
    def __init__(self, detected):
        super().__init__(None)
        self.detected, self.detect_calls = detected, []

    def detect_language(self, video_id, duration_seconds):
        self.detect_calls.append((video_id, duration_seconds))
        return self.detected


def detecting_provider(detected, video=None):
    transcriber_ = DetectingTranscriber(detected)
    return GeminiYouTubeContentProvider(data_api=FakeDataApi(video or info()), transcriber=transcriber_,
                                        allowed_languages=("en", "zh"), max_duration_seconds=900), transcriber_


def test_undeclared_language_is_detected_when_several_languages_are_enabled():
    source, transcriber_ = detecting_provider("zh")
    assert source.get_video_metadata("https://youtu.be/vid00000000").original_language_code == "zh"
    assert transcriber_.detect_calls == [("vid", 130)]


def test_declared_language_skips_detection():
    source, transcriber_ = detecting_provider("en", info(default_audio_language="zh-Hans"))
    assert source.get_video_metadata("https://youtu.be/vid00000000").original_language_code == "zh"
    assert transcriber_.detect_calls == []


@pytest.mark.parametrize("detected", [None, "ja"])
def test_undetected_or_disabled_spoken_language_is_unsupported(detected):
    source, _ = detecting_provider(detected)
    with pytest.raises(UnsupportedSourceContent):
        source.get_video_metadata("https://youtu.be/vid00000000")


def test_language_detection_uses_the_first_clip_with_speech_and_stops():
    stub = GeminiStub(lambda start, n: gemini_reply([], language="en") if start == 0
                      else gemini_reply([{"start": "0:01", "end": "0:02", "text": "你好"}], language="zh"))
    assert transcriber(stub).detect_language("vid", 600) == "zh"
    assert sorted({_start(request) for request in stub.requests}) == [0, 60]


def test_language_detection_of_silent_opening_returns_none():
    stub = GeminiStub(lambda start, n: gemini_reply([]))
    assert transcriber(stub).detect_language("vid", 600) is None
    assert sorted({_start(request) for request in stub.requests}) == [0, 60, 120]


def transcription(language="en", segments=None):
    from app.modules.content.infrastructure.gemini_transcription import TranscribedSegment, Transcription
    return Transcription(language=language, model_versions=("gemini-3.6-flash",),
                         segments=segments if segments is not None else [TranscribedSegment(1.0, 2.5, "Hello there.")],
                         usage={"requests": 1, "prompt_tokens": 900, "output_tokens": 120, "thinking_tokens": 200})


def test_transcript_track_records_ai_provenance():
    track = provider(result=transcription()).get_original_transcript("vid", "en")
    assert (track.source, track.is_original, track.language_code) == ("ai", True, "en")
    assert track.provider_metadata == {
        "method": "gemini_youtube_url", "model_requested": "gemini-3.6-flash", "model_versions": ["gemini-3.6-flash"],
        "prompt_version": YOUTUBE_TRANSCRIPTION_PROMPT_VERSION, "clip_seconds": 60, "thinking_level": None,
        "detected_language": "en",
        "usage": {"requests": 1, "prompt_tokens": 900, "output_tokens": 120, "thinking_tokens": 200},
    }
    assert [(s.sequence_number, s.start_seconds, s.duration_seconds) for s in track.segments] == [(1, 1.0, 1.5)]
    assert provider(result=transcription()).get_translated_transcript("vid", "vi") is None


@pytest.mark.parametrize("result,language", [
    (transcription(language="ja"), "en"),       # spoken language mismatch
    (transcription(segments=[]), "en"),          # no speech
    (transcription(), "zh"),                     # language not enabled
])
def test_transcript_stage_rejects_unsupported(result, language):
    with pytest.raises(UnsupportedSourceContent):
        provider(result=result).get_original_transcript("vid", language)


def test_transcript_stage_rechecks_bounds():
    late = provider(info(duration_seconds=1200), result=transcription())
    with pytest.raises(UnsupportedSourceContent):
        late.get_original_transcript("vid", "en")


# ---------------------------------------------------------------- ingestion + failure policy


def ingestion(source_provider):
    return ContentIngestionService(
        video_provider=source_provider, transcript_provider=source_provider,
        romanization_provider=FakeRomanizationProvider(), normalizer=TranscriptNormalizer(),
        languages=FakeLanguages(), channels=FakeChannels(), videos=FakeVideos(), transcripts=FakeTranscripts(),
        segments=FakeSegments(), translations=FakeTranslations(), romanization_systems=FakeRomanizationSystems(),
        romanizations=FakeRomanizations(),
    )


def test_ai_transcript_is_persisted_as_source_ai():
    service = ingestion(provider(result=transcription()))
    result = service.ingest_video("https://youtu.be/vid00000000", target_language="zh")
    assert result.transcript.source == "ai" and [s.text for s in result.segments] == ["Hello there."]
    assert result.translation_count == 0 and result.video.processing_status == "transcript_ready"


def test_unsupported_video_is_rejected_before_any_transcription():
    service = ingestion(provider(info(duration_seconds=4000)))
    with pytest.raises(ContentIngestionError) as raised:
        service.prepare_video("https://youtu.be/vid00000000")
    assert (raised.value.code, raised.value.retryable, raised.value.status_code) == (
        ContentProcessingFailureCode.UNSUPPORTED_CONTENT, False, 422)


def test_provider_failure_is_retryable_not_content_unavailable():
    service = ingestion(provider(result=ContentProviderFailure("provider_rate_limit", transient=True)))
    with pytest.raises(ContentIngestionError) as raised:
        service.ingest_video("https://youtu.be/vid00000000")
    assert raised.value.code == ContentProcessingFailureCode.PROCESSING_FAILED and raised.value.retryable
    failure = classify_content_failure(raised.value)
    assert (failure.category, failure.code) == (C.TRANSIENT, "provider_rate_limit")


def test_language_mismatch_is_permanent_unsupported():
    service = ingestion(provider(result=transcription(language="ja")))
    with pytest.raises(ContentIngestionError) as raised:
        service.ingest_video("https://youtu.be/vid00000000")
    assert raised.value.code == ContentProcessingFailureCode.UNSUPPORTED_CONTENT and not raised.value.retryable
    assert classify_content_failure(raised.value).category == C.PERMANENT


@pytest.mark.parametrize("failure,category", [
    (ContentProviderFailure("transient_timeout", transient=True), C.TRANSIENT),
    (ContentProviderFailure("configuration_error", transient=False), C.PERMANENT),
])
def test_typed_provider_failures_classify_by_their_own_code(failure, category):
    result = classify_content_failure(failure)
    assert (result.category, result.code) == (category, failure.code)


def test_caption_marker_mapping_is_unchanged():
    from app.modules.content.application.ingestion import _provider_error
    mapped = _provider_error(SourceProviderError("Lỗi khi lấy transcript: blocked"), transcript_stage=True)
    assert mapped.code == ContentProcessingFailureCode.TRANSCRIPT_UNAVAILABLE and not mapped.retryable


# ---------------------------------------------------------------- configuration and wiring

GEMINI = dict(CONTENT_TRANSCRIPT_SOURCE="gemini_youtube", GEMINI_API_KEY="g", AI_TRANSCRIPTION_MODEL="gemini-3.6-flash",
              YOUTUBE_DATA_API_KEY="y")


def settings(**values):
    return Settings(_env_file=None, ENVIRONMENT="development", **values)


def test_caption_source_remains_the_default():
    assert settings().CONTENT_TRANSCRIPT_SOURCE == "caption_track"
    assert settings(**GEMINI).content_transcription_language_list == ["en"]


@pytest.mark.parametrize("missing", ["GEMINI_API_KEY", "AI_TRANSCRIPTION_MODEL", "YOUTUBE_DATA_API_KEY"])
def test_gemini_source_requires_complete_configuration(missing):
    with pytest.raises(ValidationError):
        settings(**{**GEMINI, missing: ""})


def test_gemini_source_is_limited_to_qualified_languages_and_development():
    assert settings(**GEMINI, CONTENT_TRANSCRIPTION_LANGUAGES="en,zh").content_transcription_language_list == ["en", "zh"]
    assert settings(**GEMINI, CONTENT_TRANSCRIPTION_LANGUAGES="zh").content_transcription_language_list == ["zh"]
    for unqualified in ("en,ja", "ko", ""):
        with pytest.raises(ValidationError):
            settings(**GEMINI, CONTENT_TRANSCRIPTION_LANGUAGES=unqualified)
    # Amendments 2026-10-20/21 (M2): 20 minutes by default, configurable up to 60 for the benchmark.
    assert settings(**GEMINI).CONTENT_MAX_VIDEO_SECONDS == 1200
    assert settings(**GEMINI, CONTENT_MAX_VIDEO_SECONDS=900).CONTENT_MAX_VIDEO_SECONDS == 900  # live pin until C-dev
    assert settings(**GEMINI, CONTENT_MAX_VIDEO_SECONDS=3600).CONTENT_MAX_VIDEO_SECONDS == 3600
    with pytest.raises(ValidationError):
        settings(**GEMINI, CONTENT_MAX_VIDEO_SECONDS=3601)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENVIRONMENT="staging", AI_PROVIDER="gemini", AI_PROVIDER_DEPLOYMENT_CLASS="production_eligible",
                 AI_API_KEY="k", AI_BASE_URL="https://x.test/v1", AI_MODEL_NAME="m", **GEMINI)


def test_wiring_selects_exactly_the_configured_source(monkeypatch):
    from app.bootstrap.wiring import content as wiring
    from app.modules.content.infrastructure.sources import YouTubeContentProvider

    class Languages:
        def list_active(self):
            raise AssertionError("catalog must load lazily, not while wiring")

    monkeypatch.setattr(wiring, "settings", settings())
    assert isinstance(wiring._content_source_provider(Languages()), YouTubeContentProvider)
    monkeypatch.setattr(wiring, "settings", settings(**GEMINI))
    selected = wiring._content_source_provider(Languages())
    assert isinstance(selected, GeminiYouTubeContentProvider)
    assert selected.transcriber.model == "gemini-3.6-flash" and selected.max_duration_seconds == 1200


# ---------------------------------------------------------------- billed usage and thinking


def usage_reply(segments, *, prompt=1000, output=100, thoughts=300, finish="STOP"):
    reply = gemini_reply(segments, finish=finish)
    body = reply.json()
    body["usageMetadata"] = {"promptTokenCount": prompt, "candidatesTokenCount": output, "thoughtsTokenCount": thoughts}
    return httpx.Response(200, json=body)


def test_usage_counts_every_billed_attempt_including_rejected_ones(caplog):
    stub = GeminiStub(lambda start, n: usage_reply([], finish="MAX_TOKENS") if (start, n) == (60, 1)
                      else usage_reply([{"start": "0:01", "end": "0:02", "text": "ok"}]))
    with caplog.at_level("INFO"):
        result = transcriber(stub).transcribe("vid", 130)
    # 3 clips + 1 rejected first attempt, all billed.
    assert result.usage == {"requests": 4, "prompt_tokens": 4000, "output_tokens": 400, "thinking_tokens": 1200}
    assert any("gemini_transcription_usage" in r.getMessage() and "thinking_tokens=1200" in r.getMessage()
               for r in caplog.records)
    assert not any(SECRET in r.getMessage() for r in caplog.records)


def test_usage_is_logged_when_transcription_fails(caplog):
    stub = GeminiStub(lambda start, n: usage_reply([], finish="MAX_TOKENS"))
    with caplog.at_level("INFO"), pytest.raises(ContentProviderFailure):
        transcriber(stub).transcribe("vid", 30)
    assert any("gemini_transcription_usage" in r.getMessage() and "requests=2" in r.getMessage()
               for r in caplog.records)


def test_thinking_config_is_sent_only_when_configured():
    plain = GeminiStub(lambda s, n: gemini_reply([]))
    transcriber(plain).transcribe("vid", 30)
    assert "thinkingConfig" not in json.loads(plain.requests[0].content)["generationConfig"]

    tuned = GeminiStub(lambda s, n: gemini_reply([]))
    transcriber(tuned, thinking_level="low").transcribe("vid", 30)
    assert json.loads(tuned.requests[0].content)["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_thinking_level_setting_defaults_to_model_default():
    assert settings().AI_TRANSCRIPTION_THINKING_LEVEL == ""
    with pytest.raises(ValidationError):
        settings(AI_TRANSCRIPTION_THINKING_LEVEL="extreme")
