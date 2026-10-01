from reg.settings import Settings


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("REG_DATABASE_URL", "postgresql://a:b@h:1/d")
    monkeypatch.setenv("REG_LAWGO_OC", "oc1")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql://a:b@h:1/d"
    assert s.lawgo_oc == "oc1"
    assert s.alio_min_interval == 1.5
    assert s.s3_bucket == "regulation"
