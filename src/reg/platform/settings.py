from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # 저장소 루트 (config/, docs/)
USER_AGENT = "NST-Regulation-Collector/0.1 (+contact: bigdatanigel1513@gmail.com)"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REG_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://reg_app:reg@127.0.0.1:21055/nst_regulation"
    migrator_url: str = "postgresql://reg_migrator:reg@127.0.0.1:21055/nst_regulation"
    s3_endpoint: str = "http://127.0.0.1:21053"
    s3_bucket: str = "regulation"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    lawgo_oc: str = ""
    alio_min_interval: float = 1.5
    lawgo_min_interval: float = 1.0
    os_url: str = "http://127.0.0.1:21067"
    neo4j_url: str = "bolt://127.0.0.1:21064"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 21068
    smtp_from: str = "NST 규정·법령 <no-reply@nst-regulation.local>"
    web_url: str = "http://192.168.0.3:21060"
    embed_url: str = "http://192.168.0.2:8002"
    embed_model: str = "bge-m3"
    rerank_url: str = "http://192.168.0.2:8003"
    rerank_model: str = "bge-reranker"
    llm_url: str = "http://192.168.0.2:8001"
    llm_model: str = "llm"
    mineru_url: str = ""  # GPU PC MinerU V1 API, 예: http://192.168.0.2:8004 (M6-5 OCR, M6-6 별표 표)
    mineru_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
