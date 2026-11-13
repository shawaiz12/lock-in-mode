from fastapi import APIRouter

from lock_in_mode_api.api.deps import CurrentUser
from lock_in_mode_api.schemas.user import UserRead

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
