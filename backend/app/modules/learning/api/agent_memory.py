"""What the agent remembers about the signed-in learner (PRD 8.12 point 3): the learner lists it and deletes one
row or all of it. The learner never writes memory here; the agent does, through its own tool."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.bootstrap.wiring.agent import get_agent_memory
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.agent.context import ContextBuilder
from app.modules.learning.application.agent.ports import AgentMemory

router = APIRouter()

MAX_LISTED = 40  # the most rows a learner can have
_NO_STORE = {"Cache-Control": "no-store"}


class AgentMemoryItem(BaseModel):
    id: UUID
    kind: Literal["goal", "interest", "error", "follow_up"]
    text: str
    language_code: str | None
    created_at: datetime


class AgentMemoryView(BaseModel):
    items: list[AgentMemoryItem]


@router.get("/learner/me/agent/memory", response_model=AgentMemoryView)
def read_agent_memory(
    response: Response,
    user: CurrentUser = Depends(require_authenticated_user),
    memory: AgentMemory = Depends(get_agent_memory),
) -> AgentMemoryView:
    response.headers.update(_NO_STORE)
    return AgentMemoryView(items=[AgentMemoryItem(**row) for row in memory.list_for_learner(user.id, limit=MAX_LISTED)])


@router.delete("/learner/me/agent/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_memory_item(
    memory_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    memory: AgentMemory = Depends(get_agent_memory),
) -> None:
    deleted = memory.delete_one(user.id, memory_id)
    ContextBuilder.forget_learner(user.id)  # the agent's cached context may still carry this note
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "memory_not_found", "message": "Memory not found."})


@router.delete("/learner/me/agent/memory", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_agent_memory(
    user: CurrentUser = Depends(require_authenticated_user),
    memory: AgentMemory = Depends(get_agent_memory),
) -> None:
    deleted = memory.delete_all(user.id)
    ContextBuilder.forget_learner(user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={"code": "agent_memory_unavailable",
                                    "message": "Your memory could not be deleted right now. Please try again."})
