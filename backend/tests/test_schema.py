"""M1：模型元数据与数据表约定测试（不依赖数据库）。"""

from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from app.db import Base
import app.models  # noqa: F401

REQUIRED_TABLES = {
    "users", "departments", "roles", "user_roles", "role_permissions", "knowledge_units",
    "unit_permissions", "qa_access_logs", "faqs", "knowledge_gaps",
}
REQUIRED_COLUMNS = {
    "users": {"id", "username", "password_hash", "display_name", "department_id", "status", "created_at", "updated_at"},
    "departments": {"id", "parent_id", "name", "leader_id", "sort_order", "created_at", "updated_at"},
    "roles": {"id", "role_name", "role_code", "description", "created_at", "updated_at"},
    "user_roles": {"id", "user_id", "role_id", "created_at"},
    "role_permissions": {"id", "role_id", "permission_code", "permission_type", "created_at"},
    "knowledge_units": {"id", "unit_code", "title", "content", "summary", "category", "source_file_name",
                        "file_type", "file_size", "status", "creator_id", "created_at", "updated_at"},
    "unit_permissions": {"id", "unit_id", "target_type", "target_id", "created_at"},
    "qa_access_logs": {"id", "session_id", "user_id", "question", "answer", "recalled_unit_ids_json",
                       "authorized_unit_ids_json", "unauthorized_unit_ids_json", "prompt_tokens",
                       "completion_tokens", "total_tokens", "response_time_ms", "created_at"},
    "faqs": {"id", "question", "answer", "category", "related_unit_id", "source_type", "status", "hit_count",
             "reviewer_id", "reviewed_at", "created_at", "updated_at"},
    "knowledge_gaps": {"id", "question_pattern", "sample_questions_json", "ask_count", "last_asked_at", "status",
                       "resolved_unit_id", "created_at", "updated_at"},
}


def test_required_tables_present():
    assert REQUIRED_TABLES <= set(Base.metadata.tables)
    assert len(Base.metadata.tables) == 14


def test_required_columns_present():
    for table, columns in REQUIRED_COLUMNS.items():
        actual = set(Base.metadata.tables[table].columns.keys())
        missing = columns - actual
        assert not missing, f"{table} 缺少列 {missing}"


def test_permission_dictionary_consistency():
    for code, (_, _, parent) in ALL_PERMISSIONS.items():
        if parent:
            assert parent in ALL_PERMISSIONS, f"{code} 的父权限 {parent} 不存在"
    for role, codes in DEFAULT_ROLE_PERMISSIONS.items():
        assert set(codes) <= set(ALL_PERMISSIONS), f"{role} 存在未知权限码"
    assert {"ai:chat:view", "knowledge:ai:access"} <= set(DEFAULT_ROLE_PERMISSIONS["normal_user"])
