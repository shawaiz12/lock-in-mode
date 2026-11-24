"""Rules the database keeps for deleting accounts (ADR 0024), even if a service has a bug."""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Base, User
from lock_in_mode_api.models.enums import LeavingReason


async def test_a_reason_needs_a_waiting_deletion(db_session: AsyncSession) -> None:
    db_session.add(User(deletion_reason=LeavingReason.PRIVACY))

    with pytest.raises(IntegrityError, match="ck_users_reason_only_when_leaving"):
        await db_session.flush()


async def test_waiting_with_or_without_a_reason_is_fine(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            User(delete_after=func.now(), deletion_reason=LeavingReason.OTHER),
            User(delete_after=func.now()),
            User(),
        ]
    )
    await db_session.flush()

    assert await db_session.scalar(select(func.count()).select_from(User)) == 3


def test_every_foreign_key_to_users_cascades() -> None:
    """Deleting the users row must take everything with it (ADR 0024). A new user table
    without ON DELETE CASCADE would make every account deletion fail."""
    to_users = [
        fk
        for table in Base.metadata.sorted_tables
        for fk in table.foreign_keys
        if fk.column.table.name == "users"
    ]
    assert to_users
    assert {f"{fk.parent.table.name}.{fk.parent.name}": fk.ondelete for fk in to_users} == {
        f"{fk.parent.table.name}.{fk.parent.name}": "CASCADE" for fk in to_users
    }


async def test_the_database_cascades_too(db_session: AsyncSession) -> None:
    """The models say CASCADE; check the migrated database agrees."""
    rules = (
        await db_session.execute(
            text(
                """
                SELECT conrelid::regclass::text, confdeltype::text
                FROM pg_constraint
                WHERE contype = 'f' AND confrelid = 'users'::regclass
                """
            )
        )
    ).all()
    assert rules
    assert {table: rule for table, rule in rules} == {table: "c" for table, _ in rules}
