"""SQLAlchemy declarative base shared by all ORM models.

Import ``Base`` in every model module so Alembic's autogenerate can
discover the full schema via ``Base.metadata``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide declarative base class.

    All SQLAlchemy ORM models must inherit from this class.

    Example
    -------
    >>> from app.db.base import Base
    >>> class MyModel(Base):
    ...     __tablename__ = "my_table"
    ...     ...
    """
