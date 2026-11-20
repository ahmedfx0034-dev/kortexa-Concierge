import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

from carousel_studio import config, store
from carousel_studio.campaign import (apply_reviews, assign_week, attach_drafts_to_slots, fill_slot,
                                      load_calendar, open_slots, plan_month, publish_due)
from carousel_studio.campaign import publisher
from carousel_studio.models import CarouselDraft, DraftStatus, Idea, Slide

START = date(2026, 11, 24)
TIMES = ["08:30", "13:00", "19:30"]


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(config, "STYLES_DIR", tmp_path / "styles")
    monkeypatch.setattr(store, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(store, "STYLES_DIR", tmp_path / "styles")
    (tmp_path / "drafts").mkdir()
    (tmp_path / "styles").mkdir()
    return tmp_path


def mk(did, style="a", status=DraftStatus.approved, created="2026-11-01T00:00:00+00:00"):
    d = CarouselDraft(id=did, style=style, idea=Idea(title=f"T {did}", angle="x", hook="h"),
                      slides=[Slide(index=i, archetype="a", layout="center_statement", heading="H",
                                    rendered_path=f"slide_0{i}.png") for i in (1, 2)],
                      caption="cap", hashtags=["#x"], status=status, created_at=created)
    store.save_draft(d)
    return d


def test_old_draft_json_loads():
    d = CarouselDraft.model_validate_json(json.dumps({
        "id": "o", "style": "s", "idea": {"title": "t", "angle": "a", "hook": "h"},
        "slides": [], "caption": "c"}))
    assert d.scheduled_at is None and d.image_urls == [] and d.published_at is None


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6])
def test_plan_rotation_balance(n):
    styles = [f"s{i}" for i in range(n)]
    cal = plan_month(START, days=30, times=TIMES, styles=styles)
    assert len(cal.slots) == 90 and cal.slots[0].id == "2026-11-24-1"
    wk1 = [s for s in cal.slots if s.date < "2026-12-01"]
    later = [s for s in cal.slots if s.date >= "2026-12-01"]
    assert all(s.style is None and s.arm is None for s in later)
    assert all(s.arm == "explore" for s in wk1)
    counts = Counter(s.style for s in wk1)
    assert set(counts) == set(styles) and max(counts.values()) - min(counts.values()) <= 1
    for t in TIMES:
        c = Counter(s.style for s in wk1 if s.time == t)
        assert set(c) == set(styles) if n <= 7 else True
        assert max(c.values()) - min(c.values()) <= 1


def test_plan_idempotent_and_per_day():
    plan_month(START, days=3, per_day=[2, 3], styles=["a", "b"], times=TIMES)
    assert [len([s for s in load_calendar().slots if s.date == f"2026-11-{d}"]) for d in (24, 25, 26)] == [2, 3, 2]
    fill_slot_cal = load_calendar()
    plan_month(START, days=3, per_day=[2, 3], styles=["a", "b"], times=TIMES)
    assert len(load_calendar().slots) == len(fill_slot_cal.slots)


def test_assign_week_shares():
    plan_month(START, days=30, times=TIMES, styles=["a", "b", "c"])
    wk = date(2026, 12, 1)
    changed = assign_week(wk, "a", ["b", "c"], champion_share=0.6)
    assert len(changed) == 21
    c = Counter(s.style for s in changed)
    assert abs(c["a"] / 21 - 0.6) <= 0.08
    assert abs(c["b"] - c["c"]) <= 1
    for t in TIMES:
        col = [s for s in changed if s.time == t]
        k = sum(s.style == "a" for s in col)
        assert abs(k - 0.6 * len(col)) <= 1
    assert {s.arm for s in changed} == {"champion", "challenger"}
    # persisted, and the other weeks untouched
    cal = load_calendar()
    assert all(s.style is None for s in cal.slots if s.date >= "2026-12-08")


def test_attach_and_open_slots():
    plan_month(START, days=2, times=TIMES, styles=["a", "b"])
    mk("d1", "a", created="2026-11-01T00:00:00+00:00")
    mk("d2", "a", created="2026-11-02T00:00:00+00:00")
    mk("d3", "zzz")
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    res = attach_drafts_to_slots(now=now)
    assert {r["draft_id"] for r in res} == {"d1", "d2"}
    d1, d2 = store.load_draft("d1"), store.load_draft("d2")
    assert d1.slot_id < d2.slot_id or d1.scheduled_at < d2.scheduled_at
    assert d1.scheduled_at.endswith("+00:00") and d1.experiment_arm == "explore"
    assert store.load_draft("d3").slot_id is None
    assert load_calendar().get(d1.slot_id).status == "filled"
    assert d1.slot_id not in [s.id for s in open_slots(style="a")]
    assert attach_drafts_to_slots(now=now) == []


def _setup_due(draft_status=DraftStatus.approved):
    plan_month(START, days=1, times=TIMES, styles=["a"])
    mk("d1", status=draft_status)
    fill_slot("2026-11-24-1", "d1")  # 08:30 Accra == UTC


