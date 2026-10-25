"""导入文件的本地存储：backend/storage/uploads/{yyyyMM}/{uuid}.{ext}。"""

import uuid
from datetime import datetime
from pathlib import Path

from app.config import get_settings


def storage_root() -> Path:
    root = get_settings().storage_path
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_upload(file_name: str, data: bytes) -> str:
    """保存文件，返回相对 storage_root 的路径（写入数据库，跨机器迁移时只依赖相对路径）。"""
    suffix = Path(file_name).suffix.lower()
    rel = Path(datetime.now().strftime("%Y%m")) / f"{uuid.uuid4().hex}{suffix}"
    target = storage_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return rel.as_posix()


def read_stored(rel_path: str) -> bytes:
    return (storage_root() / rel_path).read_bytes()


def remove_stored(rel_path: str | None) -> None:
    if not rel_path:
        return
    try:
        (storage_root() / rel_path).unlink(missing_ok=True)
    except OSError:
        pass
