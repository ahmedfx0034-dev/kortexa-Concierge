import json
import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="studio_test_")
os.environ["STUDIO_DATA_DIR"] = _TMP
os.environ["IG_USER_ID"] = "1789"
os.environ["IG_ACCESS_TOKEN"] = "tok"
os.environ["IMAGE_HOST"] = "local"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
os.environ.pop("REVIEW_PASSWORD", None)

import pytest
from PIL import Image

try:
    import httpx
except ImportError:
    import httpx2 as httpx

from carousel_studio import config, store
from carousel_studio.models import CarouselDraft, DraftStatus, Idea, Slide
from carousel_studio.publish import PublishError, publish_draft, upload_images
from carousel_studio.publish import instagram


from carousel_studio.publish import hosting as hosting_mod


def _patch_settings(monkeypatch, module, **kw):
    orig = module.get_settings

    def gs():
        s = orig()
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    monkeypatch.setattr(module, "get_settings", gs)


def make_draft(draft_id="d1", n=3, status=DraftStatus.approved):
    d = store.draft_dir(draft_id)
    slides = []
    for i in range(1, n + 1):
        p = d / f"slide_{i:02d}.png"
        Image.new("RGB", (1080, 1350), (20 * i, 40, 90)).save(p)
        slides.append(Slide(index=i, archetype="a", layout="center_statement",
                            heading=f"H{i}", rendered_path=str(p)))
    draft = CarouselDraft(id=draft_id, style="s", idea=Idea(title="T", angle="A", hook="H"),
                          slides=slides, caption="Hello", hashtags=["#one", "two"], status=status)
    store.save_draft(draft)
    return draft


class FakeGraph:
    def __init__(self, fail_at=None, statuses=("IN_PROGRESS", "FINISHED")):
        self.calls = []
        self.fail_at = fail_at
        self.statuses = list(statuses)

    def handler(self, request):
        from urllib.parse import parse_qs
        path = request.url.path
        q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
        self.calls.append((request.method, path, {**q, **form}))
        if self.fail_at and path.endswith(self.fail_at):
            return httpx.Response(400, json={"error": {"message": "Bad image", "code": 9004, "error_subcode": 2207052}})
        if request.method == "POST" and path.endswith("/1789/media"):
            if form.get("media_type") == "CAROUSEL":
                return httpx.Response(200, json={"id": "container1"})
            return httpx.Response(200, json={"id": f"child{sum(1 for c in self.calls if c[0]=='POST')}"})
        if path.endswith("/container1"):
            return httpx.Response(200, json={"status_code": self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "media9"})
        if path.endswith("/media9"):
            return httpx.Response(200, json={"permalink": "https://instagram.com/p/xyz/"})
        if path.endswith("/1789"):
            return httpx.Response(200, json={"username": "kortexa", "media_count": 5})
        if path.endswith("content_publishing_limit"):
            return httpx.Response(200, json={"data": [{"quota_usage": 1}]})
        return httpx.Response(404, json={"error": {"message": "unexpected " + path}})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_upload_local_creates_jpegs():
    draft = make_draft("up1", 2)
    urls = upload_images(draft)
    assert urls == ["https://example.test/drafts/up1/slide_01.jpg", "https://example.test/drafts/up1/slide_02.jpg"]
    with Image.open(store.DRAFTS_DIR / "up1" / "slide_01.jpg") as im:
        assert im.format == "JPEG" and im.size == (1080, 1350)


def test_upload_s3(monkeypatch):
    draft = make_draft("s3a", 2)
    _patch_settings(monkeypatch, hosting_mod, image_host="s3", s3_bucket="bkt", s3_public_base_url="https://cdn.test/")
    puts = []

    class C:
        def put_object(self, **kw):
            puts.append(kw)

    urls = upload_images(draft, s3_client=C())
    assert urls[0] == "https://cdn.test/carousels/s3a/slide_01.jpg"
    assert puts[0]["ContentType"] == "image/jpeg" and puts[0]["Key"] == "carousels/s3a/slide_01.jpg"
    assert puts[0]["Body"][:2] == b"\xff\xd8"


def test_publish_full_sequence():
    make_draft("p1", 3)
    g = FakeGraph()
    d = publish_draft("p1", client=g.client(), sleep=lambda s: None)
    assert d.status == DraftStatus.published and d.ig_media_id == "media9"
    assert d.ig_permalink == "https://instagram.com/p/xyz/"
    assert store.load_draft("p1").status == DraftStatus.published
    posts = [c for c in g.calls if c[0] == "POST"]
    assert [c[1].split("/")[-1] for c in posts] == ["media"] * 4 + ["media_publish"]
    assert posts[0][2]["is_carousel_item"] == "true" and posts[0][2]["image_url"].endswith("slide_01.jpg")
    carousel = posts[3][2]
    assert carousel["media_type"] == "CAROUSEL" and len(carousel["children"].split(",")) == 3
    assert carousel["caption"] == "Hello\n\n#one #two"
    assert posts[4][2]["creation_id"] == "container1"
    assert all(c[2]["access_token"] == "tok" for c in g.calls)


def test_publish_graph_error_marks_failed():
    make_draft("p2", 3)
    g = FakeGraph(fail_at="/1789/media")
    d = publish_draft("p2", client=g.client(), sleep=lambda s: None)
    assert d.status == DraftStatus.failed and "Bad image" in d.error and "9004" in d.error
    assert store.load_draft("p2").status == DraftStatus.failed


