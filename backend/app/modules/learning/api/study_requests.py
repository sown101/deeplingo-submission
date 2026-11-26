"""What Tata asked the signed-in learner to practise again, for the agent screen (PRD 8.10): open requests in one
language with a readable title. Dismissing one is `POST /learner/me/study-requests/{id}/dismiss` (activity module)."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict

from app.bootstrap.wiring.agent import LearnerFacts, get_learner_facts
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser

router = APIRouter()
LANGUAGE = r"^[a-z]{2,3}(-[A-Za-z0-9]{1,8})?$"


class AgentStudyRequestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    kind: Literal["grammar_redo", "word_review", "pronunciation_retry", "region_practice"]
    title: str | None
    reason: str | None
    created_at: datetime


class AgentStudyRequestsView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AgentStudyRequestItem]


@router.get("/learner/me/agent/study-requests", response_model=AgentStudyRequestsView)
def read_agent_study_requests(
    response: Response,
    language: str = Query(min_length=2, max_length=16, pattern=LANGUAGE),
    support: str = Query(default="vi", min_length=2, max_length=16, pattern=LANGUAGE),
    user: CurrentUser = Depends(require_authenticated_user),
    facts: LearnerFacts = Depends(get_learner_facts),
) -> AgentStudyRequestsView:
    response.headers["Cache-Control"] = "no-store"
    return AgentStudyRequestsView(items=[AgentStudyRequestItem(**row)
                                         for row in facts.open_requests(user.id, language, support)])
