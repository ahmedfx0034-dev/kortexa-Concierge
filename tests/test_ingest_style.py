"""Tests for carousel_studio.ingest and carousel_studio.style (no network, no API keys)."""
import io
import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import carousel_studio.config as config  # noqa: E402
import carousel_studio.store as store  # noqa: E402
from carousel_studio import ingest, style  # noqa: E402
from carousel_studio.ingest import instagram  # noqa: E402
from carousel_studio.models import (  # noqa: E402
    Palette, ReferenceCarousel, ReferenceSource, SlideArchetype, StyleProfile, Typography,
)


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", d)
    monkeypatch.setattr(config, "STYLES_DIR", d / "styles")
    monkeypatch.setattr(config, "DRAFTS_DIR", d / "drafts")
    monkeypatch.setattr(config, "BRAND_FILE", d / "brand.json")
    monkeypatch.setattr(store, "STYLES_DIR", d / "styles")
    monkeypatch.setattr(store, "DRAFTS_DIR", d / "drafts")
    return d


def make_img(path: Path, color=(200, 30, 30), mode="RGB", fmt=None, size=(108, 135)):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = color if mode == "RGB" else color + (128,)
    Image.new(mode, size, c).save(path, format=fmt)
    return path


def jpeg_bytes(color):
    buf = io.BytesIO()
    Image.new("RGB", (100, 125), color).save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ local

def test_ingest_local_subfolders_natural_order(tmp_path):
    src = tmp_path / "shots"
    for i, name in enumerate(["slide10.png", "slide2.png", "slide1.jpg"]):
        make_img(src / "carousel_a" / name, color=(i * 50, 0, 0))
    make_img(src / "carousel_b" / "1.webp", fmt="WEBP", color=(0, 0, 255))
    make_img(src / "carousel_b" / "2.png", mode="RGBA", color=(0, 255, 0))
    (src / "carousel_b" / "notes.txt").write_text("ignore me")
    (src / "empty").mkdir()

    refs = ingest.ingest_local("Bold Dark", str(src))
    assert len(refs) == 2
    a = next(r for r in refs if r.origin.endswith("carousel_a"))
    assert [Path(p).name for p in a.slide_paths] == ["slide_01.jpg", "slide_02.jpg", "slide_03.jpg"]
    # natural order: slide1 (color 100), slide2 (50), slide10 (0)
    reds = [Image.open(p).getpixel((5, 5))[0] for p in a.slide_paths]
    assert reds[0] > reds[1] > reds[2]
    for r in refs:
        assert r.source == ReferenceSource.local
        for p in r.slide_paths:
            with Image.open(p) as im:
                assert im.format == "JPEG"
    stored = store.list_references("Bold Dark")
    assert {r.id for r in stored} == {r.id for r in refs}

    # re-ingesting the same folder is deduped
    assert ingest.ingest_local("Bold Dark", str(src)) == []


def test_ingest_local_loose_images(tmp_path):
    src = tmp_path / "loose"
    make_img(src / "b.png")
    make_img(src / "a.jpeg")
    refs = ingest.ingest_local("s", str(src))
    assert len(refs) == 1 and len(refs[0].slide_paths) == 2


def test_ingest_local_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest.ingest_local("s", str(tmp_path / "nope"))
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError):
        ingest.ingest_local("s", str(tmp_path / "empty"))


# ------------------------------------------------------------- parse_inputs

def test_parse_inputs(tmp_path):
    folders, posts, handles = ingest.parse_inputs([
        str(tmp_path),
        "https://www.instagram.com/p/ABC123/?img_index=1",
        "instagram.com/reel/XYZ/",
        "https://www.instagram.com/some.creator/",
        "@another_one",
    ])
    assert folders == [str(tmp_path)]
    assert len(posts) == 2
    assert handles == ["some.creator", "another_one"]
    with pytest.raises(ValueError):
        ingest.parse_inputs(["definitely/not/a/path/xyz"])


# ------------------------------------------------------------------ apify

