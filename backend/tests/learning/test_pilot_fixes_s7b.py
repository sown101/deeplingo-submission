"""M1 S7b: learning fixes before the pilot (Library occurrences, retention)."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from app.modules.content.application.library_occurrences import LibraryOccurrenceService
from app.modules.learning.worker import tasks as learning_tasks


# --- The Library occurrence reader (content module) --------------------------------------------------------------------

def test_occurrences_come_only_from_the_learners_videos_current_transcript_and_exact_span():
    mine, theirs = uuid4(), uuid4()
    track, old_track = uuid4(), uuid4()
    word, other = uuid4(), uuid4()
    segment = SimpleNamespace(id=uuid4(), transcript_id=track, text="We put off the trip.", start_ms=4000)
    old_segment = SimpleNamespace(id=uuid4(), transcript_id=old_track, text="We put off the trip.", start_ms=4000)
    moved = SimpleNamespace(id=uuid4(), transcript_id=track, text="We delayed the trip.", start_ms=4000)

    def lo(concept_id, video_id, seg, start_ms):
        return SimpleNamespace(id=uuid4(), concept_id=concept_id, video_id=video_id, transcript_segment_id=seg.id,
                               start_codepoint=3, end_codepoint=10, evidence_text="put off", start_ms=start_ms,
                               raw_ai_diagnostics=None)

    rows = [lo(word, mine, old_segment, 0), lo(word, mine, moved, 1), lo(word, mine, segment, 2),
            lo(other, theirs, segment, 0)]
    library, videos, transcripts, objects, segments = Mock(), Mock(), Mock(), Mock(), Mock()
    library.list_for_user.return_value = [SimpleNamespace(id=uuid4(), video_id=mine)]
    objects.list_for_videos_concepts.side_effect = lambda video_ids, concept_ids: [
        row for row in rows if row.video_id in video_ids and row.concept_id in concept_ids]
    videos.get_many_by_ids.side_effect = lambda ids: {
        video_id: SimpleNamespace(id=video_id, original_language_code="en") for video_id in ids}
    transcripts.list_for_videos.return_value = [
        SimpleNamespace(id=old_track, video_id=mine, is_original=False, language_code="en", source="asr"),
        SimpleNamespace(id=track, video_id=mine, is_original=True, language_code="en", source="caption_track")]
    by_id = {row.id: row for row in (segment, old_segment, moved)}
    segments.list_by_ids.side_effect = lambda ids: [by_id[segment_id] for segment_id in ids if segment_id in by_id]
    reader = LibraryOccurrenceService(library=library, videos=videos, transcripts=transcripts, objects=objects,
                                      segments=segments)
    found = reader.sentences_for(uuid4(), [word, other])
    assert set(found) == {word}  # the other word only occurs in someone else's video
    assert found[word].learning_object_id == rows[2].id  # old transcript and a moved span are skipped
    assert found[word].sentence == "We put off the trip." and found[word].target_form == "put off"
    # One read per store whatever the number of videos or occurrences; sentences are read for each
    # word's next candidate only, so the two stale candidates here cost one more round each.
    for store, method in ((library, "list_for_user"), (objects, "list_for_videos_concepts"),
                          (videos, "get_many_by_ids"), (transcripts, "list_for_videos")):
        assert getattr(store, method).call_count == 1, method
    assert [call.args[0] for call in segments.list_by_ids.call_args_list] == [
        [old_segment.id], [moved.id], [segment.id]]
    assert objects.list_for_videos_concepts.call_args.args == ([mine], [word, other])
    assert reader.sentences_for(uuid4(), []) == {}


def test_a_library_occurrence_carries_only_a_meaning_translated_from_a_dictionary_sense():
    from app.modules.content.domain.prepared_context import sense_translated_meaning
    translated = {"enrichments": {"vi": {"meaning_provenance": "translated_from_sense",
                                         "contextual_meaning": " hoãn  lại ", "dictionary_sense": {"pos": "verb"}}}}
    assert sense_translated_meaning(translated, "vi") == ("hoãn lại", "verb")
    unverified = {"enrichments": {"vi": {"meaning_provenance": "ai_unverified", "contextual_meaning": "hoãn"}}}
    assert sense_translated_meaning(unverified, "vi") == (None, None)
    assert sense_translated_meaning(translated, "fr") == (None, None) == sense_translated_meaning(None, "vi")


# --- Retention ----------------------------------------------------------------------------------

def test_the_purge_runs_in_bounded_batches_until_nothing_is_left(monkeypatch):
    client = Mock()
    # FR-3.11: transcripts older than 12 months go in the same batches; an environment without the
    # transcript migration returns no such key and counts as nothing left.
    results = [{"speech_transcripts": learning_tasks.PURGE_BATCH}] * 2 + [{"speech_transcripts": 7}]
    client.schema.return_value.rpc.return_value.execute.side_effect = [SimpleNamespace(data=row) for row in results]
    monkeypatch.setattr(learning_tasks, "supabase_service", client)
    assert learning_tasks.purge_expired_learner_data() == {"speech_transcripts": 2 * learning_tasks.PURGE_BATCH + 7,
                                                           "pronunciation_scores": 0}
    assert client.schema.return_value.rpc.call_args.args == (
        "purge_expired_learner_data", {"p_limit": learning_tasks.PURGE_BATCH})


def test_the_purge_keeps_going_while_pronunciation_scores_fill_a_batch(monkeypatch):
    client = Mock()
    batch = learning_tasks.PURGE_BATCH
    results = [{"speech_transcripts": 3, "pronunciation_scores": batch}, {"speech_transcripts": 0,
                                                                         "pronunciation_scores": 4}]
    client.schema.return_value.rpc.return_value.execute.side_effect = [SimpleNamespace(data=row) for row in results]
    monkeypatch.setattr(learning_tasks, "supabase_service", client)
    assert learning_tasks.purge_expired_learner_data() == {"speech_transcripts": 3, "pronunciation_scores": batch + 4}


def test_the_purge_is_scheduled_hourly():
    from app.bootstrap.worker import celery_app
    schedule = celery_app.conf.beat_schedule["purge-expired-learner-data"]
    assert schedule == {"task": "deeplingo.purge_expired_learner_data", "schedule": 3600.0}
    assert "app.modules.learning.worker.tasks" in celery_app.conf.imports
