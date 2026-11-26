import base64
import json
import logging

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from app.modules.learning.application.speaking_ports import (
    NoSpeechDetected,
    SpeechProviderFailure,
)
from app.modules.learning.application.speech_transcription import SpeechTranscriber
from app.modules.learning.domain.speaking import (
    FeedbackBand,
    HintMatcher,
    PronunciationErrorType,
    contains_form,
    feedback_band,
    is_grounded_quote,
    spoken_unit_count,
    used_hint_ids,
)
from app.modules.learning.domain.speech_audio import SpeechAudio, SpeechAudioError, parse_wav, voice_activity
from app.platform.llm import openai_compatible as providers_module
from app.platform.llm.port import LLMProviderError
from app.platform.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.modules.learning.infrastructure.speech.azure_pronunciation import (
    AzurePronunciationAssessor,
)
from tests.learning.speaking_fixtures import pcm_silence, pcm_tone, speech_like_wav, wav_bytes

SECRET = b"s" * 32


# --- WAV parsing and voice activity -------------------------------------------

def test_parse_wav_accepts_canonical_pcm_and_round_trips():
    audio = parse_wav(speech_like_wav(1500), max_duration_ms=5000)
    assert audio.duration_ms == 1500
    assert parse_wav(audio.to_wav(), max_duration_ms=5000).pcm == audio.pcm


@pytest.mark.parametrize("kwargs", [
    {"rate": 44_100}, {"channels": 2}, {"bits": 8}, {"audio_format": 3},
])
def test_parse_wav_rejects_non_canonical_formats(kwargs):
    with pytest.raises(SpeechAudioError) as raised:
        parse_wav(wav_bytes(pcm_tone(1000), **kwargs), max_duration_ms=5000)
    assert raised.value.code == "audio_format_unsupported"


def test_parse_wav_rejects_non_wav_and_duration_bounds():
    with pytest.raises(SpeechAudioError):
        parse_wav(b"not audio at all", max_duration_ms=5000)
    with pytest.raises(SpeechAudioError) as short:
        parse_wav(speech_like_wav(100), max_duration_ms=5000)
    assert short.value.code == "audio_too_short"
    with pytest.raises(SpeechAudioError) as long:
        parse_wav(speech_like_wav(6000), max_duration_ms=5000)
    assert long.value.code == "audio_too_long"


def test_parse_wav_skips_extra_chunks_and_open_ended_data_size():
    extra = b"LIST" + (4).to_bytes(4, "little") + b"INFO"
    audio = parse_wav(wav_bytes(pcm_tone(1000), extra_chunk=extra, declared_data_size=0xFFFFFFFF),
                      max_duration_ms=5000)
    assert audio.duration_ms == 1000


def test_voice_activity_detects_silence_speech_and_long_pauses():
    assert not voice_activity(SpeechAudio(pcm_silence(2000))).has_speech
    activity = voice_activity(SpeechAudio(pcm_tone(1000) + pcm_silence(2500) + pcm_tone(1000)))
    assert activity.has_speech
    assert activity.long_pause_count == 1
    assert 2400 <= activity.longest_pause_ms <= 2600
    assert 4300 <= activity.span_ms <= 4600


# --- Deterministic speaking policies -------------------------------------------

@pytest.mark.parametrize("score,band", [
    (95, FeedbackBand.EXCELLENT), (90, FeedbackBand.EXCELLENT), (80, FeedbackBand.GOOD),
    (60, FeedbackBand.FAIR), (40, FeedbackBand.RETRY),
])
def test_feedback_band_thresholds(score, band):
    assert feedback_band(score) == band


def test_whole_word_matching_for_spaced_languages_and_substring_for_unspaced():
    assert contains_form("I really enjoy autumn.", "enjoy", "en")
    assert not contains_form("I enjoyed it.", "enjoy", "en")
    assert contains_form("It was A BIT cold", "a bit", "en")
    assert contains_form("私は秋が好きです", "秋", "ja")


def test_hint_usage_is_deterministic():
    hints = [HintMatcher("h1", forms=("prefer",)), HintMatcher("h2", forms=("usually",))]
    text = "My favourite season is autumn and I usually walk"
    assert used_hint_ids(text, hints, "en") == ["h2"]


def test_metrics_helpers():
    assert spoken_unit_count("I love autumn.", "en") == 3
    assert spoken_unit_count("我喜欢秋天", "zh") == 5


def test_grounded_quote_requires_exact_transcript_span():
    transcript = "Before the leaf fall of the tree they turns into"
    assert is_grounded_quote("they  TURNS into", transcript)
    assert not is_grounded_quote("they turn into", transcript)
    assert not is_grounded_quote("...", transcript)


# --- Azure pronunciation adapter -----------------------------------------------

def azure_payload(**overrides):
    payload = {
        "RecognitionStatus": "Success",
        "DisplayText": "Before the leaves fall.",
        "NBest": [{
            "Display": "Before the leaves fall.", "AccuracyScore": 75.0, "FluencyScore": 95.0,
            "CompletenessScore": 79.0, "PronScore": 82.3, "ProsodyScore": 87.4,
            "Words": [
                {"Word": "before", "AccuracyScore": 97.0, "ErrorType": "None", "Offset": 800000,
                 "Duration": 4300000, "Phonemes": [{"Phoneme": "b", "AccuracyScore": 81.0}]},
                {"Word": "leaves", "AccuracyScore": 40.0, "ErrorType": "Mispronunciation",
                 "Offset": 5200000, "Duration": 3000000},
                {"Word": "orange", "AccuracyScore": 0.0, "ErrorType": "Omission"},
                {"Word": "huh", "AccuracyScore": 0.0, "ErrorType": "SomethingNew"},
            ],
        }],
    }
    payload.update(overrides)
    return payload


