"""下载本地 Embedding 模型到 backend/models/ 并在 .env 中指向该目录。

用法（开发机）：
    uv run python scripts/download_model.py
若 HF 直连不通（VM 常见），先在开发机建立反向代理隧道并在环境中设置：
    HTTPS_PROXY=http://127.0.0.1:7890 uv run python scripts/download_model.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "models" / "bge-small-zh-v1.5"


def main() -> int:
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    from sentence_transformers import SentenceTransformer

    print(f"下载模型到 {TARGET} ...")
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(TARGET))
    dim = model.get_sentence_embedding_dimension()
    print(f"完成，维度 {dim}。请在 backend/.env 设置 EMBEDDING_MODEL={TARGET.as_posix()}，EMBEDDING_DIM={dim}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
