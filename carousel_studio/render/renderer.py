"""Turn slides + a StyleProfile into 1080x1350 PNGs via Jinja2 HTML templates and
headless Chromium. Everything visual is derived from the profile's tokens."""
from __future__ import annotations

import base64
import html
import logging
import mimetypes
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .. import config, store
from ..config import get_settings
from ..models import CarouselDraft, Slide, StyleProfile
from . import fonts as fontlib
from .browser import browser_page

log = logging.getLogger(__name__)

W, H = 1080, 1350
LAYOUTS = ("center_statement", "top_heading_body", "numbered", "split_image", "list", "quote", "cta")
TEMPLATES = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# ------------------------------------------------------------------ colours


def _hex(c: str, default: str = "#000000") -> str:
    c = (c or "").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?", c)
    if not m:
        m2 = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+).*\)", c)
        if m2:
            return "#" + "".join(f"{min(255, int(x)):02X}" for x in m2.groups())
        return default
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h.upper()


def _rgb(c: str) -> tuple[int, int, int]:
    c = _hex(c)
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _lum(c: str) -> float:
    def ch(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(c)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _rgba(c: str, a: float) -> str:
    r, g, b = _rgb(c)
    return f"rgba({r},{g},{b},{a})"


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ra, rb))


def _best_on(bg: str) -> str:
    return "#FFFFFF" if contrast("#FFFFFF", bg) >= contrast("#111111", bg) else "#111111"


def build_colors(profile: StyleProfile) -> dict:
    p = profile.palette
    bg, surface = _hex(p.background, "#FFFFFF"), _hex(p.surface, "#F2F2F2")
    text, muted = _hex(p.text, "#111111"), _hex(p.muted_text, "#666666")
    accent, accent2 = _hex(p.accent, "#FF5A36"), _hex(p.accent_2, "#FFC53D")
    if contrast(text, bg) < 4.5:
        text = _best_on(bg)
    if contrast(muted, bg) < 3.2:
        muted = _mix(text, bg, 0.32)
    hl = next((x for x in (accent, accent2) if contrast(x, bg) >= 2.6), text)
    is_dark = _lum(bg) < 0.22
    card_text = muted if contrast(muted, surface) >= 3.2 else (text if contrast(text, surface) >= 4.5 else _best_on(surface))
    ph_mid = _mix(accent, accent2, 0.5)
    return dict(
        bg=bg, surface=surface, text=text, muted=muted, accent=accent, accent2=accent2,
        on_accent=_best_on(accent), hl=hl, is_dark=is_dark, card_text=card_text,
        line=_rgba(text, 0.14), shadow="rgba(0,0,0,.35)" if is_dark else "rgba(20,20,40,.08)",
        on_ph=_best_on(ph_mid),
        accent_a18=_rgba(accent, 0.20 if is_dark else 0.16), accent2_a14=_rgba(accent2, 0.16 if is_dark else 0.14),
        accent_a85=_rgba(accent, 0.85), accent2_a80=_rgba(accent2, 0.80),
        bg_a40=_rgba(bg, 0.4), bg_a55=_rgba(bg, 0.55), bg_a80=_rgba(bg, 0.8), bg_a96=_rgba(bg, 0.96),
    )


# --------------------------------------------------------------- typography

_SMALL = {"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet", "as", "at", "by", "in",
          "of", "off", "on", "per", "to", "up", "via", "vs", "vs.", "with", "from", "into", "is"}


def title_case(s: str) -> str:
    words = s.split(" ")
    out = []
    for i, w in enumerate(words):
        core = w.lower().strip("*\"'“”‘’()")
        if 0 < i < len(words) - 1 and core in _SMALL:
            out.append(w.lower() if w.islower() or w.istitle() else w)
            continue
        idx = next((j for j, ch in enumerate(w) if ch.isalpha()), None)
        if idx is None or not w[idx].islower():
            out.append(w)  # keep acronyms / already-capitalised words
        else:
            out.append(w[:idx] + w[idx].upper() + w[idx + 1:])
    return " ".join(out)


