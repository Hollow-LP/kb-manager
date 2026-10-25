"""数据权限规则（纯函数，无数据库依赖）。

SQL 版规则在 app/services/knowledge.py (`ACCESSIBLE_UNITS_SQL`)；这里保持一份等价的纯 Python 实现：
  - 作为 SQL 的对照实现，供单测覆盖全部判定分支；
  - 前端需要在前端本地判断时，照此规则实现（前端 `unitAccessible` 与此一致）。

规则（与需求 2.9.4 一致）：
  1. 单元未配置任何权限实体 → 任何人不可访问（默认无权限）
  2. 单元配置了实体 → 用户由部门 / 角色 / 个人 / 全局 任一命中即可访问（OR）
  3. global 实体不比较 target_id
  4. 用户无部门时不命中 department；用户无角色时不命中 role
"""

from dataclasses import dataclass, field
from typing import Iterable, Literal

TargetType = Literal["global", "department", "role", "user"]


@dataclass(frozen=True)
class Target:
    target_type: str
    target_id: int = 0

    def __post_init__(self) -> None:
        if self.target_type not in ("global", "department", "role", "user"):
            raise ValueError(f"unknown target_type: {self.target_type}")
        if self.target_type == "global" and self.target_id != 0:
            # 普通化：global 的 target_id 无意义，统一归零
            object.__setattr__(self, "target_id", 0)


UnitPermissions = dict[int, set[Target]]


@dataclass
class UserContext:
    user_id: int
    department_id: int | None = None
    role_ids: list[int] = field(default_factory=list)


def _matches(target: Target, user_id: int, department_id: int | None, role_ids: Iterable[int]) -> bool:
    if target.target_type == "global":
        return True
    if target.target_type == "department":
        return department_id is not None and target.target_id == department_id
    if target.target_type == "role":
        return target.target_id in set(role_ids)
    return target.target_id == user_id


REASON_PRIORITY = ("global", "department", "role", "user")


def unit_access_reason(unit_id: int, units: UnitPermissions, *, user_id: int,
                       department_id: int | None, role_ids: Iterable[int]) -> str | None:
    """返回命中的权限类型（按全局>部门>角色>个人优先级）；无权访问返回 None。"""
    targets = units.get(unit_id)
    if not targets:
        return None
    roles = set(role_ids)
    for reason in REASON_PRIORITY:
        for target in targets:
            if target.target_type == reason and _matches(target, user_id, department_id, roles):
                return reason
    return None


def user_can_access(unit_id: int, units: UnitPermissions, *, user_id: int,
                    department_id: int | None, role_ids: Iterable[int]) -> bool:
    return unit_access_reason(unit_id, units, user_id=user_id, department_id=department_id, role_ids=role_ids) is not None


def visible_summary(units: UnitPermissions, *, user_id: int, department_id: int | None,
                    role_ids: Iterable[int]) -> dict[str, list[int]]:
    roles = list(role_ids)
    visible, hidden = [], []
    for unit_id in sorted(units):
        if user_can_access(unit_id, units, user_id=user_id, department_id=department_id, role_ids=roles):
            visible.append(unit_id)
        else:
            hidden.append(unit_id)
    return {"visible": visible, "hidden": hidden}
