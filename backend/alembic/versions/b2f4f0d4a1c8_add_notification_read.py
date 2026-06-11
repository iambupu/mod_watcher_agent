# 中文注释：记录数据库结构迁移步骤，供 Alembic 按版本顺序执行。

"""add notification read flag

Revision ID: b2f4f0d4a1c8
Revises: 97340fefbb99
Create Date: 2026-05-19 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2f4f0d4a1c8"
down_revision: str | Sequence[str] | None = "97340fefbb99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "notifications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("notifications")}
    if "read" in columns:
        return
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "notifications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("notifications")}
    if "read" not in columns:
        return
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_column("read")
