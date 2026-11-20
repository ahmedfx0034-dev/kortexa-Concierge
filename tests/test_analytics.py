import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from carousel_studio import config, store
from carousel_studio.analytics import insights, merge, paths, report
from carousel_studio.models import (CarouselDraft, Idea, Palette, SlideArchetype, StyleProfile,
                                    Typography)

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "STYLES_DIR", tmp_path / "styles")
    monkeypatch.setattr(config, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(store, "STYLES_DIR", tmp_path / "styles")
    monkeypatch.setattr(store, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setenv("IG_USER_ID", "999")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    return tmp_path


def make_draft(did, style="s1", media="m1", posted=T0):
    d = CarouselDraft(id=did, style=style, idea=Idea(title="t", angle="a", hook="h"),
                      slides=[], caption="c").model_dump(mode="json")
    d.update(status="published", ig_media_id=media, published_at=posted.isoformat(),
             updated_at=posted.isoformat())
    store.draft_dir(did)
    (config.DRAFTS_DIR / did / "draft.json").write_text(json.dumps(d))
    return store.load_draft(did)


def graph_client(unsupported=(), perm_error=False, calls=None):
    def handler(req: httpx.Request):
        if calls is not None:
            calls.append(req)
        assert req.headers["authorization"] == "Bearer tok"
        assert "access_token" not in req.url.query.decode()
        path = req.url.path
        if path.endswith("/insights"):
            if perm_error:
                return httpx.Response(400, json={"error": {"type": "OAuthException", "code": 10, "message": "nope"}})
            asked = req.url.params["metric"].split(",")
            if any(m in unsupported for m in asked):
                return httpx.Response(400, json={"error": {"code": 100, "message": "metric not supported"}})
            vals = {"reach": 1000, "saved": 10, "shares": 5, "likes": 50, "comments": 3,
                    "profile_visits": 20, "follows": 4, "total_interactions": 70, "views": 1500}
            return httpx.Response(200, json={"data": [
                {"name": m, "values": [{"value": vals[m]}]} for m in asked]})
        if path.endswith("/999"):
            return httpx.Response(200, json={"followers_count": 120, "media_count": 7})
        return httpx.Response(200, json={"like_count": 51, "comments_count": 4,
                                         "timestamp": "2026-01-01T12:00:00+0000"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_all_metrics(env):
    d = make_draft("d1")
    r = insights.fetch_insights(d, client=graph_client())
    assert r["reach"] == 1000 and r["follows"] == 4 and r["missing"] == []


def test_metric_fallback_one_unsupported(env):
    d = make_draft("d1")
    r = insights.fetch_insights(d, client=graph_client(unsupported=("views",)))
    assert r["views"] is None and "views" in r["missing"]
    assert r["reach"] == 1000 and r["saved"] == 10
    # likes unsupported -> filled from like_count fallback
    r = insights.fetch_insights(d, client=graph_client(unsupported=("likes", "comments")))
    assert r["likes"] == 51 and r["comments"] == 4


def test_permission_error_message(env):
    d = make_draft("d1")
    with pytest.raises(insights.InsightsPermissionError, match="instagram_manage_insights"):
        insights.fetch_insights(d, client=graph_client(perm_error=True))


def test_snapshot_all_and_account(env):
    make_draft("d1")
    c = graph_client()
    res = insights.snapshot_all(now=T0 + timedelta(hours=48), client=c)
    assert res["snapshotted"] == ["d1"]
    m = paths.read_json("metrics.json", {})
    assert m["d1"]["snapshots"][0]["hours_since_post"] == 48.0
    assert m["d1"]["style"] == "s1"
    insights.account_snapshot(now=T0, client=c)
    assert paths.read_json("account.json", [])[0]["followers_count"] == 120


def test_snapshot_selection_nearest_48h():
    snaps = [{"hours_since_post": h, "metrics": {}} for h in (6, 30, 50, 120)]
    s, early = report.pick_snapshot(snaps)
    assert s["hours_since_post"] == 50 and not early
    s, early = report.pick_snapshot(snaps[:2])
    assert s["hours_since_post"] == 30 and early


def test_scoring(env):
    goals = paths.load_goals()
    assert (env / "analytics" / "goals.json").exists()
    m = {"reach": 1000, "follows": 2, "profile_visits": 10, "shares": 1, "saved": 2, "comments": 1, "likes": 20}
    # 20+40+3+6+2+10 = 81 per 1000 reach
    assert report.score_metrics(m, goals) == pytest.approx(81.0)
    assert report.score_metrics({"follows": 1}, goals) == pytest.approx(10 * 1000)  # reach floor of 1
    # editable weights
    paths.write_json("goals.json", {"weights": {"follows": 1}})
    assert paths.load_goals()["weights"]["shares"] == 3.0
    assert report.score_metrics(m, paths.load_goals()) == pytest.approx(63.0)


def seed(styles: dict, start=T0):
    """styles: {name: [follows per post]} -> 1000 reach each, 48h snapshot."""
    data = {}
    i = 0
    for style, fl in styles.items():
        for f in fl:
            i += 1
            data[f"p{i}"] = {"style": style, "posted_at": (start + timedelta(days=i)).isoformat(),
                             "snapshots": [{"at": "x", "hours_since_post": 48.0,
                                            "metrics": {"reach": 1000, "follows": f}}]}
    paths.write_json("metrics.json", data)


def test_champion_selection(env):
    seed({"a": [1, 1, 1], "b": [3] * 5, "c": [2] * 5, "d": [1] * 5})
    rec = report.recommend(min_posts=5, now=T0 + timedelta(days=60))
    assert rec.champion is None and "a (3/5)" in rec.reasons[0]
    seed({"a": [1] * 5, "b": [3] * 5, "c": [2] * 5, "d": [0] * 5})
    rec = report.recommend(min_posts=5, now=T0 + timedelta(days=60))
    assert rec.champion == "b" and rec.challengers == ["c", "a"]
    assert rec.dropped == ["d"] or "d" in rec.dropped
    d = report.apply_decision(rec)
    assert d["champion"] == "b" and len(d["history"]) == 1
    assert report.load_champion()["champion"] == "b"


def test_challenger_keep_and_switch(env):
    paths.write_json("champion.json", {"champion": "a", "history": []})
    # b only 5% better -> keep
    seed({"a": [10, 11, 9, 10, 10], "b": [10, 11, 10, 11, 10]})
    rec = report.recommend(min_posts=5, now=T0 + timedelta(days=30))
    assert rec.champion == "a" and not rec.changed
    # b much better with a clearly separated interval -> switch
    seed({"a": [10, 11, 9, 10, 10], "b": [20, 22, 21, 19, 20]})
    rec = report.recommend(min_posts=5, now=T0 + timedelta(days=30))
    assert rec.champion == "b" and rec.changed and rec.previous_champion == "a"
    assert "Switching champion" in rec.reasons[0]
    # too few posts -> keep
    seed({"a": [10] * 5, "b": [30] * 3})
    assert report.recommend(min_posts=5, now=T0 + timedelta(days=30)).champion == "a"
    # >10% better but noisy and not recent -> keep
    seed({"a": [10] * 5, "b": [0, 0, 0, 0, 60]})
    rec = report.recommend(min_posts=5, now=T0 + timedelta(days=60))
    assert rec.champion == "a"
    assert any("not convincing" in r for r in rec.reasons)


def test_follower_growth_and_render(env):
    paths.write_json("account.json", [
        {"at": (T0 + timedelta(days=d)).isoformat(), "followers_count": 100 + 5 * d} for d in (0, 3, 7, 10, 14)])
    g = report.follower_growth()
    assert g["overall_per_day"] == pytest.approx(5.0)
    assert g["weeks"][0]["gained"] == 15
    seed({"a": [1] * 5, "b": [2] * 5})
    md, data = report.render_report(now=T0 + timedelta(days=30))
    assert "# Style experiment report" in md and data["styles"][0]["style"] == "b"
    json.dumps(data, default=str)


def _profile(name, bg, font, tone):
    return StyleProfile(
        name=name, summary="s",
        palette=Palette(background=bg, surface=bg, text=bg, muted_text=bg, accent=bg, accent_2=bg),
        typography=Typography(heading_font=font, body_font=font, heading_weight=700,
                              heading_case="upper", heading_size="xl"),
        archetypes=[SlideArchetype(name=name + "-hook", description="d", layout="center_statement")],
        decorations=[name + "-deco"], uses_photos=False, words_per_slide=20, slide_count=7,
        hook_patterns=[name + "-hook"], tone=tone, caption_style="short")


def test_merge(env):
    store.save_profile(_profile("alpha", "#111111", "Inter", "blunt"))
    store.save_profile(_profile("beta", "#FFFFFF", "Lora", "warm"))
    m = merge.merge_styles("alpha", "beta", "mix", {})
    assert m.palette.background == "#111111" and m.decorations == ["alpha-deco"]
    assert m.typography.heading_font == "Lora" and m.archetypes[0].name == "beta-hook"
    assert m.tone == "blunt" and "blend" in m.summary.lower()
    assert store.load_profile("mix").name == "mix"
    m2 = merge.merge_styles("alpha", "beta", "mix2", {"voice": "b", "palette": "b"})
    assert m2.tone == "warm" and m2.palette.background == "#FFFFFF"
    with pytest.raises(ValueError):
        merge.merge_styles("alpha", "beta", "x", {"palette": "c"})
