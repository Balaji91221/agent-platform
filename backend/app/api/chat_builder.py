"""Plain words -> a draft agent the create form can open (plan FR-19)."""

from fastapi import APIRouter, Depends

from app.builder.draft import BuilderResult, build
from app.dependencies.auth import get_current_user
from app.models import User
from app.schemas.rest import DraftIn

router = APIRouter(prefix="/builder", tags=["Chat builder"])


@router.post("/draft", response_model=BuilderResult)
async def draft(payload: DraftIn, user: User = Depends(get_current_user)):
    """A reply when there is no task yet; otherwise a draft the form can open.

    Nothing is saved here — the user presses Create."""
    return await build(
        payload.text,
        timezone=payload.timezone,
        history=[t.model_dump() for t in payload.history],
    )
