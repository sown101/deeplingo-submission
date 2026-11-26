"""Non-live dispatch/admission contracts; real PostgreSQL gates remain opt-in."""

from pathlib import Path
from uuid import UUID, uuid4

from app.bootstrap.worker import celery_app
from app.modules.content.domain.work_intents import VideoWorkIntent
from app.modules.content.worker.dispatch import ContentWorkDispatcher


MIGRATION = (
    Path(__file__).resolve().parents[2] / "supabase" / "migrations"
    / "20260929110100_durable_content_work_intents_v6b2b.sql"
)


class MemoryIntents:
    def __init__(self, count: int = 1):
        self.rows = {
            (intent_id := uuid4()): VideoWorkIntent(
                intent_id, uuid4(), "transcript", 1, "pending",
            )
            for _ in range(count)
        }
        self.accepted: list[tuple[UUID, bool]] = []
        self.fail_ack = False

    def get(self, intent_id):
        return self.rows.get(intent_id)

    def due(self, *, limit):
        return [row for row in self.rows.values() if row.state in {"pending", "dispatched"}][:limit]

    def record_dispatch(self, intent_id, *, accepted):
        if self.fail_ack:
            raise RuntimeError("lost dispatch acknowledgement")
        self.accepted.append((intent_id, accepted))
        if accepted:
            row = self.rows[intent_id]
            self.rows[intent_id] = VideoWorkIntent(row.id, row.video_id, row.stage, row.generation, "dispatched")


def test_dispatch_success_records_operational_receipt():
    intents = MemoryIntents()
    published = []
    dispatcher = ContentWorkDispatcher(intents, publish=lambda row: published.append(row.id) or "task-1")
    intent_id = next(iter(intents.rows))

    assert dispatcher.dispatch(intent_id) is True
    assert published == [intent_id]
    assert intents.accepted == [(intent_id, True)]
    assert intents.rows[intent_id].state == "dispatched"


def test_lost_initial_publish_leaves_intent_for_reconciler():
    intents = MemoryIntents()
    intent_id = next(iter(intents.rows))
    def unavailable(_):
        raise ConnectionError("broker unavailable")

    assert ContentWorkDispatcher(intents, publish=unavailable).dispatch(intent_id) is False
    assert intents.rows[intent_id].state == "pending"
    assert intents.accepted == [(intent_id, False)]

    published = []
    recovered = ContentWorkDispatcher(intents, publish=lambda row: published.append(row.id) or "task-2")
    assert recovered.reconcile_due(limit=1) == (1, 1)
    assert published == [intent_id]


def test_publish_ack_loss_allows_same_intent_republication():
    intents = MemoryIntents()
    intents.fail_ack = True
    published = []
    dispatcher = ContentWorkDispatcher(intents, publish=lambda row: published.append(row.id) or "task-3")
    intent_id = next(iter(intents.rows))

    assert dispatcher.dispatch(intent_id) is True
    assert intents.rows[intent_id].state == "pending"
    intents.fail_ack = False
    assert dispatcher.reconcile_due(limit=1) == (1, 1)
    assert published == [intent_id, intent_id]
    assert len(intents.rows) == 1


def test_reconciler_batch_is_bounded_and_terminal_intent_not_published():
    intents = MemoryIntents(count=4)
    terminal_id = next(iter(intents.rows))
    terminal = intents.rows[terminal_id]
    intents.rows[terminal_id] = VideoWorkIntent(
        terminal.id, terminal.video_id, terminal.stage, terminal.generation, "completed",
    )
    published = []
    dispatcher = ContentWorkDispatcher(intents, publish=lambda row: published.append(row.id) or "task-4")
    assert dispatcher.reconcile_due(limit=2) == (2, 2)
    assert len(published) == 2
    assert terminal_id not in published


def test_beat_reconciler_is_registered_without_new_queue():
    schedule = celery_app.conf.beat_schedule["reconcile-content-work-intents"]
    assert schedule["task"] == "deeplingo.reconcile_content_work_intents"
    assert schedule["schedule"] == 60.0
    assert not celery_app.conf.task_routes


def test_migration_has_atomic_admission_handoff_generation_and_private_grants():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()
    assert "constraint video_work_intents_generation_unique unique (video_id, stage, generation)" in sql
    assert "video_work_intents_one_active_stage_idx" in sql
    assert "insert into v3.learner_videos" in sql
    assert "insert into v3.video_work_intents" in sql
    assert "create function v3.complete_transcript_content_work" in sql
    assert "processing_status = 'transcript_ready'" in sql
    assert "alter table v3.video_work_intents enable row level security" in sql
    assert "revoke all on table v3.video_work_intents from public, anon, authenticated" in sql
    assert "security invoker set search_path = ''" in sql
    assert "grant execute on function v3.admit_video_content_work" in sql
    assert "to service_role" in sql
    assert "update v3.videos set learning_status = 'not_started'" in sql  # explicit retry, not historical backfill
    assert "where id = p_video_id returning * into v_video" in sql
