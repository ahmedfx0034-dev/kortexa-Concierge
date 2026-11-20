"""Turn slides + a StyleProfile into 1080x1350 PNGs via Jinja2 HTML templates and
headless Chromium. Everything visual is derived from the profile's tokens."""
from __future__ import annotations

import base64
import html
import logging
import mimetypes
import re
from difflib import SequenceMatcher
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
LAYOUTS = ("center_statement", "top_heading_body", "numbered", "split_image", "list", "quote", "cta",
           "before_after", "photo")
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
    on_accent = _best_on(accent)
    if on_accent == "#111111":  # prefer the brand's own black on the accent (black text on a lime button)
        darkest = min((bg, text), key=_lum)
        if _lum(darkest) < 0.02 and contrast(darkest, accent) >= 4.5:
            on_accent = darkest
    # an accent bright enough to read on a dark photo scrim (used by photo layouts)
    hl_dark = max((accent, accent2), key=lambda x: contrast(x, "#030305"))
    return dict(
        bg=bg, surface=surface, text=text, muted=muted, accent=accent, accent2=accent2,
        on_accent=on_accent, hl=hl, hl_dark=hl_dark, is_dark=is_dark, card_text=card_text,
        tint=_mix(bg, accent, 0.07 if not is_dark else 0.05),
        panel=_mix(bg, "#FFFFFF", 0.055) if is_dark else _mix(bg, "#000000", 0.035),
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
    reqs = [(hf, {w, 700, 900}), (bf, {400, 500, 600, 700})]
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
             brand=None, underline=False, rule_h=10, bar=None, bar_hero=False, frame=False, frame_w=2,
             frame_radius=0, frame_color=None, grain=False, grain_opacity=0.10, progress=False, glow=False,
             glow_hero=False, dots=False, grid=False, blob=False, card=False, marker=False, outline_numbers=False,
             numbered_marks=False, logo=None, logo_mark=False, footer=None, eyebrow=False, eyebrow_bar=False,
             callout=False, number_rows=False, cta_button=False)
    for raw in decorations or []:
        s = raw.lower()
        if re.search(r"\bfooter\b", s):
            q = re.search(r"[\"\u201c\u2018']([^\"\u201d\u2019']{2,60})[\"\u201d\u2019']", raw)
            d["footer"] = q.group(1).strip() if q else True
            s_rest = re.sub(r"[\"\u201c\u2018'][^\"\u201d\u2019']*[\"\u201d\u2019']", "", s)
            # "footer with slide counter" also turns the counter on (bottom-right by default)
            if re.search(r"counter|page number|slide number", s_rest):
                d["counter"] = _pos(s_rest.replace("footer", "bottom"), "br")
            continue
        if re.search(r"counter|page number|slide number|pagination|\d+\s*/\s*\d+|\d+ of \d+", s):
            d["counter"] = _pos(s, "tr")
            d["counter_pad"] = bool(re.search(r"\b0\d\b", s))
            d["counter_pill"] = any(k in s for k in ("pill", "badge", "capsule", "rounded"))
        if re.search(r"handle|username|@\w|account name", s):
            d["handle"] = _pos(s, "bl")
        if re.search(r"swipe|arrow|chevron|next ?\u2192|\u2192", s):
            d["swipe"] = _pos(s, "br")
            d["swipe_word"] = "swipe" in s
        if re.search(r"\blogo\b", s):
            d["logo"] = _pos(s, "tl")
            d["logo_mark"] = bool(re.search(r"\bmark\b|\bicon\b|\bsymbol\b", s))
            d["brand"] = d["logo"]  # text fallback when the brand has no logo file
        elif re.search(r"brand ?name|wordmark", s):
            d["brand"] = _pos(s, "tl")
        if re.search(r"eyebrow|kicker label|letter-?spaced (label|kicker)", s):
            d["eyebrow"] = True
            d["eyebrow_bar"] = bool(re.search(r"\bbar\b|\bdash\b|\brule\b|\bline\b", s))
            continue
        if re.search(r"\bcallout\b|takeaway box|left[- ]border", s):
            d["callout"] = True
            continue
        if re.search(r"numbered rows|number(ed)? rows|big (lime |accent )?numbers?|row numbers", s):
            d["number_rows"] = True
            continue
        if re.search(r"\bbutton\b", s):
            d["cta_button"] = True
            continue
        if "underline" in s or "rule under" in s:
            d["underline"] = True
            if "thin" in s or "hairline" in s:
                d["rule_h"] = 4
        if re.search(r"(accent|colou?r|side|vertical|edge)[\w\s]*\b(bar|stripe|strip|band)\b|\bbar\b|\bstripe\b", s) \
                and "progress" not in s and "underline" not in s:
            d["bar"] = "top" if "top" in s else "bottom" if "bottom" in s else "left"
            d["bar_hero"] = bool(re.search(r"cover|hook|first", s))
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
            d["glow_hero"] = bool(re.search(r"cover|hook|first", s))
        if re.search(r"dot(s|ted)? (grid|pattern)|polka|halftone", s):
            d["dots"] = True
        elif re.search(r"grid", s):
            d["grid"] = True
        if re.search(r"blob|circle|shape|orb", s):
            d["blob"] = True
        if re.search(r"card|panel|box|container", s) and "outline box" not in s:
            d["card"] = True
        # "highlight words in lime" means coloured text; a marker/highlighter means a box behind the words
        if re.search(r"marker|highlighter|highlight (box|block|band)", s) or (
                "highlight" in s and not re.search(r"text|word|colou?r|lime|accent", s)):
            d["marker"] = True
        if re.search(r"outline(d)? (number|numeral|digit)", s):
            d["outline_numbers"] = True
        if re.search(r"numbered (bullet|list)|number badge", s):
            d["numbered_marks"] = True
    d["kit"] = bool(d["footer"] or d["eyebrow"])  # refined, letter-spaced chrome (playbook look)
    return d


