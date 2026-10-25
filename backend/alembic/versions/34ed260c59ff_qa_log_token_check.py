"""qa log token check

Revision ID: 34ed260c59ff
Revises: 12f4b692728a
Create Date: 2026-10-23

为 qa_access_logs 增加 Token 口径约束：total_tokens = prompt_tokens + completion_tokens。
加约束前先修正历史不一致数据（早期演示数据存在总数写死的情况）。
"""
from collections.abc import Sequence

from alembic import op

revision: str = "34ed260c59ff"
down_revision: str | None = "12f4b692728a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE qa_access_logs SET total_tokens = prompt_tokens + completion_tokens "
        "WHERE total_tokens <> prompt_tokens + completion_tokens"
    )
    op.create_check_constraint(
        "ck_qa_access_logs_tokens", "qa_access_logs",
        "total_tokens = prompt_tokens + completion_tokens",
    )


def downgrade() -> None:
    op.drop_constraint("ck_qa_access_logs_tokens", "qa_access_logs", type_="check")
