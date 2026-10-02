from functools import lru_cache
from pathlib import Path

from typing import Literal

from pydantic import model_validator
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
    # 운영 Neo4j는 GPU PC(spec 2026-10-03 §0). REG_NEO4J_TARGET=gpu면 neo4j_url 대신 gpu_neo4j_url을 쓴다
    neo4j_target: Literal["local", "gpu"] = "local"
    gpu_neo4j_url: str = ""
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
    airflow_log_dir: str = ""  # reg_maintenance가 30일 지난 Airflow 태스크 로그를 지울 폴더 (compose: /opt/airflow/logs)
    converter_url: str = ""  # 비어 있으면 DockerConverter — docker run, 호스트 CLI —, 있으면 HttpConverter (compose 안)

    @model_validator(mode="after")
    def _neo4j_target(self):
        if self.neo4j_target == "gpu":
            if not self.gpu_neo4j_url:
                raise ValueError("REG_NEO4J_TARGET=gpu인데 REG_GPU_NEO4J_URL이 비어 있습니다")
            self.neo4j_url = self.gpu_neo4j_url
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