@pytest.fixture
def fakes(monkeypatch):
    calls = {"render": 0, "upload": 0, "publish": 0}

    def render(d):
        calls["render"] += 1
        return d

    def upload(d):
        calls["upload"] += 1
        return [f"https://cdn.test/{d.id}/{i}.jpg" for i in (1, 2)]

    def pub(did, image_urls=None):
        calls["publish"] += 1
        d = store.load_draft(did)
        d.status, d.ig_media_id, d.ig_permalink = DraftStatus.published, "m1", "https://ig/p/1"
        store.save_draft(d)
        return d

    monkeypatch.setattr(publisher, "_render", render)
    monkeypatch.setattr(publisher, "upload_images", upload)
    monkeypatch.setattr(publisher, "publish_draft", pub)
    return calls


def test_publish_due_happy_path(fakes):
    _setup_due()
    now = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
    dry = publish_due(now=now, dry_run=True)
    assert dry[0]["action"] == "would_post" and fakes["publish"] == 0
    assert load_calendar().get("2026-11-24-1").status == "filled"
    res = publish_due(now=now)
    assert res[0]["action"] == "posted"
    assert fakes["render"] == 1 and fakes["upload"] == 1 and fakes["publish"] == 1  # PNGs absent -> rendered
    d = store.load_draft("d1")
    assert d.status == DraftStatus.published and d.published_at and d.image_urls[0].startswith("https://cdn")
    assert load_calendar().get("2026-11-24-1").status == "posted"
    assert publish_due(now=now) == []  # nothing left


def test_publish_not_yet_due(fakes):
    _setup_due()
    assert publish_due(now=datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)) == []


def test_publish_stale_skipped(fakes):
    _setup_due()
    res = publish_due(now=datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc))
    assert res[0]["action"] == "skipped" and res[0]["reason"] == "stale"
    s = load_calendar().get("2026-11-24-1")
    assert s.status == "skipped" and s.reason == "stale" and fakes["publish"] == 0


def test_publish_unapproved(fakes):
    _setup_due(DraftStatus.draft)
    assert publish_due(now=datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc))[0]["action"] == "waiting"
    assert load_calendar().get("2026-11-24-1").status == "filled"
    res = publish_due(now=datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc))
    assert res[0]["reason"] == "not approved"
    assert load_calendar().get("2026-11-24-1").reason == "not approved"
    assert fakes["publish"] == 0


def test_publish_24h_cap_and_max_posts(fakes):
    _setup_due()
    now = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
    for i in range(25):
        d = mk(f"old{i}", status=DraftStatus.published)
        d.published_at = (now - timedelta(hours=3)).isoformat()
        store.save_draft(d)
    res = publish_due(now=now)
    assert res[0]["action"] == "deferred" and "25" in res[0]["reason"] and fakes["publish"] == 0
    # posts older than 24h don't count
    d = store.load_draft("old0")
    d.published_at = (now - timedelta(hours=30)).isoformat()
    store.save_draft(d)
    assert publish_due(now=now)[0]["action"] == "posted"


def test_publish_max_posts(fakes):
    plan_month(START, days=1, times=["08:00", "08:30", "09:00"], styles=["a"])
    for i in (1, 2, 3):
        mk(f"d{i}")
        fill_slot(f"2026-11-24-{i}", f"d{i}")
    res = publish_due(now=datetime(2026, 11, 24, 9, 30, tzinfo=timezone.utc), max_posts=2)
    assert [r["action"] for r in res] == ["posted", "posted", "deferred"]


def test_apply_reviews(tmp_path):
    plan_month(START, days=1, times=TIMES, styles=["a"])
    for i in (1, 2, 3):
        mk(f"r{i}", status=DraftStatus.draft)
        fill_slot(f"2026-11-24-{i}", f"r{i}")
    p = tmp_path / "reviews.json"
    p.write_text(json.dumps([
        {"draft_id": "r1", "decision": "approve", "caption": "New cap", "hashtags": ["#a", "#b"]},
        {"draft_id": "r2", "decision": "reject"},
        {"draft_id": "r3", "decision": "revise", "feedback": "shorter"},
        {"draft_id": "nope", "decision": "approve"},
    ]))
    out = apply_reviews(p)
    assert [o["result"] for o in out] == ["approve", "reject", "revise", "error"]
    r1, r2, r3 = (store.load_draft(f"r{i}") for i in (1, 2, 3))
    assert r1.status == DraftStatus.approved and r1.caption == "New cap" and r1.hashtags == ["#a", "#b"]
    assert r2.status == DraftStatus.rejected and r2.slot_id is None
    assert r3.status == DraftStatus.draft and r3.feedback == "shorter" and r3.slot_id
    cal = load_calendar()
    assert cal.get("2026-11-24-2").status == "open" and cal.get("2026-11-24-2").draft_id is None
    assert cal.get("2026-11-24-3").draft_id == "r3" and cal.get("2026-11-24-1").status == "filled"


def test_campaign_cli_importable():
    from carousel_studio.campaign.cli import campaign_app
    assert campaign_app.registered_commands
