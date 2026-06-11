# 中文注释：记录数据库结构迁移步骤，供 Alembic 按版本顺序执行。

"""add agent message audit json

Revision ID: d4e8f2a9c731
Revises: c1a7e9d2f4b6
Create Date: 2026-05-25 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e8f2a9c731"
down_revision: str | Sequence[str] | None = "c1a7e9d2f4b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "agent_messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_messages")}
    if "audit_json" in columns:
        return
    with op.batch_alter_table("agent_messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("audit_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "agent_messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_messages")}
    if "audit_json" not in columns:
        return
    with op.batch_alter_table("agent_messages", schema=None) as batch_op:
        batch_op.drop_column("audit_json")
