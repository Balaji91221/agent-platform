"""The model catalogue the create form offers, grouped by provider."""

from fastapi import APIRouter, Depends

from app.config import settings
from app.dependencies.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("")
async def list_models(user: User = Depends(get_current_user)):
    """Every model a user may pick, and who serves it."""
    return [
        {
            "name": name,
            "provider": "nvidia" if name in settings.NVIDIA_MODELS else "anthropic",
            "catalogue_id": catalogue_id,
            "vision": name in settings.NVIDIA_VISION_MODELS,
            "reasoning": name in settings.NVIDIA_REASONING_MODELS,
        }
        for name, catalogue_id in settings.MODEL_IDS.items()
    ]
