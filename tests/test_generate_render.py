"""Tests for carousel_studio.generate and carousel_studio.render.

The Claude API is never called: llm.ask_json is monkeypatched with canned output.
All data goes to a pytest tmp dir.
"""
from __future__ import annotations

import json

import pytest
from PIL import Image

from carousel_studio import config, llm, store
from carousel_studio.generate import CarouselCopy, IdeaList, SlideCopy, create_drafts, generate_ideas, \
    revise_draft, write_carousel
from carousel_studio.models import (CarouselDraft, DraftStatus, Idea, Palette, SlideArchetype, StyleProfile,
                                    Typography)
from carousel_studio.render import render_draft, render_preview
from carousel_studio.render.renderer import contrast, parse_decorations, title_case

STYLE = "dark-bold"


def make_profile(name=STYLE, uses_photos=True) -> StyleProfile:
    return StyleProfile(
        name=name, summary="Dark, punchy, high-contrast tips.",
        palette=Palette(background="#0E0E10", surface="#1A1A1F", text="#F5F5F0", muted_text="#A1A1AA",
                        accent="#D4FF3A", accent_2="#7C5CFF"),
        typography=Typography(heading_font="Inter", body_font="Inter", heading_weight=800,
                              heading_case="upper", heading_size="xl"),
        archetypes=[
            SlideArchetype(name="hook", description="Huge statement", layout="center_statement"),
            SlideArchetype(name="point", description="Heading top, body", layout="top_heading_body"),
            SlideArchetype(name="numbered_point", description="Big number", layout="numbered"),
            SlideArchetype(name="photo", description="Photo top", layout="split_image"),
            SlideArchetype(name="checklist", description="Checks", layout="list"),
            SlideArchetype(name="quote", description="Pull quote", layout="quote"),
            SlideArchetype(name="cta", description="Centered CTA", layout="cta"),
        ],
        decorations=["slide counter top-right", "handle bottom-left", "swipe arrow bottom-right", "grain texture"],
        uses_photos=uses_photos, words_per_slide=30, slide_count=7,
        hook_patterns=["Stop doing X", "N mistakes that..."], tone="blunt, second person",
        caption_style="3 short lines, 1 emoji, hashtags at the end",
    )


CANNED_COPY = CarouselCopy(
    slides=[
        SlideCopy(archetype="hook", kicker="AI for realtors", heading="Stop writing listings **by hand**"),
        SlideCopy(archetype="point", heading="Generic copy kills showings",
                  body="Buyers skim past 'stunning' and 'must-see'. Specific details sell."),
        SlideCopy(archetype="numbered_point", heading="Feed it the boring facts", body="Square footage, schools, year."),
        SlideCopy(archetype="Photo", heading="Sold in 6 days", body="One rewrite. 41 showings.",
                  image_prompt="sunlit kitchen"),
        SlideCopy(archetype="made_up_archetype", heading="Paste this prompt",
                  bullets=["Act as a top listing agent", "Use these facts", "Write 3 versions"]),
        SlideCopy(archetype="quote", heading="People buy the life they imagine.", body="— Every great agent"),
        SlideCopy(archetype="whatever", heading="Save this for your next listing", body="Share with an agent friend."),
    ],
    caption="Your listings deserve better. " * 120,  # way over 2200 chars
    hashtags=[f"tag{i}" for i in range(40)] + ["#tag1", "real estate"],
)


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    data = tmp_path / "data"
    for mod in (config, store):
        monkeypatch.setattr(mod, "STYLES_DIR", data / "styles")
        monkeypatch.setattr(mod, "DRAFTS_DIR", data / "drafts")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "BRAND_FILE", data / "brand.json")
    data.mkdir(parents=True)
    (data / "brand.json").write_text(json.dumps({
        "brand_name": "Kortexa", "instagram_handle": "@kortexa", "niche": "AI for real estate agents",
        "audience": "busy realtors", "call_to_action": "Follow @kortexa for daily AI playbooks",
    }))
    store.save_profile(make_profile())
    calls = []

    def fake_ask_json(prompt, schema, **kw):
        calls.append((prompt, schema))
        if schema is IdeaList:
            return IdeaList(ideas=[
                Idea(title=f"Idea {i}", angle="Saves agents hours", hook=f"Stop doing thing {i}") for i in range(5)
            ])
        if schema is CarouselCopy:
            return CANNED_COPY.model_copy(deep=True)
        raise AssertionError(f"unexpected schema {schema}")

    monkeypatch.setattr(llm, "ask_json", fake_ask_json)
    return calls


