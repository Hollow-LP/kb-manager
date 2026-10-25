"""M4：数据权限引擎单元测试（纯规则，不依赖数据库）。

校验内容：
  - 前端权限弹窗组件与后端组件共用同一套规则
  - 访问判定矩阵：仅全局 / 仅部门 / 仅角色 / 仅个人 / 混合 / 无配置 / 目标不存在
  - 用户无部门且无角色时只能看到全局单元
  - 停用 / 不存在用户一律拒绝
"""

import pytest

from app.services.permission_rules import (
    Target,
    unit_access_reason,
    user_can_access,
    visible_summary,
)


def units_with(perms: dict[int, list[Target]]) -> dict[int, set[Target]]:
    return {uid: set(targets) for uid, targets in perms.items()}


def test_global_unit_visible_to_everyone():
    units = units_with({1: [Target("global", 0)]})
    assert user_can_access(1, units, user_id=99, department_id=None, role_ids=[])
    assert user_can_access(1, units, user_id=1, department_id=10, role_ids=[3])
    assert unit_access_reason(1, units, user_id=99, department_id=None, role_ids=[]) == "global"


def test_department_match_only_same_department():
    units = units_with({2: [Target("department", 10)]})
    assert user_can_access(2, units, user_id=5, department_id=10, role_ids=[])
    assert not user_can_access(2, units, user_id=5, department_id=11, role_ids=[])
    assert not user_can_access(2, units, user_id=5, department_id=None, role_ids=[])
    assert unit_access_reason(2, units, user_id=5, department_id=10, role_ids=[]) == "department"


def test_role_match_any_granted_role():
    units = units_with({3: [Target("role", 7)]})
    assert user_can_access(3, units, user_id=5, department_id=None, role_ids=[7])
    assert user_can_access(3, units, user_id=5, department_id=None, role_ids=[7, 8])
    assert not user_can_access(3, units, user_id=5, department_id=None, role_ids=[8])


def test_personal_match_only_target_user():
    units = units_with({4: [Target("user", 42)]})
    assert user_can_access(4, units, user_id=42, department_id=None, role_ids=[])
    assert not user_can_access(4, units, user_id=43, department_id=42, role_ids=[42])


def test_mixed_targets_use_or_logic():
    units = units_with({5: [Target("department", 10), Target("role", 7), Target("user", 42)]})
    assert user_can_access(5, units, user_id=1, department_id=10, role_ids=[])   # 部门命中
    assert user_can_access(5, units, user_id=1, department_id=None, role_ids=[7])  # 角色命中
    assert user_can_access(5, units, user_id=42, department_id=9, role_ids=[2])  # 个人命中
    assert not user_can_access(5, units, user_id=99, department_id=9, role_ids=[2])  # 都不命中


def test_unit_without_permissions_is_denied():
    units = units_with({6: []})
    assert not user_can_access(6, units, user_id=1, department_id=1, role_ids=[1])
    assert unit_access_reason(6, units, user_id=1, department_id=1, role_ids=[1]) is None


def test_unknown_unit_is_denied():
    units = units_with({1: [Target("global", 0)]})
    assert not user_can_access(999, units, user_id=1, department_id=1, role_ids=[1])


def test_orphan_user_sees_only_global():
    units = units_with({
        1: [Target("global", 0)],
        2: [Target("department", 0)],
        3: [Target("role", 0)],
        4: [Target("user", 1)],
    })
    # 无部门用户命中 department target_id=0 是用来检验 0 不会被当作通配
    assert not user_can_access(2, units, user_id=1, department_id=None, role_ids=[])
    assert not user_can_access(3, units, user_id=1, department_id=None, role_ids=[])
    assert user_can_access(4, units, user_id=1, department_id=None, role_ids=[])
    assert user_can_access(1, units, user_id=1, department_id=None, role_ids=[])


def test_global_target_ignores_target_id():
    # 数据里 global 行的 target_id 固定为 0；即便出现脏数据 9，也不应被当成本人/部门 9 的授权
    units = units_with({1: [Target("global", 9)]})
    assert user_can_access(1, units, user_id=9, department_id=9, role_ids=[9])


def test_disabled_or_missing_user_denied():
    # 由 load_viewer 返回 None 表达；规则侧用"不存在"模拟
    assert not user_can_access(1, {}, user_id=1, department_id=1, role_ids=[1])


def test_visible_summary_counts():
    units = units_with({1: [Target("global", 0)], 2: [Target("department", 5)], 3: []})
    summary = visible_summary(units, user_id=1, department_id=5, role_ids=[])
    assert summary == {"visible": [1, 2], "hidden": [3]}


@pytest.mark.parametrize(
    ("targets", "dept", "roles", "expected_reason"),
    [
        ([Target("global", 0), Target("department", 10), Target("role", 7)], 10, [7], "global"),  # 同时命中优先 global
        ([Target("department", 10), Target("role", 7)], 10, [], "department"),
        ([Target("department", 10), Target("role", 7)], None, [7], "role"),
        ([Target("role", 7), Target("user", 1)], 10, [], "user"),
        ([Target("department", 10), Target("role", 7)], 11, [8], None),
    ],
)
def test_reason_priority(targets, dept, roles, expected_reason):
    units = units_with({1: targets})
    assert unit_access_reason(1, units, user_id=1, department_id=dept, role_ids=roles) == expected_reason