# -------------------------------------------------------------------- logos

_LOGO_CACHE: dict = {}


def _resolve_asset(path: Optional[str]) -> Optional[Path]:
    if not path:
        return None
    p = Path(path)
    for c in ([p] if p.is_absolute() else [config.ROOT / p, config.DATA_DIR.parent / p, config.DATA_DIR / p,
                                           Path.cwd() / p]):
        if c.is_file():
            return c
    return None


def _png_uri(im) -> str:
    import io

    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def logo_variants(path: Optional[str]) -> Optional[dict]:
    """Load a transparent logo PNG and split it into variants by its horizontal bands:
    'full' (everything), 'lockup' (mark + wordmark, no tagline) and 'mark' (the symbol only).
    Returns {variant: {"uri": data-URI, "ratio": w/h}} or None if the file is missing."""
    p = _resolve_asset(path)
    if not p:
        return None
    key = (str(p), p.stat().st_mtime)
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    try:
        from PIL import Image

        im = Image.open(p).convert("RGBA")
        alpha = im.getchannel("A").point(lambda v: 255 if v > 40 else 0)
        w, h = im.size
        rw = max(1, w // 4)
        rows = alpha.resize((rw, h)).tobytes()
        ink = [any(rows[y * rw + x] for x in range(rw)) for y in range(h)]
        bands, start = [], None
        for y, on in enumerate(ink + [False]):
            if on and start is None:
                start = y
            elif not on and start is not None:
                if bands and start - bands[-1][1] < h * 0.025:   # tiny gap: same band
                    bands[-1] = (bands[-1][0], y)
                else:
                    bands.append((start, y))
                start = None

        def crop(y0: int, y1: int) -> dict:
            part = im.crop((0, y0, w, y1))
            bb = part.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox() or (0, 0, w, y1 - y0)
            part = part.crop(bb)
            return {"uri": _png_uri(part), "ratio": round(part.width / max(1, part.height), 4)}

        if not bands:
            out = None
        else:
            top, bottom = bands[0][0], bands[-1][1]
            full = crop(top, bottom)
            out = {"full": full,
                   "lockup": crop(top, bands[1][1]) if len(bands) >= 3 else full,
                   "mark": crop(*bands[0]) if len(bands) >= 2 else full}
    except Exception as e:  # never let a bad logo break rendering
        log.warning("Could not load logo %s: %s", p, e)
        out = None
    _LOGO_CACHE[key] = out
    return out


def brand_logo(brand: dict, dark_bg: bool) -> Optional[dict]:
    """Logo variants for a background: logo_dark is the version made for dark slides."""
    order = ("logo_dark", "logo_light", "logo") if dark_bg else ("logo_light", "logo_dark", "logo")
    for k in order:
        v = logo_variants(brand.get(k))
        if v:
            return v
    return None


def _logo_img(v: dict, height: int, cls: str) -> str:
    return (f'<img class="{cls}" src="{v["uri"]}" alt="" '
            f'style="height:{height}px;width:{round(height * v["ratio"])}px">')


def _footer_html(text: str, tagline: bool = False) -> str:
    """'KORTEXA · AI WORKFLOWS' -> first part muted, the rest in the accent colour.
    tagline=True renders every part in the accent (the closing slide)."""
    parts = [x.strip() for x in re.split(r"\s*[\u00b7|\u2022]\s*", text) if x.strip()]
    esc = html.escape
    if tagline:
        inner = ' <span class="sep">\u00b7</span> '.join(esc(x) for x in parts)
        return f'<div class="chip footer tagline"><span class="fl">{inner}</span></div>'
    if len(parts) < 2:
        return f'<div class="chip footer">{esc(text)}</div>'
    rest = ' <span class="sep">\u00b7</span> '.join(esc(x) for x in parts[1:])
    return (f'<div class="chip footer"><span>{esc(parts[0])}</span> <span class="sep">\u00b7</span> '
            f'<span class="fl">{rest}</span></div>')


def _chrome(deco: dict, brand: dict, index: int, total: int, layout: str, on_image: bool,
            logo: Optional[dict] = None, hero: bool = False) -> dict:
    slots = {"tl": [], "tr": [], "bl": [], "br": []}
    esc = html.escape
    if deco["logo"] and logo and not hero:
        v = logo["mark"] if deco["logo_mark"] else logo["lockup"]
        slots[deco["logo"]].append(_logo_img(v, 64 if deco["logo_mark"] else 60, "chip logo"))
    elif deco["brand"] and brand.get("brand_name") and not (hero and deco["logo"] and logo):
        slots[deco["brand"]].append(f'<div class="chip brand">{esc(brand["brand_name"])}</div>')
    if deco["footer"]:
        text = deco["footer"] if isinstance(deco["footer"], str) else (
            brand.get("footer") or (brand.get("brand_name") or "").upper())
        tagline = bool(hero and layout == "cta" and brand.get("tagline"))
        if tagline:
            text = brand["tagline"].upper()  # all-accent tagline, like the playbook's last page
        if text:
            slots["bl"].append(_footer_html(text, tagline))
    if deco["handle"] and brand.get("instagram_handle") and layout != "cta":
        h = brand["instagram_handle"]
        h = h if h.startswith("@") else "@" + h
        slots[deco["handle"]].append(f'<div class="chip handle">{esc(h)}</div>')
    if deco["counter"] and not (hero and deco["kit"]):
        pad = deco["counter_pad"] or deco["kit"]
        txt = f"{index:02d} / {total:02d}" if pad else f"{index}/{total}"
        pill = deco["counter_pill"] or (on_image and deco["counter"].startswith("t"))
        cls = "chip counter pill" if pill else "chip counter"
        slots[deco["counter"]].append(f'<div class="{cls}">{txt}</div>')
    if deco["swipe"] and index < total:
        word = "Swipe" if deco["swipe_word"] else ""
        slots[deco["swipe"]].append(f'<div class="chip swipe">{word}<span class="arrow">{_ARROW}</span></div>')
    # items on the right should read outward (arrow last)
    return {k: [Markup(x) for x in v] for k, v in slots.items()}


# ------------------------------------------------------------------- text


_OPEN_PREV = set(" \t\n\r([{\u2014\u2013-\u201c\u2018\u00a0")


def smart_quotes(t: str) -> str:
    """Curly quotes/apostrophes. ** emphasis markers are transparent when deciding
    whether a quote opens or closes (so `**'the` still opens)."""
    out: list[str] = []
    prev = ""  # previous significant char (skipping ** markers)
    i = 0
    while i < len(t):
        ch = t[i]
        if t.startswith("**", i):
            out.append("**")
            i += 2
            continue
        if ch in "\"'":
            opening = (not prev) or prev in _OPEN_PREV
            if ch == "'" and opening and re.match(r"'\d\ds?\b", t[i:]):
                opening = False  # '90s -> ’90s
            if ch == '"':
                ch = "\u201c" if opening else "\u201d"
            else:
                ch = "\u2018" if opening else "\u2019"
        out.append(ch)
        prev = ch
        i += 1
    return "".join(out)


_QUOTE_CHARS = "\"\u201c\u201d\u201e'\u2018\u2019"


def strip_quote_marks(t: str) -> str:
    """Drop leading/trailing quote characters (the quote layout draws its own mark)."""
    t = t.strip()
    lead = re.match(r"^((?:\*\*)?)[" + _QUOTE_CHARS + r"]+\s*", t)
    if lead:
        t = lead.group(1) + t[lead.end():]
    chars = _QUOTE_CHARS if lead else "\"\u201c\u201d\u201e"
    t = re.sub(r"\s*[" + chars + r"]+((?:\*\*)?)$", r"\1", t)
    return t.strip()


def rich(text: Optional[str], *, paragraphs: bool = False, case_fn=None) -> Markup:
    """Escape, apply heading case, turn **x** into accent spans and newlines into breaks."""
    if not text:
        return Markup("")
    t = text.strip()
    if case_fn:
        t = case_fn(t)
    t = html.escape(smart_quotes(t), quote=False)
    t = re.sub(r"\*\*(.+?)\*\*",
               lambda m: '<span class="hl%s">%s</span>' % (" hlnw" if len(m.group(1).split()) <= 3 else "", m.group(1)), t)
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
        self.deco["message"] = "message" in (profile.name + " " + " ".join(profile.decorations or [])).lower()
        fc = self.deco["frame_color"]
        self.deco["frame_color"] = self.c["accent"] if fc == "accent" else self.c["line"]
        if not self.c["is_dark"] and not self.deco.get("grain_strong"):
            self.deco["grain_opacity"] = 0.05  # multiply-grain greys out light backgrounds quickly
        self.logo = brand_logo(brand, self.c["is_dark"]) if self.deco["logo"] else None
        self.logo_on_dark = (brand_logo(brand, True) if self.deco["logo"] else None)
        tops = {self.deco[k] for k in ("counter", "handle", "brand", "logo") if self.deco[k]}
        bottoms = tops | ({self.deco["swipe"]} if self.deco["swipe"] else set()) | ({"bl"} if self.deco["footer"] else set())
        self.has_top = any(p and p.startswith("t") for p in bottoms)
        self.has_bottom = any(p and p.startswith("b") for p in bottoms)


def _context(theme: _Theme, slide: Slide, total: int, numbered_ordinal: int, base: Optional[Path]) -> dict:
    p, t, brand = theme.profile, theme.t, theme.brand
    layout = slide.layout if slide.layout in LAYOUTS else _fallback_layout(slide, total)
    case_fn = title_case if t["title"] else None
    is_first, is_last = slide.index == 1, slide.index == total

    deco = theme.deco
    ba_images: list = []
    if layout == "before_after":
        # image_path is the AFTER photo; "before.jpg | after.jpg" gives both panels a photo
        paths = [x.strip() for x in re.split(r"\s*[|;]\s*", slide.image_path or "") if x.strip()]
        if len(paths) == 1:
            paths = [None, paths[0]]
        ba_images = [_image_uri(x, base) if x else None for x in paths[:2]] + [None, None]
        ba_images = ba_images[:2]
        image_uri = None
    else:
        image_uri = _image_uri(slide.image_path, base)
    photo_bg = layout == "photo"
    on_image = bool(layout == "split_image" or image_uri)
    # cover/hook and closing slides carry the full logo, large (like the playbook's cover and last page)
    hero = bool(deco["logo"] and theme.logo and layout in ("center_statement", "cta", "photo")
                and (is_first or is_last))
    logo = theme.logo_on_dark if photo_bg else theme.logo
    chrome = _chrome(deco, brand, slide.index, total, layout,
                     on_image and layout in ("split_image", "photo"), logo, hero)

    chrome_h = 60 if deco["kit"] else 44
    chrome_y = 60 if deco["kit"] else 64
    top = chrome_y + chrome_h + 52 if theme.has_top else 110
    bottom = chrome_y + chrome_h + 52 if theme.has_bottom else 110
    hero_logo = None
    if hero and logo:
        hv = logo["full"] if layout != "photo" else logo["lockup"]  # the tiny tagline turns to noise on a photo
        hh = 150 if layout != "photo" else 104
        hero_logo = Markup(_logo_img(hv, hh, "hero-logo"))
        top = max(top, 72 + hh + 70)
    media_h = 610
    if layout == "split_image":
        top = media_h + 56
    grow = {"center_statement": 1.0, "cta": 1.0, "quote": 1.1, "split_image": 1.08, "photo": 1.0,
            "before_after": 1.1, "top_heading_body": 1.4}.get(layout, 1.18)
    if layout == "list" and deco["number_rows"]:
        grow = 1.35
    if deco["kit"] and layout in ("center_statement", "cta"):
        grow = 1.15  # the playbook look lets cover/statement type run large
    geo = dict(top=top, bottom=bottom, media_h=media_h, grow=grow, chrome_h=chrome_h, chrome_y=chrome_y)

    kicker = slide.kicker
    number = f"{numbered_ordinal:02d}"
    if layout == "numbered" and kicker:
        m = re.fullmatch(r"\s*(?:#|no\.?|step|tip|rule|mistake|lesson|part|point|reason|myth|fix|way|day|week)?\s*"
                         r"(\d{1,2})(?:\s*(?:/|of)\s*\d{1,2})?[.):]?\s*", kicker, re.I)
        if m:
            number, kicker = f"{int(m.group(1)):02d}", None

    s = dict(
        index=slide.index, layout=layout,
        kicker=Markup(html.escape(smart_quotes(_plain(kicker)))) if kicker else None,
        heading=rich(strip_quote_marks(slide.heading) if layout == "quote" else slide.heading, case_fn=case_fn),
        body=rich(slide.body, paragraphs=True) if slide.body else None,
        bullets=[rich(b) for b in slide.bullets if b and b.strip()],
    )
    show_glow = deco["glow"] and (not deco["glow_hero"] or (hero or is_first or (is_last and layout == "cta")))
    show_bar = deco["bar"] and (not deco["bar_hero"] or hero or is_first or (is_last and layout == "cta"))
    ctx = dict(
        s=s, c=theme.c, t=t, fonts=theme.fonts, font_css=Markup(theme.fonts["css"]), deco=deco,
        chrome=chrome, chrome_on_image=layout in ("split_image", "photo"), geo=geo, total=total,
        is_first=is_first, is_last=is_last, image_uri=image_uri, number=number,
        align=_align_for(p, slide.archetype, layout), hero_logo=hero_logo, hero=hero,
        show_glow=show_glow, show_bar=show_bar,
    )
    if layout == "list" and deco["number_rows"]:
        rows = []
        src = [b for b in slide.bullets if b and b.strip()]
        if not src and slide.body:
            src = [ln.strip(" -\u2022*\t") for ln in slide.body.splitlines() if ln.strip(" -\u2022*\t")]
        for b in src:
            title, desc = _split_row(b)
            rows.append(dict(title=rich(title) if title else None, desc=rich(desc) if desc else None))
        ctx["rows"] = rows
    if layout == "before_after":
        before, after = _before_after_text(slide)
        ctx.update(before=_ba_lines(before), after=_ba_lines(after), before_img=ba_images[0],
                   after_img=ba_images[1], ba_labels=_ba_labels(slide))
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
            ctx.update(attribution=html.escape(smart_quotes(body.lstrip("—–- ").strip())), quote_body=None)
        else:
            ctx.update(attribution=None, quote_body=s["body"])
    if layout == "quote":
        ctx["quote_card"] = bool(theme.deco["card"] or theme.deco["message"])
    if layout == "cta":
        cta = (brand.get("call_to_action") or "").strip()
        seen = (_plain(slide.heading) + " " + _plain(slide.body)).lower()
        handle = brand.get("instagram_handle") or ""
        if handle and not handle.startswith("@"):
            handle = "@" + handle
        name = brand.get("brand_name") or handle.lstrip("@") or "•"
        cta_text = cta if cta and cta.lower().rstrip(".!") not in seen else None
        if slide.body and slide.index == total and _is_brand_cta(slide.body, cta, handle):
            # the brand call to action lives in slide.body: render it as the button
            cta_text = Markup(html.escape(smart_quotes(_plain(slide.body))))
            s["body"] = None
        elif cta_text:
            cta_text = Markup(html.escape(smart_quotes(cta_text)))
        ctx.update(cta_text=cta_text, handle=handle, initial=name[:1].upper())
    return ctx


def _split_row(text: str) -> tuple[Optional[str], Optional[str]]:
    """'The photo dump: twenty photos in random order' -> ('The photo dump', 'twenty photos ...')."""
    t = text.strip()
    m = re.match(r"^(.{2,48}?)\s*(?::|\s[\u2014\u2013-]\s)\s*(.+)$", t, re.S)
    if m and len(_plain(m.group(1)).split()) <= 6:
        desc = m.group(2).strip()
        i = next((j for j, ch in enumerate(desc) if ch.isalpha()), None)
        if i is not None and desc[i].islower():
            desc = desc[:i] + desc[i].upper() + desc[i + 1:]
        return m.group(1).strip(), desc
    if len(t.split()) <= 6:
        return t, None
    return None, t


def _before_after_text(slide: Slide) -> tuple[str, str]:
    """BEFORE / AFTER copy. Either 'Before: ...' and 'After: ...' sections in the body,
    or body = before and bullets = the after lines."""
    body = (slide.body or "").strip()
    parts = re.split(r"(?im)^\s*\**\s*(before|after)\s*\**\s*[:\-\u2013\u2014]\s*", body)
    if len(parts) >= 3:
        found = {parts[i].lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
        before, after = found.get("before", ""), found.get("after", "")
        if not after and slide.bullets:
            after = "\n".join(slide.bullets)
        return before, after
    return body, "\n".join(b for b in slide.bullets if b and b.strip())


def _ba_lines(text: str) -> list:
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = re.match(r"^(\u2713|\u2714|\[x\]|-\s|\u2022|\*\s)\s*", ln)
        if m:
            ln = ln[m.end():]
        out.append(dict(text=rich(ln), check=bool(m)))
    return out


def _ba_labels(slide: Slide) -> tuple[str, str]:
    return "Before", "After"


def _is_brand_cta(body: str, cta: str, handle: str) -> bool:
    norm = lambda x: re.sub(r"[^a-z0-9@ ]+", "", _plain(x).lower().replace("\u2019", "'")).strip()  # noqa: E731
    b, c = norm(body), norm(cta)
    if c and (b == c or (len(b) >= 12 and (b in c or c in b)) or SequenceMatcher(None, b, c).ratio() > 0.75):
        return True
    return bool(handle and handle.lower() in b and re.search(r"\b(dm|follow|message)\b", b))


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
