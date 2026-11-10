"""add server defaults to users

Revision ID: 06481f7daeb1
Revises: 9e8b0b2ce446
Create Date: 2026-11-11 02:06:01.538328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '06481f7daeb1'
down_revision: Union[str, Sequence[str], None] = '9e8b0b2ce446'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("users", "id", server_default=sa.text("gen_random_uuid()"))
    op.alter_column("users", "is_guest", server_default=sa.text("true"))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("users", "is_guest", server_default=None)
    op.alter_column("users", "id", server_default=None)