"""unit status archived and import job statuses

Revision ID: acd3a766e856
Revises: 54d489a855bb
Create Date: 2026-10-22 17:00:00+08:00

说明：模型为 knowledge_units.status 增加 'archived'，导入任务状态增加 'embedding'。
两者都是 VARCHAR + CHECK 约束；为避免在校验已有数据时失败，CHECK 约束在脚本中重建。
"""
from collections.abc import Sequence

from alembic import op

revision: str = "acd3a766e856"
down_revision: str | None = "54d489a855bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIT_CHECK_NEW = (
    "status IN ('parsing', 'active', 'disabled', 'parse_failed', 'archived')"
)
UNIT_CHECK_OLD = "status IN ('parsing', 'active', 'disabled', 'parse_failed')"


def upgrade() -> None:
    op.create_index("ix_knowledge_units_status_created", "knowledge_units", ["status", "created_at"], unique=False)
    op.drop_constraint("ck_knowledge_units_status", "knowledge_units", type_="check")
    op.create_check_constraint("ck_knowledge_units_status", "knowledge_units", UNIT_CHECK_NEW)


def downgrade() -> None:
    op.drop_constraint("ck_knowledge_units_status", "knowledge_units", type_="check")
    op.create_check_constraint("ck_knowledge_units_status", "knowledge_units", UNIT_CHECK_OLD)
    op.drop_index("ix_knowledge_units_status_created", table_name="knowledge_units")
