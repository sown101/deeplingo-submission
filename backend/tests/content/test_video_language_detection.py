import pytest
import youtube_transcript_api
from youtube_transcript_api._errors import NoTranscriptFound

from app.modules.content.application.ports import SourceProviderError
from app.modules.content.infrastructure import youtube as youtube_module
from app.modules.content.infrastructure.youtube import YouTubeService


VIDEO_ID = "MYQrQvbR8Vk"
ZH_TEXT = [{"text": "大家好！欢迎收听新一期的《每天中文》。我是李明。"}]
KO_TEXT = [{"text": "안녕하세요 여러분! Everyday Chinese의 새 에피소드에 오신 것을 환영합니다."}]


class _Fetched:
    def __init__(self, raw):
        self._raw = raw

    def to_raw_data(self):
        return self._raw


class FakeTranscriptApi:
    """Scripted fetch outcomes per track: a list of raw data or exceptions, consumed in order."""

    def __init__(self, script):
        self.script = {code: list(outcomes) for code, outcomes in script.items()}
        self.calls = []

    def __call__(self):
        return self

    def fetch(self, video_id, languages):
        code = languages[0]
        self.calls.append(code)
        outcome = self.script[code].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Fetched(outcome)


def _manual_tracks(*codes):
    return [
        {"language": code, "language_code": code, "is_generated": False, "is_translatable": True}
        for code in codes
    ]


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(youtube_module.time, "sleep", lambda seconds: None)
    svc = YouTubeService()
    monkeypatch.setattr(svc, "list_available_transcripts", lambda video_id: _manual_tracks("zh", "en", "ko"))
    return svc


def _install(monkeypatch, api):
    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", api)


def test_transient_failure_on_original_track_is_retried_not_skipped(service, monkeypatch):
    api = FakeTranscriptApi({"zh": [RuntimeError("502 Bad Gateway"), ZH_TEXT], "ko": [KO_TEXT]})
    _install(monkeypatch, api)

    assert service.detect_video_language(VIDEO_ID) == "zh"
    assert api.calls == ["zh", "zh"]


def test_persistent_failure_fails_closed_instead_of_using_translated_track(service, monkeypatch):
    api = FakeTranscriptApi({"zh": [RuntimeError("502")] * 3, "ko": [KO_TEXT]})
    _install(monkeypatch, api)

    with pytest.raises(SourceProviderError):
        service.detect_video_language(VIDEO_ID)
    assert "ko" not in api.calls
    assert api.calls == ["zh"] * YouTubeService._DETECTION_FETCH_ATTEMPTS


def test_track_without_transcript_is_skipped(service, monkeypatch):
    api = FakeTranscriptApi({
        "zh": [NoTranscriptFound(VIDEO_ID, ["zh"], None)],
        "ko": [NoTranscriptFound(VIDEO_ID, ["ko"], None)],
        "en": [[{"text": "Hello everyone and welcome back to the show"}]],
    })
    _install(monkeypatch, api)

    assert service.detect_video_language(VIDEO_ID) == "en"
    assert api.calls == ["zh", "ko", "en"]