class FakeResp:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code = status
        self._json = json_data
        self.content = content
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    gets = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        FakeClient.gets.append(url)
        if "broken" in url:
            return FakeResp(status=403)
        return FakeResp(content=jpeg_bytes((10, 20, 30)))


ITEMS = [
    {  # sidecar with childPosts incl. a video child
        "type": "Sidecar", "shortCode": "AAA111", "url": "https://www.instagram.com/p/AAA111/",
        "ownerUsername": "creator", "caption": "Top tips 👇 #growth", "likesCount": 900, "commentsCount": 100,
        "displayUrl": "https://cdn/a0.jpg",
        "childPosts": [
            {"type": "Image", "displayUrl": "https://cdn/a1.jpg"},
            {"type": "Video", "displayUrl": "https://cdn/a2-thumb.jpg", "videoUrl": "https://cdn/a2.mp4"},
            {"type": "Image", "displayUrl": "https://cdn/a3.jpg"},
        ],
    },
    {  # sidecar with only images list, lower engagement
        "type": "Sidecar", "shortCode": "BBB222", "ownerUsername": "creator",
        "likesCount": 50, "commentsCount": 1, "images": ["https://cdn/b1.jpg", "https://cdn/b2.jpg"],
    },
    {"type": "Video", "shortCode": "VVV", "ownerUsername": "creator", "likesCount": 99999,
     "displayUrl": "https://cdn/v.jpg"},
    {"type": "Image", "shortCode": "III", "ownerUsername": "creator", "likesCount": 99999,
     "displayUrl": "https://cdn/i.jpg"},
    {"type": "Sidecar", "shortCode": "CCC333", "ownerUsername": "creator", "likesCount": 500,
     "commentsCount": 0, "images": ["https://cdn/c1.jpg", "https://cdn/broken.jpg"]},
]


@pytest.fixture
def fake_apify(monkeypatch):
    calls = []

    def fake_post(url, params=None, json=None, timeout=None):
        calls.append({"url": url, "params": params, "json": json, "timeout": timeout})
        return FakeResp(json_data=ITEMS)

    s = config.Settings()
    s.apify_token = "test-token"
    monkeypatch.setattr(instagram, "get_settings", lambda: s)
    monkeypatch.setattr(instagram.httpx, "post", fake_post)
    monkeypatch.setattr(instagram.httpx, "Client", FakeClient)
    FakeClient.gets = []
    return calls


def test_ingest_accounts_top_sidecars(fake_apify):
    refs = ingest.ingest_accounts("s", ["@Creator"], per_account=2)
    call = fake_apify[0]
    assert "apify~instagram-scraper/run-sync-get-dataset-items" in call["url"]
    assert call["params"]["token"] == "test-token"
    assert call["json"]["directUrls"] == ["https://www.instagram.com/creator/"]
    assert call["json"]["resultsType"] == "posts"
    assert call["timeout"] >= 300
    assert [r.id for r in refs] == ["AAA111", "CCC333"]  # top 2 sidecars by likes+comments
    a = refs[0]
    assert len(a.slide_paths) == 2  # video child skipped
    assert "https://cdn/a2-thumb.jpg" not in FakeClient.gets
    assert a.likes == 900 and a.comments == 100 and a.caption.startswith("Top tips")
    assert a.source == ReferenceSource.account and a.origin == "@creator"
    assert len(refs[1].slide_paths) == 1  # broken download skipped
    assert Image.open(a.slide_paths[0]).format == "JPEG"
    # dedupe on second run
    assert ingest.ingest_accounts("s", ["creator"], per_account=2) == []


def test_ingest_post_urls(fake_apify):
    refs = ingest.ingest_post_urls("s", ["https://www.instagram.com/p/AAA111/", "https://www.instagram.com/p/BBB222/"])
    ids = {r.id for r in refs}
    assert {"AAA111", "BBB222", "III"} <= ids and "VVV" not in ids
    a = next(r for r in refs if r.id == "AAA111")
    assert a.source == ReferenceSource.post_url
    assert a.origin == "https://www.instagram.com/p/AAA111/"


