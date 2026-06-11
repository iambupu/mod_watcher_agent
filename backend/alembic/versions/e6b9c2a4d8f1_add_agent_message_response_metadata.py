# 中文注释：记录数据库结构迁移步骤，供 Alembic 按版本顺序执行。

"""add agent message response metadata

Revision ID: e6b9c2a4d8f1
Revises: d4e8f2a9c731
Create Date: 2026-05-26 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6b9c2a4d8f1"
down_revision: str | Sequence[str] | None = "d4e8f2a9c731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "agent_messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_messages")}
    with op.batch_alter_table("agent_messages", schema=None) as batch_op:
        if "response_cards_json" not in columns:
            batch_op.add_column(sa.Column("response_cards_json", sa.Text(), nullable=True))
        if "llm_provider" not in columns:
            batch_op.add_column(sa.Column("llm_provider", sa.String(length=64), nullable=True))
        if "llm_model" not in columns:
            batch_op.add_column(sa.Column("llm_model", sa.String(length=128), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "agent_messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agent_messages")}
    with op.batch_alter_table("agent_messages", schema=None) as batch_op:
        if "llm_model" in columns:
            batch_op.drop_column("llm_model")
        if "llm_provider" in columns:
            batch_op.drop_column("llm_provider")
        if "response_cards_json" in columns:
            batch_op.drop_column("response_cards_json")