def _check_pngs(draft: CarouselDraft):
    assert all(s.rendered_path for s in draft.slides)
    for s in draft.slides:
        with Image.open(s.rendered_path) as im:
            assert im.size == (1080, 1350)
            assert im.format == "PNG"
            # not a blank image
            assert len(im.convert("L").resize((54, 68)).getcolors(65536)) > 5


def test_create_drafts_end_to_end(studio):
    drafts = create_drafts(STYLE, n=2)
    assert len(drafts) == 2
    for d in drafts:
        assert d.status == DraftStatus.draft
        assert len(d.slides) == 7
        _check_pngs(d)
        names = sorted(p.name for p in store.draft_dir(d.id).glob("slide_*.png"))
        assert names == [f"slide_{i:02d}.png" for i in range(1, 8)]
        reloaded = store.load_draft(d.id)
        assert reloaded.slides[0].rendered_path == d.slides[0].rendered_path


def test_write_carousel_validates_output(studio):
    idea = Idea(title="Listings by AI", angle="time", hook="Stop writing listings by hand")
    d = write_carousel(STYLE, idea)
    assert d.id.startswith("c_")
    assert [s.index for s in d.slides] == list(range(1, 8))
    names = {a.name: a.layout for a in make_profile().archetypes}
    for s in d.slides:
        assert s.archetype in names and s.layout == names[s.archetype]
    assert d.slides[0].archetype == "hook"
    assert d.slides[-1].archetype == "cta"
    assert d.slides[3].archetype == "photo"  # case-insensitive match
    assert d.slides[4].layout == "list"  # unknown archetype with bullets → list archetype
    assert len(d.hashtags) <= 30 and all(h.startswith("#") and " " not in h for h in d.hashtags)
    assert len(set(h.lower() for h in d.hashtags)) == len(d.hashtags)
    assert len(d.caption) + len(" ".join(d.hashtags)) + 2 <= 2200
    assert store.load_draft(d.id).idea.title == "Listings by AI"
    prompt = studio[-1][0]
    assert "Follow @kortexa" in prompt and "'numbered_point'" in prompt


def test_image_prompt_only_when_style_uses_photos(studio):
    store.save_profile(make_profile(name="no-photos", uses_photos=False))
    d = write_carousel("no-photos", Idea(title="t", angle="a", hook="h"))
    assert all(s.image_prompt is None for s in d.slides)


def test_generate_ideas_avoids_recent(studio):
    write_carousel(STYLE, Idea(title="Idea 0", angle="a", hook="h"))
    ideas = generate_ideas(STYLE, n=3, theme="pricing")
    assert len(ideas) == 3
    assert "Idea 0" not in [i.title for i in ideas]
    prompt = studio[-1][0]
    assert "Idea 0" in prompt and "pricing" in prompt and "busy realtors" in prompt


def test_revise_draft_keeps_id_and_uses_feedback(studio):
    d = write_carousel(STYLE, Idea(title="t", angle="a", hook="h"))
    d.status = DraftStatus.rejected
    store.save_draft(d)
    r = revise_draft(d.id, "Make slide 2 more specific", render=False)
    assert r.id == d.id
    assert r.status == DraftStatus.draft
    assert r.feedback == "Make slide 2 more specific"
    prompt = studio[-1][0]
    assert "Make slide 2 more specific" in prompt
    assert "Generic copy kills showings" in prompt  # previous version included
    assert store.load_draft(d.id).feedback == "Make slide 2 more specific"


def test_create_drafts_skips_failures(studio, monkeypatch):
    import carousel_studio.generate.writer as writer

    real = writer.write_carousel
    count = {"n": 0}

    def flaky(style, idea, feedback=None):
        count["n"] += 1
        if count["n"] == 1:
            raise RuntimeError("boom")
        return real(style, idea, feedback)

    monkeypatch.setattr(writer, "write_carousel", flaky)
    drafts = create_drafts(STYLE, n=3)
    assert len(drafts) == 2


def test_render_preview(studio):
    paths = render_preview(STYLE)
    assert len(paths) == 7
    for p in paths:
        assert "/preview/" in p
        with Image.open(p) as im:
            assert im.size == (1080, 1350)


