from fastapi import APIRouter

from lock_in_mode_api.api.v1 import auth, me

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(me.router)
