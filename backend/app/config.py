from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    """知识库管理平台运行配置，读取 backend/.env。"""

    app_env: Literal["dev", "prod"] = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    frontend_origins: str = "http://localhost:5173"

    database_url: str = "postgresql+psycopg://kb:kb@127.0.0.1:5432/kb_manager"
    redis_url: str = "redis://127.0.0.1:6379/0"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=720, gt=0)
    internal_service_token: str = "kb-internal-token"

    # 知识导入
    storage_dir: Path = Path("./storage/uploads")
    upload_max_size_mb: int = Field(default=50, ge=1, le=500)
    chunk_max_chars: int = Field(default=700, ge=100)
    import_workers: int = Field(default=2, ge=1, le=8)

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=90, gt=0)
    llm_max_tokens: int = Field(default=1024, ge=64)
    # 思考型模型的开关（SiliconFlow 的 XingChen 等通过 enable_thinking 控制）；非思考模型可忽略
    llm_enable_thinking: bool = False
    embedding_provider: Literal["local", "openai_compatible"] = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512

    # 重排（qwen3-rerank，DashScope 原生格式；留空则只用向量相似度）
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = "qwen3-rerank"
    rerank_top_n: int = Field(default=15, ge=2, le=50)
    rerank_min_score: float = Field(default=0.55, ge=0, le=1)
    rerank_timeout_seconds: float = Field(default=15, gt=0)

    retrieval_top_k: int = Field(default=6, ge=1, le=50)
    rrf_k: int = 60
    gap_score_threshold: float = 0.45
    faq_similarity_threshold: float = 0.92
    faq_mine_similarity: float = 0.88
    mining_enabled: bool = True
    faq_mine_threshold: int = Field(default=3, ge=1)
    faq_mine_lookback_days: int = Field(default=30, ge=1)
    mining_cron: str = "0 2 * * *"
    missing_hint_mode: Literal["unit_title", "count_only"] = "unit_title"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        """相对路径按 backend/ 目录解析，避免依赖进程工作目录。"""
        return self.storage_dir if self.storage_dir.is_absolute() else (ENV_FILE.parent / self.storage_dir).resolve()

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
