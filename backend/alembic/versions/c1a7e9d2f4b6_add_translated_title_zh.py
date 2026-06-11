# 中文注释：记录数据库结构迁移步骤，供 Alembic 按版本顺序执行。

"""add translated Chinese mod title

Revision ID: c1a7e9d2f4b6
Revises: b2f4f0d4a1c8
Create Date: 2026-05-24 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a7e9d2f4b6"
down_revision: str | Sequence[str] | None = "b2f4f0d4a1c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "mods" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("mods")}
    if "translated_title_zh" in columns:
        return
    with op.batch_alter_table("mods", schema=None) as batch_op:
        batch_op.add_column(sa.Column("translated_title_zh", sa.String(length=512), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "mods" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("mods")}
    if "translated_title_zh" not in columns:
        return
    with op.batch_alter_table("mods", schema=None) as batch_op:
        batch_op.drop_column("translated_title_zh")
