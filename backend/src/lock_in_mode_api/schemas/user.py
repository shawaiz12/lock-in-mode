import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    """Public view of a user. Never includes provider ids (google_sub/apple_sub)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_guest: bool
    display_name: str | None
    created_at: datetime
