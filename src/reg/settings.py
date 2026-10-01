from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

USER_AGENT = "NST-Regulation-Collector/0.1 (+contact: bigdatanigel1513@gmail.com)"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REG_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://reg_app:reg@127.0.0.1:21055/nais"
    migrator_url: str = "postgresql://reg_migrator:reg@127.0.0.1:21055/nais"
    s3_endpoint: str = "http://127.0.0.1:21053"
    s3_bucket: str = "regulation"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    lawgo_oc: str = ""
    alio_min_interval: float = 1.5
    lawgo_min_interval: float = 1.0
    os_url: str = "http://127.0.0.1:21067"
    embed_url: str = "http://192.168.0.2:8002"
    embed_model: str = "bge-m3"
    rerank_url: str = "http://192.168.0.2:8003"
    rerank_model: str = "bge-reranker"
    llm_url: str = "http://192.168.0.2:8001"
    llm_model: str = "llm"


@lru_cache
def get_settings() -> Settings:
    return Settings()
