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
