"""Composition of the exercise engine (practice module): review decks, grammar, and their speech."""
from functools import lru_cache

from app.bootstrap.wiring.activity import build_activity_service
from app.bootstrap.wiring.clients import service_client


def _word_cards(client):
    from app.modules.content.application.library_occurrences import LibraryOccurrenceService
    from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
    from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
    from app.modules.content.infrastructure.repositories.example_sentences import ExampleSentenceRepository
    from app.modules.content.infrastructure.repositories.learner_videos import LearnerVideoRepository
    from app.modules.content.infrastructure.repositories.learning_objects import LearningObjectRepository
    from app.modules.content.infrastructure.repositories.sense_translations import SenseTranslationRepository
    from app.modules.content.infrastructure.repositories.transcript_segments import TranscriptSegmentRepository
    from app.modules.content.infrastructure.repositories.video_transcripts import VideoTranscriptRepository
    from app.modules.content.infrastructure.repositories.videos import VideoRepository
    from app.modules.learner.infrastructure.user_language_preferences import UserLanguagePreferenceRepository
    from app.modules.practice.infrastructure.word_cards import WordCards
    return WordCards(
        profiles=UserLanguagePreferenceRepository(client), concepts=ConceptRepository(client),
        meanings=SenseTranslationRepository(client), examples=ExampleSentenceRepository(client),
        occurrences=LibraryOccurrenceService(
            library=LearnerVideoRepository(client), videos=VideoRepository(client),
            transcripts=VideoTranscriptRepository(client), objects=LearningObjectRepository(client),
            segments=TranscriptSegmentRepository(client)),
        readings=DictionaryEntryRepository(client))


def build_review_service(client):
    from app.modules.practice.application.review import ReviewService
    from app.modules.practice.infrastructure.repositories import ReviewDeckRepository
    from app.modules.review.infrastructure.fsrs_adapter import FSRSAdapter
    return ReviewService(store=ReviewDeckRepository(client), cards=_word_cards(client), adapter=FSRSAdapter())


def get_review_service():
    return build_review_service(service_client())


def get_grammar_service():
    from app.modules.content.infrastructure.grammar_banks import GrammarBanks
    from app.modules.learner.infrastructure.user_language_preferences import UserLanguagePreferenceRepository
    from app.modules.practice.application.grammar import GrammarService
    from app.modules.practice.infrastructure.repositories import GrammarProgressRepository
    client = service_client()
    return GrammarService(profiles=UserLanguagePreferenceRepository(client), banks=GrammarBanks(),
                          progress=GrammarProgressRepository(client), requests=build_activity_service(client))


def get_review_speech():
    """A word read aloud and one attempt at saying it, without a log row of its own: the review answer is the
    one row."""
    return _review_speech()


@lru_cache(maxsize=1)
def _review_speech():
    from app.bootstrap.wiring.learner import get_agent_signals_service
    from app.bootstrap.wiring.speaking import (
        PronunciationScoreRepository,
        _pronunciation_assessor,
        _speech_synthesizer,
    )
    from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
    from app.modules.learning.application.word_speech import WordSpeechService
    client = service_client()
    return WordSpeechService(dictionary=DictionaryEntryRepository(client), synthesizer=_speech_synthesizer(),
                             assessor=_pronunciation_assessor(), consent=get_agent_signals_service(),
                             scores=PronunciationScoreRepository(client), learning_log=None)
