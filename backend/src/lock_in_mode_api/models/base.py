import enum

from sqlalchemy import Enum, MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_cls: type[enum.Enum]) -> Enum:
    """Store a Python enum as plain text (its value), not a native Postgres ENUM."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=30,
        values_callable=lambda members: [member.value for member in members],
    )