def build_typography(profile: StyleProfile) -> dict:
    t = profile.typography
    weight = max(100, min(900, int(round((t.heading_weight or 700) / 100) * 100)))
    case = (t.heading_case or "sentence").lower()
    upper = case.startswith("upper") or case == "caps"
    size = (t.heading_size or "l").lower()
    scale = {"xl": 1.16, "xxl": 1.25, "l": 1.0, "lg": 1.0, "large": 1.0, "m": 0.84, "md": 0.84,
             "medium": 0.84, "s": 0.74, "small": 0.74}.get(size, 1.0)
    hf = t.heading_font or "Inter"
    serif = any(h in hf.lower() for h in fontlib.SERIF_HINTS) and "sans" not in hf.lower()
    display = any(h in hf.lower() for h in fontlib.DISPLAY_HINTS)
    if upper:
        scale *= 1.0 if display else 0.86
    if upper:
        lh, tr = (0.98 if display else 1.02), ("0.01em" if display else "-0.005em")
    elif serif:
        lh, tr = 1.08, "-0.015em"
    else:
        lh, tr = (1.04 if weight >= 700 else 1.08), ("-0.03em" if weight >= 800 else "-0.02em")
    return dict(weight=weight, upper=upper, title=case.startswith("title"), scale=round(scale, 3),
                line_height=lh, tracking=tr, serif=serif, quote_italic=serif,
                quote_weight=min(weight, 500 if serif else 700))


def build_fonts(profile: StyleProfile) -> dict:
    t = profile.typography
    hf, bf = (t.heading_font or "Inter").strip(), (t.body_font or "Inter").strip()
    w = max(100, min(900, int(round((t.heading_weight or 700) / 100) * 100)))
    reqs = [(hf, {w, 900}), (bf, {400, 600, 700})]
    serif_head = any(h in hf.lower() for h in fontlib.SERIF_HINTS) and "sans" not in hf.lower()
    css = ""
    try:
        css = fontlib.font_css(reqs, italic_body=hf if serif_head else None)
    except Exception as e:  # never let fonts break rendering
        log.warning("Font loading failed: %s", e)
    return dict(
        heading=Markup(fontlib.css_stack(hf)), body=Markup(fontlib.css_stack(bf)),
        quote_mark=Markup(fontlib.css_stack(hf) if serif_head else "Georgia, 'DejaVu Serif', serif"),
        css=css,
    )


# -------------------------------------------------------------- decorations

_ARROW = ('<svg viewBox="0 0 24 24" fill="none" stroke-width="2.6" stroke-linecap="round" '
          'stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>')


def _pos(text: str, default: str) -> str:
    t = text.lower().replace("_", " ").replace("-", " ")
    v = "t" if re.search(r"\b(top|upper|header)\b", t) else "b" if re.search(r"\b(bottom|lower|footer)\b", t) else default[0]
    h = "l" if re.search(r"\bleft\b", t) else "r" if re.search(r"\bright\b", t) else default[1]
    return v + h


def parse_decorations(decorations: Sequence[str]) -> dict:
    """Keyword-match free-text motifs into render switches + chrome positions."""
    d = dict(counter=None, counter_pad=False, counter_pill=False, handle=None, swipe=None, swipe_word=False,
             brand=None, underline=False, rule_h=10, bar=None, frame=False, frame_w=2, frame_radius=0,
             frame_color=None, grain=False, grain_opacity=0.10, progress=False, glow=False, dots=False,
             grid=False, blob=False, card=False, marker=False, outline_numbers=False, numbered_marks=False)
    for raw in decorations or []:
        s = raw.lower()
        if re.search(r"counter|page number|slide number|pagination|\d+\s*/\s*\d+|\d+ of \d+", s):
            d["counter"] = _pos(s, "tr")
            d["counter_pad"] = bool(re.search(r"\b0\d\b", s))
            d["counter_pill"] = any(k in s for k in ("pill", "badge", "capsule", "rounded"))
        if re.search(r"handle|username|@\w|account name", s):
            d["handle"] = _pos(s, "bl")
        if re.search(r"swipe|arrow|chevron|next ?→|→", s):
            d["swipe"] = _pos(s, "br")
            d["swipe_word"] = "swipe" in s
        if re.search(r"\blogo\b|brand ?name|wordmark", s):
            d["brand"] = _pos(s, "tl")
        if "underline" in s or "rule under" in s:
            d["underline"] = True
            if "thin" in s or "hairline" in s:
                d["rule_h"] = 4
        if re.search(r"(accent|colou?r|side|vertical|edge)[\w\s]*\b(bar|stripe|strip|band)\b|\bbar\b|\bstripe\b", s) \
                and "progress" not in s and "underline" not in s:
            d["bar"] = "top" if "top" in s else "bottom" if "bottom" in s else "left"
        if re.search(r"border|frame|outline box|inset line", s):
            d["frame"] = True
            d["frame_radius"] = 28 if "round" in s else 0
            d["frame_w"] = 4 if "thick" in s else 2
            d["frame_color"] = "accent" if "accent" in s or "colou" in s else None
        if re.search(r"grain|noise|film|texture|paper", s):
            d["grain"] = True
            d["grain_opacity"] = 0.16 if any(k in s for k in ("heavy", "strong", "film")) else 0.10
            d["grain_strong"] = d["grain_opacity"] > 0.12
        if "progress" in s:
            d["progress"] = True
        if re.search(r"gradient|glow|halo|mesh", s):
            d["glow"] = True
        if re.search(r"dot(s|ted)? (grid|pattern)|polka|halftone", s):
            d["dots"] = True
        elif re.search(r"grid", s):
            d["grid"] = True
        if re.search(r"blob|circle|shape|orb", s):
            d["blob"] = True
        if re.search(r"card|panel|box|container", s) and "outline box" not in s:
            d["card"] = True
        if re.search(r"highlight|marker|highlighter", s):
            d["marker"] = True
        if re.search(r"outline(d)? (number|numeral|digit)", s):
            d["outline_numbers"] = True
        if re.search(r"numbered (bullet|list)|number badge", s):
            d["numbered_marks"] = True
    return d