def test_render_draft_with_image(studio, tmp_path):
    img = tmp_path / "photo.jpg"
    Image.new("RGB", (800, 600), "#336699").save(img)
    d = write_carousel(STYLE, Idea(title="t", angle="a", hook="h"))
    d.slides[3].image_path = str(img)
    d = render_draft(d)
    _check_pngs(d)
    with Image.open(d.slides[3].rendered_path) as im:  # photo occupies the top of the split slide
        r, g, b = im.convert("RGB").getpixel((540, 300))
        assert abs(r - 0x33) < 30 and abs(g - 0x66) < 30 and abs(b - 0x99) < 30


def test_decoration_parsing_and_helpers():
    d = parse_decorations(["Slide counter 01/07 bottom-right in a pill", "@handle top left",
                           "thin accent underline", "film grain", "white rounded card"])
    assert d["counter"] == "br" and d["counter_pad"] and d["counter_pill"]
    assert d["handle"] == "tl"
    assert d["underline"] and d["rule_h"] == 4
    assert d["grain"] and d["card"]
    assert title_case("how to win at the game of AI") == "How to Win at the Game of AI"
    assert contrast("#000000", "#FFFFFF") > 20


# ------------------------------------------------------------ brand kit: logo, before/after, photo


def _logo_png(path, ink):
    """A fake transparent logo with three bands: mark, wordmark, tagline (like data/brand/logo-*.png)."""
    from PIL import ImageDraw

    im = Image.new("RGBA", (400, 220), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([150, 10, 250, 110], fill=ink)        # mark
    d.rectangle([20, 140, 380, 180], fill=ink)        # wordmark
    d.rectangle([40, 200, 360, 208], fill="#98CC13")  # tagline
    im.save(path)


def _kit_profile(name="kit", bg="#030305", text="#FFFFFF") -> StyleProfile:
    p = make_profile(name=name, uses_photos=False)
    p.palette = Palette(background=bg, surface="#111114", text=text, muted_text="#888888",
                        accent="#98CC13", accent_2="#6FA00B")
    p.archetypes.append(SlideArchetype(name="before_after", description="Two panels", layout="before_after"))
    p.decorations = ["full logo top left on cover, small logo on inner slides",
                     "footer line 'KORTEXA · AI WORKFLOWS' bottom left", "slide counter 01 / 08 top right",
                     "letter-spaced lime eyebrow label with a short lime bar", "numbered rows with big lime numbers",
                     "callout with lime left border", "lime CTA button with black text",
                     "highlighted words in lime text colour"]
    return p


def test_logo_embedding_picks_variant_by_background(tmp_path):
    from carousel_studio.models import Slide
    from carousel_studio.render.renderer import brand_logo, logo_variants, render_html

    dark, light = tmp_path / "on-dark.png", tmp_path / "on-light.png"
    _logo_png(dark, "#FFFFFF")
    _logo_png(light, "#000000")
    v = logo_variants(str(dark))
    assert set(v) == {"full", "lockup", "mark"}
    assert v["mark"]["ratio"] == pytest.approx(1.0, abs=0.05)       # the square symbol only
    assert v["full"]["ratio"] < v["lockup"]["ratio"]                 # tagline makes the full logo taller
    brand = {"brand_name": "Kortexa", "instagram_handle": "@kortexa", "logo_dark": str(dark),
             "logo_light": str(light), "call_to_action": "Comment LISTING and I'll send you the playbook"}
    assert brand_logo(brand, True)["full"]["uri"] == v["full"]["uri"]
    assert brand_logo(brand, False)["full"]["uri"] == logo_variants(str(light))["full"]["uri"]

    slides = [Slide(index=1, archetype="hook", layout="center_statement", heading="Your listing is **invisible**",
                    kicker="For agents"),
              Slide(index=2, archetype="point", layout="top_heading_body", heading="The problem", body="Text."),
              Slide(index=3, archetype="cta", layout="cta", heading="Want the playbook?",
                    body="Comment LISTING and I'll send you the playbook")]
    for prof, logo in ((_kit_profile(), dark), (_kit_profile("kit-light", "#FFFFFF", "#030305"), light)):
        lv = logo_variants(str(logo))
        pages = render_html(prof, slides, brand)
        assert 'class="hero-logo"' in pages[0] and lv["full"]["uri"] in pages[0]       # cover: big full logo
        assert 'class="chip logo"' in pages[1] and lv["lockup"]["uri"] in pages[1]     # inner: small lockup
        assert 'class="hero-logo"' in pages[2] and 'class="cta-btn"' in pages[2]
        assert "Comment LISTING" in pages[2]
        assert "AI WORKFLOWS" in pages[1] and 'class="kicker' in pages[0] and 'class="ebar"' in pages[0]
    # highlights use the darker lime on white slides
    light_page = render_html(_kit_profile("kit-light", "#FFFFFF", "#030305"), slides[:1], brand)[0]
    assert "--hl: #6FA00B" in light_page
    # no logo file -> falls back to the brand name as text, nothing breaks
    page = render_html(_kit_profile(), slides[1:2], {"brand_name": "Kortexa", "logo_dark": "missing.png"})[0]
    assert 'class="chip brand"' in page and "data:image/png" not in page


def test_before_after_layout_text_and_photo(tmp_path):
    from carousel_studio.models import Slide
    from carousel_studio.render.renderer import render_html, render_slides

    brand = {"brand_name": "Kortexa", "instagram_handle": "@kortexa"}
    body = ("Before: Beautiful house for sale. DM for price.\n"
            "After: Pool and garden in East Legon.\n✓ Gated\n✓ Fitted kitchen\nDM \"TOUR\" to book a viewing.")
    text_slide = Slide(index=1, archetype="before_after", layout="before_after", heading="Same house. **Better caption.**",
                       body=body)
    html_ = render_html(_kit_profile(), [text_slide], brand)[0]
    assert 'class="panel before"' in html_ and 'class="panel after"' in html_
    assert "Beautiful house for sale" in html_ and "Fitted kitchen" in html_ and 'class="ck"' in html_
    # body + bullets convention also works
    alt = Slide(index=1, archetype="before_after", layout="before_after", heading="h", body="Photo dump",
                bullets=["Hero shot first", "One clear action"])
    alt_html = render_html(_kit_profile(), [alt], brand)[0]
    assert "Photo dump" in alt_html and "One clear action" in alt_html

    photo = tmp_path / "after.jpg"
    Image.new("RGB", (900, 700), "#336699").save(photo)
    photo_slide = text_slide.model_copy(update={"index": 2, "image_path": str(photo), "body": "Before: plain\nAfter: premium"})
    full = Slide(index=3, archetype="photo", layout="photo", heading="4-bed with pool, **East Legon**",
                 body="Gated, fitted kitchen.", image_path=str(photo))
    paths = render_slides(_kit_profile(), [text_slide, photo_slide, full], tmp_path / "out", brand=brand)
    assert [p.name for p in paths] == ["slide_01.png", "slide_02.png", "slide_03.png"]
    with Image.open(paths[1]) as im:  # the AFTER panel (lower half) shows the photo
        lower = im.convert("RGB").crop((90, 800, 990, 1150)).resize((90, 35))
        px = [lower.getpixel((x, y)) for y in range(lower.height) for x in range(lower.width)]
        blue = sum(1 for r, g, b in px if abs(r - 0x33) < 30 and abs(g - 0x66) < 30 and abs(b - 0x99) < 30)
        assert blue > 300
    with Image.open(paths[2]) as im:  # full-bleed photo: bright in the middle, dark gradient behind the text
        rgb = im.convert("RGB")
        r, g, b = rgb.getpixel((540, 520))
        assert abs(r - 0x33) < 30 and abs(b - 0x99) < 30
        assert sum(rgb.getpixel((540, 1300))) < 90


# ------------------------------------------------------------ editorial format (kortexa-editorial)

EDITORIAL_PROFILE = config.ROOT / "data" / "styles" / "kortexa-editorial" / "profile.json"
_ED_BRAND = {"brand_name": "Kortexa", "instagram_handle": "@ahmed.kortexa",
             "call_to_action": "Comment LISTING and I'll send you the playbook"}


def _editorial_profile() -> StyleProfile:
    return StyleProfile.model_validate_json(EDITORIAL_PROFILE.read_text())


def test_editorial_profile_is_valid():
    from carousel_studio.render.renderer import LAYOUTS

    p = _editorial_profile()
    assert p.name == "kortexa-editorial" and p.palette.accent == "#98CC13" and p.palette.background == "#030305"
    assert p.typography.heading_font == "Montserrat" and p.typography.body_font == "Inter"
    assert {a.layout for a in p.archetypes} == {"editorial_cover", "worksheet", "editorial_takeaway", "editorial_cta"}
    assert all(a.layout in LAYOUTS for a in p.archetypes)
    assert "~~" in next(a.description for a in p.archetypes if a.layout == "worksheet")  # scribble convention documented
    d = parse_decorations(p.decorations)
    assert d["serif"] == "Instrument Serif" and d["cinematic"]


def test_editorial_worksheet_html():
    from carousel_studio.models import Slide
    from carousel_studio.render.renderer import render_html

    slides = [
        Slide(index=1, archetype="question", layout="worksheet", kicker="2", heading="What is the ~~one~~ thing?",
              bullets=["My hero shot:", "Price shown? (yes/no):", "Keep it short"]),
        Slide(index=2, archetype="question", layout="worksheet", heading="Who replies?",
              bullets=["My first reply:", "___", "___"]),
    ]
    a, b = render_html(_editorial_profile(), slides, _ED_BRAND)
    assert '<div class="numeral">2.</div>' in a                    # kicker digits
    assert '<div class="numeral">2.</div>' in b                    # no kicker: 2nd question slide
    assert a.count('class="row"') == 2 and a.count('class="fill"') == 2
    assert a.count('class="line"') == 4                            # 2 prompts -> 2 extra writing lines each
    assert '<div class="note">Keep it short</div>' in a            # no ':' -> italic line, no rule
    assert b.count('class="line"') == 2                            # explicit '___' lines replace the auto ones
    assert 'class="scribble"' in a and 'class="scrib"' in a and "~~" not in a
    assert "--serif: 'Instrument Serif'" in a and "@ahmed.kortexa" in a and "save for later" in a
    assert "Montserrat" in a and "#98CC13" in a


def test_editorial_cover_takeaway_cta_html():
    from carousel_studio.models import Slide
    from carousel_studio.render.renderer import render_html

    slides = [
        Slide(index=1, archetype="cover", layout="editorial_cover",
              heading="Your listing **checklist** *before* you **post.**", body="from someone who reviews listings"),
        Slide(index=2, archetype="takeaway", layout="editorial_takeaway", kicker="Remember this:",
              heading="Same listing. Better ~~package~~.", body="Get the ones you have **noticed**."),
        Slide(index=3, archetype="cta", layout="editorial_cta", heading="Get my **playbook**",
              body="Comment LISTING and I'll send you the playbook"),
    ]
    cover, take, cta = render_html(_editorial_profile(), slides, _ED_BRAND)
    assert "<em>before</em>" in cover and '<span class="hl hlnw">checklist</span>' in cover
    assert '<span class="dot">.</span>' in cover                   # white phrase, accent full stop
    assert 'class="sub"' in cover and "swipe" in cover
    assert "Remember this:" in take and 'class="scribble"' in take and 'class="rule2"' in take
    assert 'class="cta-btn"' in cta and "Comment LISTING" in cta and cta.count("Comment LISTING") == 1
    assert 'class="swipe"' not in cta                              # last slide: no swipe cue


def test_editorial_photo_options_and_grade(tmp_path):
    from carousel_studio.render.renderer import _split_image_opts, cinematic_grade, editorial_photo

    raw, opts = _split_image_opts("me.png#pos=50% 0%&right&portrait")
    assert raw == "me.png" and opts == {"pos": "50% 0%", "fit": "right", "grade": "portrait"}
    assert _split_image_opts("x.jpg#pos=1px;}body{color:red")[1]["pos"] == "1px"  # CSS can't be injected
    assert _split_image_opts("x.jpg#raw")[1]["grade"] == "none"

    # portrait grade: light background touching the frame goes dark, the subject and a highlight
    # inside it (an island, like forehead shine) are left natural
    from PIL import ImageDraw
    im = Image.new("RGB", (400, 500), (205, 205, 200))
    d = ImageDraw.Draw(im)
    d.rectangle([100, 120, 300, 500], fill=(140, 92, 64))
    d.rectangle([180, 200, 220, 240], fill=(205, 205, 200))
    src = tmp_path / "portrait.png"
    im.save(src)
    import base64
    import io
    g = cinematic_grade(src, "portrait")
    out = Image.open(io.BytesIO(base64.b64decode(g["uri"].split(",", 1)[1]))).convert("RGB")
    assert sum(out.getpixel((20, 20))) < 3 * 80                    # background crushed
    assert sum(out.getpixel((200, 220))) > 3 * 150                 # interior highlight untouched
    r, gg, b = out.getpixel((140, 400))
    assert abs(r - 140) < 30 and abs(gg - 92) < 30 and abs(b - 64) < 30  # skin-like tone kept
    assert g["ratio"] == pytest.approx(0.8)

    ph = editorial_photo(str(src) + "#right", None)
    assert ph["fit"] == "right" and ph["width"] == round(1350 * 0.8) and ph["grade"] == "cinematic"
    assert editorial_photo("missing.png", None) is None


def test_portrait_soft_option_and_skin_grade(tmp_path):
    import base64
    import io

    import numpy as np
    from PIL import ImageDraw

    from carousel_studio.render.renderer import _split_image_opts, cinematic_grade, editorial_photo

    assert _split_image_opts("me.png#portrait&soft")[1] == {"grade": "portrait", "soft": "0.6"}
    assert _split_image_opts("me.png#portrait&soft=0.2&zoom=0.8")[1]["soft"] == "0.2"

    # light wall, a skin-toned face with a dark 'eye' line (an edge that must stay crisp)
    im = Image.new("RGB", (400, 500), (205, 205, 200))
    d = ImageDraw.Draw(im)
    d.rectangle([100, 120, 300, 500], fill=(140, 92, 64))
    d.rectangle([140, 250, 260, 256], fill=(25, 15, 10))
    src = tmp_path / "face.png"
    im.save(src)

    def grade(**kw):
        g = cinematic_grade(src, "portrait", **kw)
        return g, np.asarray(Image.open(io.BytesIO(base64.b64decode(g["uri"].split(",", 1)[1]))).convert("L"), dtype=float)

    def edge(a):                                                    # contrast across the dark line
        return abs(a[240:246, 150:250].mean() - a[252:254, 150:250].mean())

    _, crisp = grade(soft=0.0)
    _, soft = grade(soft=1.0)
    assert edge(soft) < edge(crisp) - 10                            # soft=1 visibly defocuses
    assert edge(crisp) > 40                                         # smoothing keeps real edges
    assert crisp[20:60, 20:60].mean() < 80                          # background still dark

    g, out_default = grade()                                        # portrait defaults to a mild soft
    assert edge(soft) < edge(out_default) < edge(crisp)
    r, gg, b = np.asarray(Image.open(io.BytesIO(base64.b64decode(cinematic_grade(src, "portrait", soft=0.0)["uri"].split(",", 1)[1]))).convert("RGB"))[400, 200]
    assert r > b + 30 and r >= 140                                  # warm, not grey, shadows lifted

    zoomed = cinematic_grade(src, "portrait", zoom=0.8)             # zoom out: same shape, face smaller in frame
    zo = np.asarray(Image.open(io.BytesIO(base64.b64decode(zoomed["uri"].split(",", 1)[1]))).convert("RGB"))
    assert zo.shape[1] == round(400 / 0.8) and zoomed["ratio"] == pytest.approx(0.8, abs=0.01)
    ph = editorial_photo(str(src) + "#portrait&soft=0.6", None)
    assert ph["grade"] == "portrait"


def test_editorial_render_with_and_without_photo(tmp_path):
    from carousel_studio.models import Slide
    from carousel_studio.render.renderer import render_slides

    photo = tmp_path / "red.jpg"
    Image.new("RGB", (900, 1200), (200, 40, 40)).save(photo)
    slides = [
        Slide(index=1, archetype="question", layout="worksheet", kicker="1", heading="What will buyers see first?",
              bullets=["My hero shot:"]),
        Slide(index=2, archetype="question", layout="worksheet", kicker="2", heading="Which ~~one~~ keyword?",
              bullets=["My one keyword:"], image_path=str(photo) + "#right&grade=none"),
    ]
    paths = render_slides(_editorial_profile(), slides, tmp_path / "out", brand=_ED_BRAND)
    with Image.open(paths[0]) as im:                                # dark cinematic stand-in, no photo
        rgb = im.convert("RGB")
        assert rgb.size == (1080, 1350)
        assert sum(rgb.getpixel((900, 700))) < 3 * 60
        # the lime numeral sits behind the heading at the top left
        lime = sum(1 for x in range(80, 400, 8) for y in range(100, 560, 8)
                   if (lambda p: p[1] > 150 and p[0] < 190 and p[2] < 90)(rgb.getpixel((x, y))))
        assert lime > 30
    with Image.open(paths[1]) as im:                                # photo on the right, fading to black on the left
        rgb = im.convert("RGB")
        r, g, b = rgb.getpixel((900, 700))
        assert r > 90 and r > g + 40
        assert sum(rgb.getpixel((30, 700))) < 3 * 40
