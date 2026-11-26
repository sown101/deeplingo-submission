"""The review HTTP surface: learner input only, one transaction per answer, and the Flutter memory-rating shape."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.practice import get_review_service, get_review_speech
from app.bootstrap.wiring.speaking import get_speaking_rate_limiter
from app.main import app
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from tests.practice.fakes import USER, make_review, word

PREFIX = "/api/v1/v3"
EN = word("leave", meaning="rời đi", sentence="I have to leave now.")
ZH = word("你好", "zh", meaning="xin chào", sentence="他说你好。")


class Speech:
    def __init__(self):
        self.assessed = []
        self.read = []

    def audio(self, language, text, *, saved=False):
        self.read.append((language, text, saved))
        return f"{language}:{text}".encode()

    def assess_result(self, user, language, text, audio, *, saved=False):
        self.assessed.append((language, text, saved))
        scores = SimpleNamespace(pronunciation=95.0, accuracy=92.0, fluency=97.0, completeness=100.0, prosody=None)
        words = (SimpleNamespace(word=text, accuracy=92.0, error_type=SimpleNamespace(value="mispronunciation"),
                                 phonemes=(SimpleNamespace(phoneme="l", accuracy=99.0),
                                           SimpleNamespace(phoneme="iː", accuracy=58.0))),)
        return text, SimpleNamespace(value="excellent"), SimpleNamespace(recognized_text="Leave.", scores=scores,
                                                                         words=words)


@pytest.fixture
def client():
    env = make_review([EN, ZH])
    speech = Speech()
    app.dependency_overrides[get_review_service] = lambda: env.service
    app.dependency_overrides[get_review_speech] = lambda: speech
    app.dependency_overrides[get_speaking_rate_limiter] = lambda: SimpleNamespace(allow=lambda *args: True)
    try:
        test_client = TestClient(app)
        assert test_client.get(f"{PREFIX}/learner/me/review/decks").status_code == 401
        app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(id=USER)
        yield test_client, env, speech
    finally:
        for dependency in (get_review_service, get_review_speech, get_speaking_rate_limiter,
                           require_authenticated_user):
            app.dependency_overrides.pop(dependency, None)


def body(card, **changes):
    return {"client_event_id": "evt-1", "pass_id": "pass-1", "concept_id": str(card.concept_id),
            "language_code": card.language_code, "exercise_type": "choice", "answer": {"option": card.meaning},
            "response_ms": 2500, **changes}


def test_due_cards_follow_the_review_settings_types(client):
    http, _, _ = client
    due = http.get(f"{PREFIX}/learner/me/review/en/due?types=order").json()
    assert [card["exercise"]["type"] for card in due["cards"]] == ["order"]
    assert http.get(f"{PREFIX}/learner/me/review/en/due?types=order,Bad").status_code == 422
    assert http.get(f"{PREFIX}/learner/me/review/en/due?types=guessing").status_code == 422


def test_decks_and_due_cards_by_language(client):
    http, _, _ = client
    decks = http.get(f"{PREFIX}/learner/me/review/decks").json()["decks"]
    assert [(deck["language_code"], deck["new_count"]) for deck in decks] == [("en", 1), ("zh", 1)]
    due = http.get(f"{PREFIX}/learner/me/review/zh/due?mode=writing").json()
    assert due["language_code"] == "zh" and len(due["cards"]) == 1
    assert due["cards"][0]["exercise"] == {"type": "writing", "prompt": {
        "script": "strokes", "characters": "你好", "reading": None, "meaning": "xin chào"}}
    assert http.get(f"{PREFIX}/learner/me/review/zh/due?mode=guessing").status_code == 422
    assert http.get(f"{PREFIX}/learner/me/review/EN!/due").status_code == 422


def test_an_answer_is_graded_once_logged_once_and_a_retry_returns_the_stored_result(client):
    http, env, _ = client
    first = http.post(f"{PREFIX}/learner/me/review/answers", json=body(EN))
    again = http.post(f"{PREFIX}/learner/me/review/answers", json=body(EN))
    assert first.status_code == again.status_code == 200
    assert (first.json()["correct"], first.json()["scheduled"], first.json()["duplicate"]) == (True, True, False)
    assert again.json()["duplicate"] is True and again.json()["grade"] == first.json()["grade"]
    assert len(env.log.entries) == 1 and len(env.store.events) == 1


@pytest.mark.parametrize("forged", [{"correct": True}, {"grade": "easy"}, {"user_id": str(USER)}, {"score": 100}])
def test_the_client_cannot_send_a_result(client, forged):
    http, env, _ = client
    assert http.post(f"{PREFIX}/learner/me/review/answers", json={**body(EN), **forged}).status_code == 422
    assert http.post(f"{PREFIX}/learner/me/review/answers", json=body(EN, answer={"option": "x", **forged})
                     ).status_code == 422
    assert env.log.entries == []


def test_a_word_outside_the_learners_deck_is_a_409(client):
    http, env, _ = client
    stranger = word("other", meaning="khác")
    response = http.post(f"{PREFIX}/learner/me/review/answers", json=body(stranger))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "word_not_in_review"
    assert env.log.entries == []


def test_pronunciation_is_assessed_on_the_server_returns_every_detail_and_the_latest_is_kept(client):
    http, env, speech = client
    latest = f"{PREFIX}/learner/me/words/{EN.concept_id}/pronunciation"
    assert http.get(latest).json() == {"concept_id": str(EN.concept_id), "latest": None}
    response = http.post(f"{PREFIX}/learner/me/review/answers/pronunciation", data={
        "client_event_id": "p-1", "concept_id": str(EN.concept_id), "language_code": "en", "pass_id": "pass-1"},
        files={"audio": ("a.wav", _wav(), "audio/wav")})
    assert response.status_code == 200, response.text
    view = response.json()
    # The saved word is assessed even when the dictionary does not hold it, and the schedule never moves.
    assert view["correct"] is True and view["scheduled"] is False and speech.assessed == [("en", "leave", True)]
    assert view["assessment"]["scores"] == {"pronunciation": 95.0, "accuracy": 92.0, "fluency": 97.0,
                                            "completeness": 100.0, "prosody": None}
    assert view["assessment"]["words"] == [{"word": "leave", "accuracy": 92.0, "error_type": "mispronunciation",
                                            "phonemes": [{"phoneme": "l", "accuracy": 99.0},
                                                         {"phoneme": "iː", "accuracy": 58.0}]}]
    assert len(env.log.of("pronunciation")) == 1 and env.store.events == []
    stored = http.get(latest).json()["latest"]
    assert (stored["score"], stored["band"]) == (95.0, "excellent")
    assert stored["assessment"]["words"] == view["assessment"]["words"]


def test_card_audio_is_chosen_by_id_and_only_for_the_learners_words(client):
    http, _, speech = client
    response = http.get(f"{PREFIX}/learner/me/review/cards/{ZH.concept_id}/audio")
    assert response.status_code == 200 and response.content == "zh:你好".encode()
    assert speech.read == [("zh", "你好", True)]  # a saved word has audio whatever the dictionary holds
    assert http.get(f"{PREFIX}/learner/me/review/cards/{word('x').concept_id}/audio").status_code == 404


def test_flutter_memory_rating_keeps_its_shape(client):
    http, env, _ = client
    url = f"{PREFIX}/learner/me/words/{ZH.concept_id}/memory-rating"
    first = http.post(url, json={"rating": "remembered", "client_event_id": "6f1c9a52-0000-4000-8000-000000000001"})
    assert first.status_code == 200 and set(first.json()) == {"next_review_at"}
    assert http.post(url, json={"rating": "remembered", "client_event_id": "6f1c9a52-0000-4000-8000-000000000001"}
                     ).json() == first.json()
    assert len(env.log.of("flashcard")) == 1 and len(env.store.events) == 1
    assert http.post(url, json={"rating": "good"}).status_code == 422
    missing = http.post(f"{PREFIX}/learner/me/words/{word('x').concept_id}/memory-rating", json={"rating": "unsure"})
    assert missing.status_code == 409 and missing.json()["detail"]["code"] == "word_not_in_review"


def _wav() -> bytes:
    import io
    import math
    import struct
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(16000)))
    return buffer.getvalue()
