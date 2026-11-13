import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lock_in_mode_api.models.base import Base


class RefreshToken(Base):
    """One issued refresh token (ADR 0005).

    Only the SHA-256 hash is stored, never the token itself. Every refresh
    replaces the token with a new one in the same `family_id`; if an
    already-used token comes back, the whole family is revoked.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Every token created by refreshing shares its ancestor's family_id.
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # Hex SHA-256 is always 64 characters; UNIQUE also gives us the lookup index.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set when this token is exchanged for a new one. Seeing it again = reuse.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set on logout or when reuse is detected in its family.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
