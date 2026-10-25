"""faq norm and publish columns

Revision ID: b0c22daa6693
Revises: 34ed260c59ff
Create Date: 2026-10-23

FAQ 增加：question_norm（规范化问题，精确命中缓存）、published_by / published_at、mine_group_key（挖掘去重）。
手写约束名，便于 downgrade。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0c22daa6693"
down_revision: str | None = "34ed260c59ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("faqs", sa.Column("question_norm", sa.Text(), nullable=True))
    op.add_column("faqs", sa.Column("published_by", sa.BigInteger(), nullable=True))
    op.add_column("faqs", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("faqs", sa.Column("mine_group_key", sa.String(length=64), nullable=True))
    op.create_foreign_key("fk_faqs_published_by", "faqs", "users", ["published_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_faqs_question_norm", "faqs", ["question_norm"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_faqs_question_norm", table_name="faqs")
    op.drop_constraint("fk_faqs_published_by", "faqs", type_="foreignkey")
    op.drop_column("faqs", "mine_group_key")
    op.drop_column("faqs", "published_at")
    op.drop_column("faqs", "published_by")
    op.drop_column("faqs", "question_norm")