def assessor_with(handler, key="test-key"):
    return AzurePronunciationAssessor(key=key, region="eastasia",
                                      client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_azure_assessment_maps_scores_words_and_request_contract():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=azure_payload())

    audio = parse_wav(speech_like_wav(1200), max_duration_ms=5000)
    result = assessor_with(handler).assess(audio, reference_text="Before the leaves fall.", language_code="en")

    assert result.scores.pronunciation == 82.3 and result.scores.prosody == 87.4
    assert [word.error_type for word in result.words] == [
        PronunciationErrorType.NONE, PronunciationErrorType.MISPRONUNCIATION,
        PronunciationErrorType.OMISSION, PronunciationErrorType.OTHER]
    assert (result.words[0].start_ms, result.words[0].end_ms) == (80, 510)
    assert result.words[2].start_ms is None
    request = seen[0]
    assert request.url.host == "eastasia.stt.speech.microsoft.com"
    assert request.url.params["language"] == "en-US"
    config = json.loads(base64.b64decode(request.headers["Pronunciation-Assessment"]))
    assert config["ReferenceText"] == "Before the leaves fall." and config["EnableMiscue"] is True
    assert config["EnableProsodyAssessment"] is True and config["PhonemeAlphabet"] == "IPA"
    assert request.content == audio.to_wav()


def test_azure_no_match_is_no_speech_not_a_learner_failure():
    assessor = assessor_with(lambda request: httpx.Response(200, json={"RecognitionStatus": "NoMatch"}))
    with pytest.raises(NoSpeechDetected):
        assessor.assess(SpeechAudio(pcm_tone(1000)), reference_text="Hello", language_code="en")


@pytest.mark.parametrize("status_code,category", [
    (401, "configuration"), (403, "configuration"), (429, "busy"), (500, "transport"), (400, "rejected"),
])
def test_azure_http_failures_are_typed(status_code, category, caplog):
    assessor = assessor_with(lambda request: httpx.Response(status_code, text="secret provider body"))
    with caplog.at_level(logging.WARNING), pytest.raises(SpeechProviderFailure) as raised:
        assessor.assess(SpeechAudio(pcm_tone(1000)), reference_text="Hello", language_code="en")
    assert raised.value.category == category
    assert "secret provider body" not in caplog.text and "test-key" not in caplog.text


def test_azure_out_of_range_scores_fail_closed():
    payload = azure_payload()
    payload["NBest"][0]["PronScore"] = 140.0
    assessor = assessor_with(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(SpeechProviderFailure) as raised:
        assessor.assess(SpeechAudio(pcm_tone(1000)), reference_text="Hello", language_code="en")
    assert raised.value.category == "rejected"


def test_azure_transport_errors_and_language_support():
    def fail(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(SpeechProviderFailure) as raised:
        assessor_with(fail).assess(SpeechAudio(pcm_tone(1000)), reference_text="Hi", language_code="ja")
    assert raised.value.category == "transport"
    assert assessor_with(fail).supports("ja") and not assessor_with(fail).supports("xx")
    assert not assessor_with(fail, key="").supports("en")


# --- Transcription and audio provider contract -----------------------------------

class FakeAudioModel:
    provider_name = "fake"
    model_name = "fake-audio"

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def generate_structured_with_audio(self, prompt, wav_audio, response_model, **kwargs):
        self.calls.append((prompt, wav_audio, kwargs))
        if self.error:
            raise self.error
        return response_model.model_validate(self.result)


def test_transcriber_normalizes_and_fails_closed():
    audio = SpeechAudio(pcm_tone(1000))
    model = FakeAudioModel({"transcript": "  they   turns into ", "contains_speech": True})
    assert SpeechTranscriber(model).transcribe(audio, language_code="en").text == "they turns into"
    assert "verbatim" in model.calls[0][2]["system_prompt"].casefold()
    with pytest.raises(NoSpeechDetected):
        SpeechTranscriber(FakeAudioModel({"transcript": "", "contains_speech": False})).transcribe(
            audio, language_code="en")
    with pytest.raises(SpeechProviderFailure):
        SpeechTranscriber(FakeAudioModel(error=LLMProviderError("down"))).transcribe(audio, language_code="en")


class _Echo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word: str


def test_provider_sends_audio_as_input_audio_part(monkeypatch):
    calls = []

    class Completions:
        def parse(self, **kwargs):
            calls.append(kwargs)
            message = type("M", (), {"parsed": _Echo(word="pong"), "refusal": None})()
            return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

    provider = OpenAICompatibleLLMProvider(api_key="k", base_url="https://provider.invalid/v1", model_name="m")
    provider.client = type("Client", (), {"beta": type("B", (), {"chat": type("Ch", (), {
        "completions": Completions()})()})()})()

    result = provider.generate_structured_with_audio("Transcribe", b"RIFFwav", _Echo, system_prompt="sys")

    assert result.word == "pong"
    content = calls[0]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "Transcribe"}
    assert content[1]["input_audio"] == {"data": base64.b64encode(b"RIFFwav").decode(), "format": "wav"}
    with pytest.raises(LLMProviderError):
        provider.generate_structured_with_audio("x", b"", _Echo, system_prompt="sys")
    assert providers_module.LLMProviderFailureCategory