def _chrome(deco: dict, brand: dict, index: int, total: int, layout: str, on_image: bool) -> dict:
    slots = {"tl": [], "tr": [], "bl": [], "br": []}
    esc = html.escape
    if deco["brand"] and brand.get("brand_name"):
        slots[deco["brand"]].append(f'<div class="chip brand">{esc(brand["brand_name"])}</div>')
    if deco["handle"] and brand.get("instagram_handle") and layout != "cta":
        h = brand["instagram_handle"]
        h = h if h.startswith("@") else "@" + h
        slots[deco["handle"]].append(f'<div class="chip handle">{esc(h)}</div>')
    if deco["counter"]:
        txt = f"{index:02d} / {total:02d}" if deco["counter_pad"] else f"{index}/{total}"
        pill = deco["counter_pill"] or (on_image and deco["counter"].startswith("t"))
        cls = "chip counter pill" if pill else "chip counter"
        slots[deco["counter"]].append(f'<div class="{cls}">{txt}</div>')
    if deco["swipe"] and index < total:
        word = "Swipe" if deco["swipe_word"] else ""
        slots[deco["swipe"]].append(f'<div class="chip swipe">{word}<span class="arrow">{_ARROW}</span></div>')
    # items on the right should read outward (arrow last)
    return {k: [Markup(x) for x in v] for k, v in slots.items()}


# ------------------------------------------------------------------- text


def smart_quotes(t: str) -> str:
    t = re.sub(r'(^|[\s(\[{\u2014\u2013-])"', "\\1\u201c", t)
    t = t.replace('"', "\u201d")
    t = re.sub(r"(^|[\s(\[{\u2014\u2013-])'", "\\1\u2018", t)
    return t.replace("'", "\u2019")


