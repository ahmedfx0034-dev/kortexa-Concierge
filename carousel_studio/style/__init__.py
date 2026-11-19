"""Distil a StyleProfile from reference carousels using Claude vision."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from .. import llm, store
from ..models import ReferenceCarousel, SlideArchetype, StyleProfile

__all__ = ["analyze_style", "select_slides", "build_prompt", "ALLOWED_LAYOUTS"]

ALLOWED_LAYOUTS = [
    "center_statement", "top_heading_body", "numbered", "split_image", "list", "quote", "cta",
]
MAX_TOTAL_IMAGES = 40

SYSTEM = """You are a senior brand designer and social-media strategist who reverse-engineers \
Instagram carousel styles so they can be reproduced pixel-faithfully by an HTML/CSS renderer and \
a copywriter. You look closely: you sample colours, identify typefaces, measure hierarchy, and notice \
small recurring details (counters, handles, arrows, borders, textures). You describe what IS there, \
consistently across the set — not generic design advice. When references disagree, describe the \
dominant pattern."""


# ------------------------------------------------------------------ selection

def _engagement(r: ReferenceCarousel) -> int | None:
    if r.likes is None and r.comments is None:
        return None
    return (r.likes or 0) + (r.comments or 0)


def _pick_slides(paths: List[str], n: int) -> List[Tuple[int, str]]:
    """Up to n (1-based slide #, path); keeps the first slides and always the last (CTA)."""
    existing = [(i + 1, p) for i, p in enumerate(paths) if Path(p).exists()]
    if len(existing) <= n:
        return existing
    if n <= 1:
        return existing[:1]
    return existing[: n - 1] + [existing[-1]]


def select_slides(
    refs: List[ReferenceCarousel], max_refs: int, max_slides_per_ref: int, max_total: int = MAX_TOTAL_IMAGES
) -> List[Tuple[ReferenceCarousel, List[Tuple[int, str]]]]:
    # Highest known engagement first; refs with unknown engagement keep their order after those.
    known = sorted((r for r in refs if _engagement(r) is not None), key=_engagement, reverse=True)
    unknown = [r for r in refs if _engagement(r) is None]
    ordered = [r for r in known + unknown if any(Path(p).exists() for p in r.slide_paths)][:max_refs]

    per = max(1, max_slides_per_ref)
    while per > 2 and sum(min(len(r.slide_paths), per) for r in ordered) > max_total:
        per -= 1
    out, total = [], 0
    for r in ordered:
        slides = _pick_slides(r.slide_paths, min(per, max_total - total))
        if not slides:
            break
        out.append((r, slides))
        total += len(slides)
        if total >= max_total:
            break
    return out


# --------------------------------------------------------------------- prompt

def build_prompt(style: str, picked) -> str:
    lines = [
        f"The {sum(len(s) for _, s in picked)} images above are slides from {len(picked)} Instagram "
        f"carousels the user likes and wants to emulate (style name: '{style}'). They are in this order:",
        "",
    ]
    idx = 1
    for n, (ref, slides) in enumerate(picked, 1):
        eng = []
        if ref.likes is not None:
            eng.append(f"{ref.likes} likes")
        if ref.comments is not None:
            eng.append(f"{ref.comments} comments")
        eng_s = f", {', '.join(eng)}" if eng else ""
        total = len(ref.slide_paths)
        first, last = idx, idx + len(slides) - 1
        slide_nums = ", ".join(f"image {idx + k} = slide {num}/{total}" for k, (num, _) in enumerate(slides))
        lines.append(f"Carousel {n} (id {ref.id}, from {ref.origin}{eng_s}): images {first}-{last} — {slide_nums}")
        idx = last + 1
    lines.append("")

    captions = [(n, r.caption.strip()) for n, (r, _) in enumerate(picked, 1) if r.caption and r.caption.strip()]
    if captions:
        lines.append("Post captions (use these for caption_style and tone):")
        for n, c in captions:
            c = c if len(c) <= 1200 else c[:1200] + " …"
            lines.append(f"--- Carousel {n} caption ---\n{c}")
        lines.append("")
    else:
        lines.append("No captions are available; infer caption_style from the on-slide voice "
                     "(keep it a sensible, concrete recommendation).\n")

    lines.append(f"""Distil ONE reusable style profile that a renderer (HTML/CSS, 1080x1350 slides) and a \
copywriter can follow to produce new carousels that look and read like these. Be precise and concrete:

PALETTE — sample actual colours from the slides and give exact-ish uppercase hex codes (#RRGGBB):
background (dominant slide background), surface (cards/panels/boxes; if none, a subtle shift of the \
background), text (main heading/body colour), muted_text (secondary text, counters, handles), accent \
(highlight colour used for emphasis words, underlines, shapes), accent_2 (second accent; if only one \
exists, a tint/shade of it). Ensure text vs background has strong contrast as in the references.

TYPOGRAPHY — name the closest Google Fonts families (real family names, e.g. 'Inter', 'Montserrat', \
'Playfair Display', 'Archivo Black', 'DM Serif Display', 'Space Grotesk', 'Bebas Neue', 'Poppins'). \
heading_weight is a CSS weight 400-900. heading_case is exactly 'upper', 'title' or 'sentence'. \
heading_size is exactly 'xl', 'l' or 'm' (how much of the slide the headline dominates).

ARCHETYPES — the recurring slide types, in the order they typically appear in a carousel (3-7 of them). \
Each `layout` MUST be exactly one of: {', '.join(repr(l) for l in ALLOWED_LAYOUTS)}.
  - The FIRST archetype must be the hook/cover slide (name 'hook') with layout 'center_statement' \
(unless the covers clearly use 'split_image').
  - The LAST archetype must be the closing slide (name 'cta') with layout 'cta' — follow/save/share/comment ask.
  - In between, the content slide types (e.g. 'numbered_point', 'tip', 'quote', 'list', 'example').
  - In each description, say concretely where text sits (alignment, vertical position), relative sizes \
of kicker/heading/body, use of highlight colour on keywords, any boxes/cards/images, and margins.

DECORATIONS — every recurring visual motif worth reproducing, each as a short concrete phrase with \
position: e.g. 'slide counter "2/8" top-right in muted text', '@handle bottom-left', 'swipe arrow → \
bottom-right on cover', 'thin accent underline under key word', 'rounded 24px card', '1px border inset', \
'paper grain texture', 'author avatar + name top-left', 'progress bar along bottom'. Omit nothing that repeats.

uses_photos — true only if photographic imagery is a core part of most slides (not just an avatar).
words_per_slide — typical word count on a content slide (count them). slide_count — typical total \
slides per carousel (3-20), using the full slide counts given above, not just the images shown.
hook_patterns — 3-6 patterns for how the cover slide hooks (e.g. 'bold contrarian claim', \
'"X mistakes killing your Y"', 'number + promise'), with a short example in each, modelled on what you see.
tone — the copy voice (person, sentence length, punctuation, emoji use, jargon level).
caption_style — length, structure (hook line, line breaks, bullets), emojis, CTA, number and kind of hashtags.
summary — 2-3 sentences that would let a designer picture the style instantly.
Set name to '{style}'.""")
    return "\n".join(lines)


# ------------------------------------------------------------- post-process

_LAYOUT_SYNONYMS = {
    "center": "center_statement", "centered": "center_statement", "statement": "center_statement",
    "hook": "center_statement", "cover": "center_statement", "title": "center_statement",
    "heading_body": "top_heading_body", "top_heading": "top_heading_body", "text": "top_heading_body",
    "number": "numbered", "numbered_point": "numbered", "step": "numbered",
    "image": "split_image", "photo": "split_image", "split": "split_image",
    "bullets": "list", "bullet": "list", "checklist": "list",
    "quotation": "quote", "testimonial": "quote",
    "call_to_action": "cta", "closing": "cta", "outro": "cta", "follow": "cta",
}


def _fix_layout(layout: str) -> str:
    l = re.sub(r"[^a-z_]+", "_", (layout or "").strip().lower()).strip("_")
    if l in ALLOWED_LAYOUTS:
        return l
    if l in _LAYOUT_SYNONYMS:
        return _LAYOUT_SYNONYMS[l]
    for k, v in _LAYOUT_SYNONYMS.items():
        if k in l:
            return v
    return "top_heading_body"


def _fix_hex(h: str, fallback: str) -> str:
    m = re.search(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", h or "")
    if not m:
        return fallback
    v = m.group(1)
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return "#" + v.upper()


def _normalize(profile: StyleProfile, style: str, ref_ids: List[str]) -> StyleProfile:
    profile.name = style
    profile.reference_ids = ref_ids

    p = profile.palette
    p.background = _fix_hex(p.background, "#FFFFFF")
    p.text = _fix_hex(p.text, "#111111")
    p.surface = _fix_hex(p.surface, p.background)
    p.muted_text = _fix_hex(p.muted_text, p.text)
    p.accent = _fix_hex(p.accent, p.text)
    p.accent_2 = _fix_hex(p.accent_2, p.accent)

    t = profile.typography
    t.heading_weight = min(900, max(100, int(round(t.heading_weight / 100.0)) * 100 or 700))
    if t.heading_case not in ("upper", "title", "sentence"):
        c = t.heading_case.lower()
        if "title" in c:
            t.heading_case = "title"
        elif "up" in c or "cap" in c:
            t.heading_case = "upper"
        else:
            t.heading_case = "sentence"
    if t.heading_size not in ("xl", "l", "m"):
        s = t.heading_size.lower()
        t.heading_size = "xl" if "x" in s or "huge" in s else ("m" if "m" in s or "small" in s else "l")

    archs = list(profile.archetypes)
    for a in archs:
        a.layout = _fix_layout(a.layout)
    if not any(a.layout == "center_statement" for a in archs):
        archs.insert(0, SlideArchetype(
            name="hook",
            description="Cover slide: one bold statement centred on the slide, large heading, minimal extra text.",
            layout="center_statement",
        ))
    ctas = [a for a in archs if a.layout == "cta"]
    if ctas:
        archs = [a for a in archs if a.layout != "cta"] + ctas[-1:]
    else:
        archs.append(SlideArchetype(
            name="cta",
            description="Closing slide: short recap line and a clear follow/save/share ask with the handle.",
            layout="cta",
        ))
    profile.archetypes = archs

    profile.slide_count = min(20, max(3, profile.slide_count))
    profile.words_per_slide = max(1, profile.words_per_slide)
    return profile


# --------------------------------------------------------------------- public

def analyze_style(style: str, max_refs: int = 8, max_slides_per_ref: int = 6) -> StyleProfile:
    """Look at the style's reference carousels with Claude vision and save a StyleProfile."""
    refs = store.list_references(style)
    if not refs:
        raise ValueError(
            f"No reference carousels for style '{style}'. Add some first, e.g. "
            f"`studio ingest {style} ./screenshots` or `studio ingest {style} @handle` "
            f"or an instagram.com/p/... URL."
        )
    picked = select_slides(refs, max_refs, max_slides_per_ref)
    if not picked:
        raise ValueError(f"Reference images for style '{style}' are missing on disk; re-run ingest.")

    images = [path for _, slides in picked for _, path in slides]
    prompt = build_prompt(style, picked)
    profile = llm.ask_json(prompt, StyleProfile, images=images, system=SYSTEM)
    profile = _normalize(profile, style, [r.id for r, _ in picked])
    store.save_profile(profile)
    return profile
