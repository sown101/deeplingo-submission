"""Learner module object graph and FastAPI dependency providers."""
from app.bootstrap.wiring.activity import build_activity_service
from app.bootstrap.wiring.clients import service_client
from app.modules.learner.application.learner_model import LearnerModelService
from app.modules.learner.infrastructure.profiles import ProfileRepository
from app.modules.learner.infrastructure.user_language_preferences import UserLanguagePreferenceRepository
from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
from app.modules.content.infrastructure.repositories.languages import LanguageRepository


def get_learner_model_service() -> LearnerModelService:
    supabase_service = service_client()
    return LearnerModelService(
        profiles=ProfileRepository(supabase_service),
        languages=LanguageRepository(supabase_service),
        language_preferences=UserLanguagePreferenceRepository(supabase_service),
    )


def get_account_deletion_service():
    """Self-service account deletion (service-role sign-in admin)."""
    from app.modules.learner.application.account_deletion import AccountDeletionService
    from app.modules.learner.infrastructure.sign_in_users import SupabaseSignInUsers
    return AccountDeletionService(users=SupabaseSignInUsers(service_client()))


def get_agent_signals_service():
    """The learner's voice consent and personalization signals (service-role writes)."""
    from app.modules.learner.application.agent_signals import AgentSignalsService
    from app.modules.learner.infrastructure.agent_signals import (
        AgentConsentRepository,
        PersonalizationSignalRepository,
    )
    supabase_service = service_client()
    return AgentSignalsService(
        consents=AgentConsentRepository(supabase_service),
        signals=PersonalizationSignalRepository(supabase_service),
    )


def get_speech_transcripts_service():
    """FR-3.11: the separate transcript consent and the kept spoken turns (service-role, backend-only table)."""
    from app.modules.learner.application.speech_transcripts import SpeechTranscriptService
    from app.modules.learner.infrastructure.agent_signals import AgentConsentRepository
    from app.modules.learner.infrastructure.speech_transcripts import SpeechTranscriptRepository
    supabase_service = service_client()
    return SpeechTranscriptService(consents=AgentConsentRepository(supabase_service),
                                   transcripts=SpeechTranscriptRepository(supabase_service))


def get_word_targets_service():
    """L1a: the learner's targets, level warnings and the usage ladder."""
    from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
    from app.modules.learner.application.word_targets import WordTargetsService
    from app.modules.learner.infrastructure.target_events import TargetEventRepository
    client = service_client()
    return WordTargetsService(
        targets=SavedConceptRepository(client), events=TargetEventRepository(client),
        preferences=UserLanguagePreferenceRepository(client), profiles=ProfileRepository(client),
    )


class _DictionaryHeadwords:
    """L1b: the dictionary meanings of typed words, found in a few batched reads. An inflected form
    ("went") that has no meaning of its own offers its base form's meanings ("go")."""

    def __init__(self, dictionary):
        self.dictionary = dictionary

    def candidates_for(self, language_code, words):
        from app.modules.content.application.knowledge_resolution import normalize_reference_text
        from app.modules.content.application.word_lookup import real_senses
        from app.modules.learner.domain.word_lists import SenseCandidate

        keys = {word: normalize_reference_text(word, language_code=language_code) for word in words}
        wanted = sorted({key for key in keys.values() if key})
        found = {}
        for start in range(0, len(wanted), 100):
            for entry in self.dictionary.list_by_headwords(
                    language_code=language_code, normalized_headwords=wanted[start:start + 100]):
                found[entry.normalized_headword] = entry

        def senses_of(entry):
            return [SenseCandidate(entry_id=entry.id, sense_id=sense["sense_id"], headword=entry.headword,
                                   text=str(sense["text"]), part_of_speech=sense.get("pos"))
                    for sense in real_senses(entry) if entry.id is not None]

        bases = {}
        base_keys = sorted({normalize_reference_text(base, language_code=language_code)
                            for entry in found.values() if not real_senses(entry)
                            for sense in entry.definitions if isinstance(sense, dict)
                            for base in (sense.get("form_of") or []) if isinstance(base, str)} - set(found))
        for start in range(0, len(base_keys), 100):
            for entry in self.dictionary.list_by_headwords(
                    language_code=language_code, normalized_headwords=base_keys[start:start + 100]):
                bases[entry.normalized_headword] = entry

        result = {}
        for word, key in keys.items():
            entry = found.get(key)
            candidates = senses_of(entry) if entry is not None else []
            if entry is not None and not candidates:
                for sense in entry.definitions:
                    for base in (sense.get("form_of") or []) if isinstance(sense, dict) else []:
                        base_entry = bases.get(normalize_reference_text(base, language_code=language_code)) \
                            or found.get(normalize_reference_text(base, language_code=language_code))
                        if base_entry is not None:
                            candidates.extend(item for item in senses_of(base_entry) if item not in candidates)
            result[word] = candidates
        return result


