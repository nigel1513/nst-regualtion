from reg.platform.settings import Settings


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("REG_DATABASE_URL", "postgresql://a:b@h:1/d")
    monkeypatch.setenv("REG_LAWGO_OC", "oc1")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql://a:b@h:1/d"
    assert s.lawgo_oc == "oc1"
    assert s.alio_min_interval == 1.5
    assert s.s3_bucket == "regulation"


def test_neo4j_target_gpu_switches_url(monkeypatch):
    import pytest

    monkeypatch.delenv("REG_NEO4J_URL", raising=False)
    monkeypatch.setenv("REG_GPU_NEO4J_URL", "bolt://10.0.0.2:8006")
    assert Settings(_env_file=None).neo4j_url == "bolt://127.0.0.1:21064"
    monkeypatch.setenv("REG_NEO4J_TARGET", "gpu")
    assert Settings(_env_file=None).neo4j_url == "bolt://10.0.0.2:8006"
    monkeypatch.delenv("REG_GPU_NEO4J_URL")
    with pytest.raises(ValueError, match="GPU_NEO4J_URL"):
        Settings(_env_file=None)