def test_missing_apify_token(monkeypatch):
    s = config.Settings()
    s.apify_token = None
    monkeypatch.setattr(instagram, "get_settings", lambda: s)
    with pytest.raises(instagram.ApifyError, match="APIFY_TOKEN"):
        ingest.ingest_post_urls("s", ["https://www.instagram.com/p/X/"])


# ------------------------------------------------------------------ style

def fake_profile(**kw):
    base = dict(
        name="whatever", summary="Bold dark slides.",
        palette=Palette(background="0f0f0f", surface="#1A1A1A", text="#fff", muted_text="#999999",
                        accent="#FF5A1F", accent_2="nonsense"),
        typography=Typography(heading_font="Archivo Black", body_font="Inter", heading_weight=870,
                              heading_case="UPPERCASE", heading_size="xl"),
        archetypes=[
            SlideArchetype(name="point", description="d", layout="numbered point"),
            SlideArchetype(name="cta", description="d", layout="cta"),
            SlideArchetype(name="tip", description="d", layout="list"),
        ],
        decorations=["slide counter top-right"], uses_photos=False, words_per_slide=25,
        slide_count=40, hook_patterns=["contrarian claim"], tone="blunt", caption_style="short",
        reference_ids=["bogus"],
    )
    base.update(kw)
    return StyleProfile(**base)


def test_analyze_style(tmp_path, monkeypatch):
    src = tmp_path / "shots"
    for c in range(3):
        for i in range(1, 9):
            make_img(src / f"c{c}" / f"{i}.png", color=(c * 40, i * 10, 0))
    refs = ingest.ingest_local("Bold Dark", str(src))
    # give one ref known engagement so it's prioritised
    top = refs[2].model_copy(update={"likes": 500, "comments": 5, "caption": "Save this 🔥 #tips"})
    store.save_reference("Bold Dark", top)

    captured = {}

    def fake_ask_json(prompt, schema, *, system=None, images=(), max_tokens=32000):
        captured.update(prompt=prompt, schema=schema, system=system, images=list(images))
        return fake_profile()

    monkeypatch.setattr(style.llm, "ask_json", fake_ask_json)
    prof = style.analyze_style("Bold Dark", max_refs=2, max_slides_per_ref=4)

    assert captured["schema"] is StyleProfile and captured["system"]
    assert len(captured["images"]) == 8
    assert captured["images"][0] == top.slide_paths[0]          # engaged ref first
    assert captured["images"][3] == top.slide_paths[-1]         # last (CTA) slide kept
    assert "image 4 = slide 8/8" in captured["prompt"]
    assert "Save this" in captured["prompt"]
    assert "center_statement" in captured["prompt"]

    assert prof.name == "Bold Dark"
    assert prof.reference_ids[0] == top.id and len(prof.reference_ids) == 2
    layouts = [a.layout for a in prof.archetypes]
    assert layouts[0] == "center_statement" and layouts[-1] == "cta"
    assert set(layouts) <= set(style.ALLOWED_LAYOUTS)
    assert "numbered" in layouts
    assert prof.palette.background == "#0F0F0F" and prof.palette.text == "#FFFFFF"
    assert prof.palette.accent_2 == "#FF5A1F"
    assert prof.typography.heading_case == "upper" and prof.typography.heading_weight == 900
    assert prof.slide_count == 20

    saved = store.load_profile("Bold Dark")
    assert saved.name == "Bold Dark" and saved.reference_ids == prof.reference_ids


def test_analyze_style_caps_total_images(tmp_path, monkeypatch):
    src = tmp_path / "many"
    for c in range(10):
        for i in range(1, 11):
            make_img(src / f"c{c:02d}" / f"{i}.png", color=(c * 20, i * 20, 5))
    ingest.ingest_local("big", str(src))
    seen = {}
    monkeypatch.setattr(style.llm, "ask_json",
                        lambda p, s, **kw: seen.setdefault("n", len(list(kw["images"]))) and fake_profile())
    style.analyze_style("big", max_refs=10, max_slides_per_ref=10)
    assert seen["n"] <= 40


def test_analyze_style_no_refs():
    with pytest.raises(ValueError, match="No reference carousels"):
        style.analyze_style("empty-style")