class _LibraryVideoProfiles:
    """L1c: the content module's profiles, in the shapes learner coverage reads."""

    def __init__(self, library_profiles):
        self.library_profiles = library_profiles

    @staticmethod
    def _convert(found):
        from app.modules.learner.domain.video_coverage import ProfileLexeme, VideoProfile
        profile = found.profile
        return VideoProfile(
            language_code=profile.language_code, token_count=profile.token_count,
            proper_noun_count=profile.proper_noun_count, speech_ms=profile.speech_ms,
            lexemes=[ProfileLexeme(item.lexeme, item.level, item.matched, item.occurrences, item.level_derived)
                      for item in found.lexemes])

    def for_item(self, user, library_item_id):
        from app.modules.content.application.library import LearnerLibraryError
        from app.modules.learner.application.video_coverage import VideoCoverageError
        try:
            return self._convert(self.library_profiles.for_item(user, library_item_id))
        except LearnerLibraryError as exc:
            raise VideoCoverageError(str(exc), status_code=exc.status_code, code=exc.code) from exc

    def for_library(self, user, *, build_budget):
        return [(item_id, self._convert(found) if found is not None else None)
                for item_id, found in self.library_profiles.for_library(user, build_budget=build_budget)]


class _RecognisedLexemes:
    """L1c: which words of a video the learner already recognised in practice (rung R1+)."""

    def __init__(self, targets, concepts):
        self.targets, self.concepts = targets, concepts

    def known_among(self, user_id, language_code, lexemes):
        from uuid import UUID
        wanted = set(lexemes)
        ids = {UUID(str(row["concept_id"])) for row in self.targets.list_for_user(user_id, language_code=language_code)
                if int(row.get("rung") or 0) >= 1}
        found: set[str] = set()
        ordered = sorted(ids, key=str)
        for start in range(0, len(ordered), 100):
            found.update(concept.normalized_text for concept in self.concepts.list_by_ids(ordered[start:start + 100])
                         if concept.normalized_text in wanted)
        return found


def get_video_coverage_service():
    """L1c: personal lexical coverage of the learner's own Library videos."""
    from app.bootstrap.wiring.content import get_library_lexical_profiles
    from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
    from app.modules.learner.application.video_coverage import VideoCoverageService
    client = service_client()
    return VideoCoverageService(
        profiles=_LibraryVideoProfiles(get_library_lexical_profiles()),
        known=_RecognisedLexemes(SavedConceptRepository(client), ConceptRepository(client)),
        targets=get_word_targets_service(),
    )


def get_word_list_service():
    """L1b: named word lists, bulk import and the choice of a meaning for an ambiguous line."""
    from app.bootstrap.wiring.content import get_word_concept_service
    from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
    from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
    from app.modules.learner.application.word_lists import WordListService
    from app.modules.learner.infrastructure.word_groups import (
        ImportRowRepository,
        WordGroupItemRepository,
        WordGroupRepository,
    )
    client = service_client()
    return WordListService(
        groups=WordGroupRepository(client), items=WordGroupItemRepository(client), rows=ImportRowRepository(client),
        targets_store=SavedConceptRepository(client), targets=get_word_targets_service(),
        resolver=_DictionaryHeadwords(DictionaryEntryRepository(client)), senses=get_word_concept_service(),
        concepts=ConceptRepository(client), preferences=UserLanguagePreferenceRepository(client),
        dictionary=DictionaryEntryRepository(client),
    )


def get_my_words_service():
    """The learner's saved words, with their target status (L1a)."""
    from app.bootstrap.wiring.content import get_word_concept_service
    from app.modules.learner.application.my_words import MyWordsService
    from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
    from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
    from app.modules.review.infrastructure.review_states import ReviewStateRepository
    from app.modules.learner.infrastructure.video_words import VideoWordRepository
    client = service_client()
    return MyWordsService(
        saved=SavedConceptRepository(client),
        resolver=get_word_concept_service(),
        concepts=ConceptRepository(client),
        reviews=ReviewStateRepository(client), preferences=UserLanguagePreferenceRepository(client),
        targets=get_word_targets_service(), video_words=VideoWordRepository(client),
        readings=DictionaryEntryRepository(client),
        learning_log=build_activity_service(client),
    )


def get_learner_data_export_service():
    """The learner's own data from every module as one document (privacy: right to access)."""
    from app.modules.activity.infrastructure.data_export import ActivityDataSection
    from app.modules.content.infrastructure.data_export import ConceptLabels, LibraryDataSection
    from app.modules.learner.application.data_export import LearnerDataExportService
    from app.modules.learner.infrastructure.data_export import LearnerOwnDataSection
    from app.modules.learning.infrastructure.data_export import LearningDataSection
    from app.modules.practice.infrastructure.data_export import PracticeDataSection
    from app.modules.review.infrastructure.data_export import ReviewDataSection
    client = service_client()
    return LearnerDataExportService(
        sections=[LearnerOwnDataSection(client), LibraryDataSection(client), LearningDataSection(client),
                  ReviewDataSection(client), ActivityDataSection(client),
                  PracticeDataSection(client)],
        concept_labels=ConceptLabels(client),
    )