def test_publish_container_error_status():
    make_draft("p3", 2)
    g = FakeGraph(statuses=("ERROR",))
    d = publish_draft("p3", client=g.client(), sleep=lambda s: None)
    assert d.status == DraftStatus.failed and "ERROR" in d.error


def test_publish_poll_timeout():
    make_draft("p4", 2)
    g = FakeGraph(statuses=("IN_PROGRESS",))
    d = publish_draft("p4", client=g.client(), sleep=lambda s: None, poll_timeout=8, poll_interval=4)
    assert d.status == DraftStatus.failed and "Timed out" in d.error


def test_publish_requires_approved():
    make_draft("p5", 3, status=DraftStatus.draft)
    g = FakeGraph()
    with pytest.raises(PublishError):
        publish_draft("p5", client=g.client())
    assert g.calls == []


def test_publish_slide_limits(monkeypatch):
    make_draft("p6", 11)
    with pytest.raises(PublishError, match="2-10"):
        publish_draft("p6", client=FakeGraph().client())
    monkeypatch.setenv("IG_MAX_SLIDES", "20")
    assert publish_draft("p6", client=FakeGraph().client(), sleep=lambda s: None).status == DraftStatus.published
    make_draft("p7", 1)
    with pytest.raises(PublishError):
        publish_draft("p7", client=FakeGraph().client())


def test_missing_credentials(monkeypatch):
    _patch_settings(monkeypatch, instagram, ig_user_id=None)
    with pytest.raises(PublishError, match="IG_USER_ID"):
        instagram.verify_credentials()


def test_verify_and_limit():
    g = FakeGraph()
    assert instagram.verify_credentials(g.client())["username"] == "kortexa"
    assert "data" in instagram.check_publishing_limit(g.client())


# ------------------------------------------------------------------ review app
from fastapi.testclient import TestClient

from carousel_studio.review import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_list_and_detail(client):
    make_draft("r1", 3, status=DraftStatus.draft)
    r = client.get("/")
    assert r.status_code == 200 and "r1" in r.text and "Generate new drafts" in r.text
    r = client.get("/drafts/r1")
    assert r.status_code == 200 and "slide_01.png" in r.text and "Hello" in r.text
    assert "Publish to Instagram" not in r.text
    assert client.get("/drafts/nope").status_code == 404
    assert client.get("/drafts-files/r1/slide_01.png").status_code == 200
    assert client.get("/drafts-files/r1/draft.json").status_code == 404
    assert client.get("/drafts/r1/slide_01.jpg").status_code in (200, 404)


def test_caption_approve_reject_publish(client, monkeypatch):
    make_draft("r2", 3, status=DraftStatus.draft)
    client.post("/drafts/r2/caption", data={"caption": "New text\nline two\n\n#a #b"}, follow_redirects=False)
    d = store.load_draft("r2")
    assert d.caption == "New text\nline two" and d.hashtags == ["a", "b"]
    assert client.post("/drafts/r2/approve", follow_redirects=False).status_code == 303
    assert store.load_draft("r2").status == DraftStatus.approved
    assert "Publish to Instagram" in client.get("/drafts/r2").text

    g = FakeGraph()
    real = httpx.Client
    monkeypatch.setattr(instagram.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(g.handler)))
    monkeypatch.setattr(instagram.time, "sleep", lambda s: None)
    client.post("/drafts/r2/publish", follow_redirects=False)
    d = store.load_draft("r2")
    assert d.status == DraftStatus.published
    assert "https://instagram.com/p/xyz/" in client.get("/drafts/r2").text

    make_draft("r3", 2, status=DraftStatus.draft)
    client.post("/drafts/r3/reject")
    assert store.load_draft("r3").status == DraftStatus.rejected
    # publishing an unapproved draft never touches the API
    make_draft("r4", 2, status=DraftStatus.draft)
    client.post("/drafts/r4/publish")
    assert store.load_draft("r4").status == DraftStatus.draft


def test_basic_auth(monkeypatch):
    monkeypatch.setenv("REVIEW_PASSWORD", "pw")
    make_draft("a1", 2)
    c = TestClient(create_app())
    assert c.get("/").status_code == 401
    assert c.get("/", auth=("u", "pw")).status_code == 200
    assert c.get("/", auth=("u", "bad")).status_code == 401
    # public slide jpgs (IMAGE_HOST=local) stay reachable for Instagram
    upload_images(store.load_draft("a1"))
    assert c.get("/drafts/a1/slide_01.jpg").status_code == 200


def test_generate_and_revise_background(client, monkeypatch):
    import sys, types
    called = {}
    gen = types.ModuleType("carousel_studio.generate")
    gen.create_drafts = lambda style, n=3, theme=None: called.setdefault("gen", (style, n, theme)) and []
    gen.revise_draft = lambda did, fb: (called.setdefault("rev", (did, fb)), store.load_draft(did))[1]
    rnd = types.ModuleType("carousel_studio.render")
    rnd.render_draft = lambda d: d
    monkeypatch.setitem(sys.modules, "carousel_studio.generate", gen)
    monkeypatch.setitem(sys.modules, "carousel_studio.render", rnd)
    make_draft("g1", 2, status=DraftStatus.draft)
    client.post("/generate", data={"style": "x", "count": 2, "theme": "t"}, follow_redirects=False)
    assert called["gen"] == ("x", 2, "t")
    client.post("/drafts/g1/revise", data={"feedback": "punchier"})
    assert called["rev"] == ("g1", "punchier")