def rich(text: Optional[str], *, paragraphs: bool = False, case_fn=None) -> Markup:
    """Escape, apply heading case, turn **x** into accent spans and newlines into breaks."""
    if not text:
        return Markup("")
    t = text.strip()
    if case_fn:
        t = case_fn(t)
    t = html.escape(smart_quotes(t), quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r'<span class="hl">\1</span>', t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
    t = t.replace("**", "")
    # keep short hyphenated compounds ("must-see", "3-bed") on one line
    t = re.sub(r"(?<![\w-])(\w{1,12}(?:-\w{1,12}){1,2})(?![\w-])", r'<span class="nw">\1</span>', t)
    if paragraphs:
        parts = [p.strip() for p in re.split(r"\n\s*\n|\n", t) if p.strip()]
        return Markup("".join(f"<p>{p}</p>" for p in parts))
    return Markup(t.replace("\n", "<br>"))


def _plain(text: Optional[str]) -> str:
    return re.sub(r"\*+", "", text or "").strip()


def _image_uri(path: Optional[str], base: Optional[Path] = None) -> Optional[str]:
    if not path:
        return None
    candidates = [Path(path)]
    if base:
        candidates.append(base / path)
    candidates.append(config.DATA_DIR / path)
    for p in candidates:
        if p.is_file():
            mime = mimetypes.guess_type(p.name)[0] or "image/png"
            return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"
    log.warning("Slide image not found: %s", path)
    return None


def _align_for(profile: StyleProfile, archetype: str, layout: str) -> str:
    desc = next((a.description.lower() for a in profile.archetypes if a.name == archetype), "")
    if re.search(r"left[- ]aligned|aligned left|flush left|\bleft\b", desc):
        return "left"
    if re.search(r"cent(er|re)", desc):
        return "center"
    return "center" if layout in ("center_statement", "cta") else "left"


# ---------------------------------------------------------------- rendering


class _Theme:
    def __init__(self, profile: StyleProfile, brand: dict):
        self.profile = profile
        self.brand = brand
        self.c = build_colors(profile)
        self.t = build_typography(profile)
        self.fonts = build_fonts(profile)
        self.deco = parse_decorations(profile.decorations)
        fc = self.deco["frame_color"]
        self.deco["frame_color"] = self.c["accent"] if fc == "accent" else self.c["line"]
        if not self.c["is_dark"] and not self.deco.get("grain_strong"):
            self.deco["grain_opacity"] = 0.05  # multiply-grain greys out light backgrounds quickly
        tops = {self.deco[k] for k in ("counter", "handle", "brand") if self.deco[k]}
        bottoms = tops | ({self.deco["swipe"]} if self.deco["swipe"] else set())
        self.has_top = any(p and p.startswith("t") for p in bottoms)
        self.has_bottom = any(p and p.startswith("b") for p in bottoms)


def _context(theme: _Theme, slide: Slide, total: int, numbered_ordinal: int, base: Optional[Path]) -> dict:
    p, t, brand = theme.profile, theme.t, theme.brand
    layout = slide.layout if slide.layout in LAYOUTS else _fallback_layout(slide, total)
    case_fn = title_case if t["title"] else None
    is_first, is_last = slide.index == 1, slide.index == total

    image_uri = _image_uri(slide.image_path, base)
    on_image = bool(layout == "split_image" or image_uri)
    chrome = _chrome(theme.deco, brand, slide.index, total, layout, on_image and layout == "split_image")

    top = 64 + 44 + 52 if theme.has_top else 110
    bottom = 64 + 44 + 52 if theme.has_bottom else 110
    media_h = 610
    if layout == "split_image":
        top = media_h + 56
    grow = {"center_statement": 1.0, "cta": 1.0, "quote": 1.1, "split_image": 1.08}.get(layout, 1.18)
    geo = dict(top=top, bottom=bottom, media_h=media_h, grow=grow)

    kicker = slide.kicker
    number = f"{numbered_ordinal:02d}"
    if layout == "numbered" and kicker:
        m = re.fullmatch(r"\s*(?:#|no\.?|step|tip|rule|mistake|lesson|part)?\s*(\d{1,2})[.):]?\s*", kicker, re.I)
        if m:
            number, kicker = f"{int(m.group(1)):02d}", None

    s = dict(
        index=slide.index, layout=layout,
        kicker=Markup(html.escape(_plain(kicker))) if kicker else None,
        heading=rich(slide.heading, case_fn=case_fn),
        body=rich(slide.body, paragraphs=True) if slide.body else None,
        bullets=[rich(b) for b in slide.bullets if b and b.strip()],
    )
    ctx = dict(
        s=s, c=theme.c, t=t, fonts=theme.fonts, font_css=Markup(theme.fonts["css"]), deco=theme.deco,
        chrome=chrome, chrome_on_image=layout == "split_image", geo=geo, total=total,
        is_first=is_first, is_last=is_last, image_uri=image_uri, number=number,
        align=_align_for(p, slide.archetype, layout),
    )
    if layout == "list":
        bullets = s["bullets"]
        list_body = s["body"]
        if not bullets and slide.body:
            lines = [ln.strip(" -•*\t") for ln in slide.body.splitlines() if ln.strip(" -•*\t")]
            if len(lines) >= 2:
                bullets, list_body = [rich(x) for x in lines], None
        ctx.update(bullets=bullets, list_body=list_body)
    if layout == "quote":
        body = _plain(slide.body)
        if body and len(body.split()) <= 9:
            ctx.update(attribution=body.lstrip("—–- ").strip(), quote_body=None)
        else:
            ctx.update(attribution=None, quote_body=s["body"])
    if layout == "cta":
        cta = (brand.get("call_to_action") or "").strip()
        seen = (_plain(slide.heading) + " " + _plain(slide.body)).lower()
        handle = brand.get("instagram_handle") or ""
        if handle and not handle.startswith("@"):
            handle = "@" + handle
        name = brand.get("brand_name") or handle.lstrip("@") or "•"
        ctx.update(cta_text=cta if cta and cta.lower().rstrip(".!") not in seen else None,
                   handle=handle, initial=name[:1].upper())
    return ctx


def _fallback_layout(slide: Slide, total: int) -> str:
    if slide.index == 1:
        return "center_statement"
    if slide.index == total:
        return "cta"
    if slide.bullets:
        return "list"
    return "top_heading_body"


def render_html(profile: StyleProfile, slides: Sequence[Slide], brand: Optional[dict] = None,
                base: Optional[Path] = None) -> List[str]:
    """Build the HTML for each slide (exposed for debugging / tests)."""
    brand = brand if brand is not None else get_settings().brand
    theme = _Theme(profile, brand)
    out, n_ord = [], 0
    total = len(slides)
    for sl in slides:
        if sl.layout == "numbered":
            n_ord += 1
        ctx = _context(theme, sl, total, max(n_ord, 1), base)
        out.append(_env.get_template(f"{ctx['s']['layout']}.html.j2").render(**ctx))
    return out


def render_slides(profile: StyleProfile, slides: Sequence[Slide], out_dir: Path,
                  brand: Optional[dict] = None, prefix: str = "slide_") -> List[Path]:
    """Render slides to out_dir/slide_01.png ... and return the paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{prefix}*.png"):
        old.unlink()
    pages = render_html(profile, slides, brand, base=out_dir)
    paths: List[Path] = []
    with browser_page(W, H) as page:
        for sl, doc in zip(slides, pages):
            page.set_content(doc, wait_until="load", timeout=30000)
            page.wait_for_function("window.__ready === true", timeout=20000)
            if page.evaluate("window.__overflow"):
                log.warning("Slide %s text still overflows at minimum size", sl.index)
            path = out_dir / f"{prefix}{sl.index:02d}.png"
            page.screenshot(path=str(path), type="png", clip={"x": 0, "y": 0, "width": W, "height": H})
            paths.append(path)
    return paths


def render_draft(draft: CarouselDraft) -> CarouselDraft:
    """Render every slide of a draft into its folder, record the paths and save it."""
    profile = store.load_profile(draft.style)
    out_dir = store.draft_dir(draft.id)
    paths = render_slides(profile, draft.slides, out_dir)
    for sl, p in zip(draft.slides, paths):
        sl.rendered_path = str(p.resolve())
    store.save_draft(draft)
    return draft


# ------------------------------------------------------------------ preview

_SAMPLE = {
    "center_statement": dict(kicker="Read this before you post", heading="You don't need more content. You need **better hooks**.",
                             body="7 patterns the top 1% of creators use on every carousel."),
    "top_heading_body": dict(kicker="The problem", heading="Most posts die in the **first second**",
                             body="People decide to swipe or scroll in under a second. If slide one doesn't create a "
                                  "question in their head, nothing after it gets read."),
    "numbered": dict(heading="Lead with the **outcome**, not the process",
                     body="\"How I doubled my reach in 30 days\" beats \"My new posting routine\" every time."),
    "split_image": dict(kicker="Case study", heading="One change. **3x the saves.**",
                        body="We swapped generic stock photos for real behind-the-scenes shots."),
    "list": dict(heading="Steal these hook formulas",
                 bullets=["\"Stop doing X if you want Y\"", "\"I tried X for 30 days — here's what happened\"",
                          "\"The X nobody talks about\"", "\"X mistakes costing you Y\""]),
    "quote": dict(heading="People don't save information. They save **transformation**.", body="Your audience"),
    "cta": dict(heading="Want more like this?", body="Save this post for your next content day and share it with a friend who needs it."),
}


def sample_slides(profile: StyleProfile) -> List[Slide]:
    """One dummy slide per archetype (hook first, CTA last) using realistic copy."""
    archs = list(profile.archetypes)
    if not archs:
        from ..models import SlideArchetype
        archs = [SlideArchetype(name=n, description="", layout=n) for n in LAYOUTS]
    hook = next((a for a in archs if "hook" in a.name.lower() or "cover" in a.name.lower()),
                next((a for a in archs if a.layout == "center_statement"), archs[0]))
    cta = next((a for a in archs if a.layout == "cta" or "cta" in a.name.lower()), None)
    middle = [a for a in archs if a is not hook and a is not cta]
    order = [hook] + middle + ([cta] if cta else [])
    slides = []
    for i, a in enumerate(order, 1):
        layout = a.layout if a.layout in LAYOUTS else ("center_statement" if i == 1 else "top_heading_body")
        copy = dict(_SAMPLE[layout])
        if layout == "numbered":
            copy["kicker"] = None
        if profile.uses_photos and layout == "split_image":
            copy["image_prompt"] = "candid behind-the-scenes photo"
        slides.append(Slide(index=i, archetype=a.name, layout=layout, **copy))
    return slides


def render_preview(style: str) -> List[str]:
    """Render dummy copy in the given style to data/styles/<style>/preview/."""
    profile = store.load_profile(style)
    out_dir = store.style_dir(style) / "preview"
    paths = render_slides(profile, sample_slides(profile), out_dir)
    return [str(p) for p in paths]
