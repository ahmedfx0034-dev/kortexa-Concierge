from carousel_studio import config
from carousel_studio.campaign import post_log


def test_log_appends_and_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    post_log.log_event({"slot_id": "2026-11-24-1", "action": "posted", "title": "A | B",
                        "style": "kortexa-dark", "permalink": "https://instagram.com/p/x"})
    post_log.log_event({"slot_id": "2026-11-24-2", "action": "failed", "title": "C",
                        "style": "kortexa-bold", "reason": "boom"})
    rows = post_log.read_log()
    assert [r["action"] for r in rows] == ["posted", "failed"]
    md = (tmp_path / "campaign" / "POST_LOG.md").read_text()
    assert md.index("boom") < md.index("instagram.com/p/x")  # newest first
    assert "A / B" in md


def test_connections_placeholders(tmp_path, monkeypatch):
    import json
    from carousel_studio import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "BRAND_FILE", tmp_path / "brand.json")
    monkeypatch.setattr(config, "STYLES_DIR", tmp_path / "styles")
    monkeypatch.setattr(config, "DRAFTS_DIR", tmp_path / "drafts")
    for k in ("IG_ACCESS_TOKEN", "IG_USER_ID", "BLOB_READ_WRITE_TOKEN", "APIFY_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "connections.json").write_text(json.dumps(
        {"ig_user_id": "1784", "blob_store_id": "abc123", "secrets_via_proxy": True}))
    s = config.get_settings()
    assert s.ig_user_id == "1784"
    assert s.ig_access_token == config.PROXY_PLACEHOLDER
    assert s.blob_token == "vercel_blob_rw_abc123_proxy-injected"
    from vercel.blob._internal.credentials import store_from_read_write_token
    assert store_from_read_write_token(s.blob_token) == "abc123"
