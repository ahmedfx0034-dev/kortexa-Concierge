"""Idea generation and carousel copywriting in a learned StyleProfile."""
from __future__ import annotations

import difflib
import json
import logging
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from .. import llm, store
from ..config import get_settings
from ..models import CarouselDraft, DraftStatus, Idea, Slide, SlideArchetype, StyleProfile, utcnow

log = logging.getLogger(__name__)

MAX_HASHTAGS = 30
MAX_CAPTION = 2200
MAX_SLIDES = 20  # Instagram carousel limit


# ------------------------------------------------------------ LLM schemas

class IdeaList(BaseModel):
    ideas: List[Idea]


class SlideCopy(BaseModel):
    archetype: str = Field(description="Exact name of one of the style's archetypes")
    kicker: Optional[str] = Field(default=None, description="Optional tiny label above the heading (1-4 words)")
    heading: str = Field(description="The main line of the slide")
    body: Optional[str] = Field(default=None, description="Supporting text, or null")
    bullets: List[str] = Field(default_factory=list, description="Short list items, only for list-style slides")
    image_prompt: Optional[str] = Field(default=None, description="Photo to generate, only if the style uses photos")


class CarouselCopy(BaseModel):
    slides: List[SlideCopy]
    caption: str = Field(description="Instagram caption without the hashtags")
    hashtags: List[str] = Field(description="Hashtags, each starting with #")


SYSTEM = (
    "You are a world-class Instagram carousel strategist and copywriter. You write carousels people "
    "save and share because every slide delivers something concrete: a specific tactic, number, "
    "example, template or insight — never filler, never generic motivational fluff. You match the "
    "voice and structure of the creator's established style precisely."
)


# ---------------------------------------------------------------- context

def _brand_block(brand: dict) -> str:
    avoid = brand.get("topics_to_avoid") or []
    return (
        f"Brand: {brand.get('brand_name', '')} ({brand.get('instagram_handle', '')})\n"
        f"Niche: {brand.get('niche', '')}\n"
        f"Audience: {brand.get('audience', '')}\n"
        f"Goals: {brand.get('goals', '')}\n"
        f"Call to action: {brand.get('call_to_action', '')}\n"
        f"Topics to avoid: {', '.join(avoid) if avoid else 'none'}\n"
        f"Language: write everything in {brand.get('language', 'English')}"
        + _extras_block(brand)
        + _content_bank_block()
        + _framework_block()
    )


def _framework_block(limit: int = 9000) -> str:
    """The owner's copywriting method (data/copy_framework.md), if present."""
    from ..config import DATA_DIR

    p = DATA_DIR / "copy_framework.md"
    if not p.exists():
        return ""
    return "\n\nCopywriting framework (follow it):\n<framework>\n" + p.read_text().strip()[:limit] + "\n</framework>"


def _extras_block(brand: dict) -> str:
    """Optional positioning fields in brand.json (statement, beliefs, rules, offer)."""
    out = []
    for key, label in (("offer", "What we sell"), ("brand_statement", "Brand statement"),
                       ("contrarian_belief", "Core belief"), ("voice", "Voice")):
        if brand.get(key):
            out.append(f"{label}: {brand[key]}")
    for key, label in (("content_pillars", "Content pillars"), ("content_rules", "Content rules (must follow)")):
        items = brand.get(key) or []
        if items:
            out.append(f"{label}:\n" + "\n".join(f"- {x}" for x in items))
    return ("\n" + "\n".join(out)) if out else ""


def _content_bank_block(limit: int = 12000) -> str:
    """Free-form notes (e.g. pulled from Notion) in data/content_bank.md: real stories,
    client conversations, results and drafts the writer should draw from."""
    from ..config import DATA_DIR

    p = DATA_DIR / "content_bank.md"
    if not p.exists():
        return ""
    text = p.read_text().strip()[:limit]
    return ("\n\nContent bank (real material from the owner — prefer these facts, stories and "
            "phrasing over generic claims; never invent results or numbers that aren't here):\n"
            f"<content_bank>\n{text}\n</content_bank>") if text else ""


def _style_block(p: StyleProfile) -> str:
    archs = "\n".join(f"  - {a.name} (layout: {a.layout}): {a.description}" for a in p.archetypes)
    return (
        f"Style '{p.name}': {p.summary}\n"
        f"Tone of voice: {p.tone}\n"
        f"Hook patterns that work for this style:\n" + "\n".join(f"  - {h}" for h in p.hook_patterns) + "\n"
        f"Typical slide count: {p.slide_count}; typical words per content slide: {p.words_per_slide}\n"
        f"Caption style: {p.caption_style}\n"
        f"Headings are rendered in {p.typography.heading_case} case, size {p.typography.heading_size}.\n"
        f"Slide archetypes (name, layout, look):\n{archs}\n"
        f"Uses photos: {'yes' if p.uses_photos else 'no'}"
    )


_LAYOUT_RULES = {
    "center_statement": "one bold statement as heading; body optional and short",
    "top_heading_body": "heading + a body of 1-3 short sentences",
    "numbered": "one numbered point: heading is the point, body explains it (the renderer draws the number)",
    "split_image": "short heading + 1 sentence body; the top half is a photo",
    "list": "heading + 3-6 bullets of under 10 words each in `bullets`; body usually null",
    "quote": "heading is the quote itself; body is the attribution (e.g. '— Naval') or null",
    "cta": "heading invites the action; body gives the reason; the brand CTA is added as a button",
}


# ----------------------------------------------------------------- ideas

def generate_ideas(style: str, n: int = 5, theme: Optional[str] = None) -> List[Idea]:
    """Brainstorm n carousel ideas that fit the style and brand, avoiding past titles."""
    profile = store.load_profile(style)
    brand = get_settings().brand
    recent = store.recent_titles()
    prompt = (
        f"{_brand_block(brand)}\n\n{_style_block(profile)}\n\n"
        f"Propose {n} carousel ideas for this audience"
        + (f", all around the theme: {theme}" if theme else "")
        + ".\n\nRequirements:\n"
        "- Each idea must be genuinely useful and save-worthy: a framework, checklist, step-by-step, "
        "teardown, mistakes-to-avoid, before/after, swipe file or counter-intuitive insight the audience "
        "can act on today.\n"
        "- Be specific (numbers, named tools, concrete situations) rather than broad.\n"
        "- `hook` is the exact first-slide line, written using one of the style's hook patterns and its tone, "
        "short enough for a slide (ideally under 12 words).\n"
        "- `angle` explains in one sentence why this audience will care / save it.\n"
        "- Vary formats and angles across the ideas.\n"
        "- Avoid the brand's topics to avoid.\n"
        + ("- Do not repeat or closely paraphrase these previous titles:\n"
           + "\n".join(f"  * {t}" for t in recent) + "\n" if recent else "")
    )
    out = llm.ask_json(prompt, IdeaList, system=SYSTEM)
    seen = {t.strip().lower() for t in recent}
    ideas = [i for i in out.ideas if i.title.strip().lower() not in seen]
    return (ideas or out.ideas)[:n]


# ----------------------------------------------------------------- writing

def _write_prompt(profile: StyleProfile, brand: dict, idea: Idea, feedback: Optional[str],
                  previous: Optional[CarouselDraft]) -> str:
    hook = _hook_arch(profile)
    cta = _cta_arch(profile)
    layouts = sorted({a.layout for a in profile.archetypes})
    rules = "\n".join(f"  - {l}: {_LAYOUT_RULES[l]}" for l in layouts if l in _LAYOUT_RULES)
    parts = [
        _brand_block(brand), "", _style_block(profile), "",
        f"Write a complete carousel for this idea:\nTitle: {idea.title}\nAngle: {idea.angle}\nHook: {idea.hook}",
        "",
        "Rules:",
        f"- About {profile.slide_count} slides (never more than {MAX_SLIDES}).",
        f"- Slide 1 uses archetype '{hook.name}' and carries the hook (adapt the hook line if it makes it stronger).",
        f"- The last slide uses archetype '{cta.name}' and drives this call to action: "
        f"\"{brand.get('call_to_action', '')}\".",
        "- Every slide's `archetype` must be EXACTLY one of: "
        + ", ".join(f"'{a.name}'" for a in profile.archetypes) + ". Pick the archetype whose layout suits the content.",
        f"- Content slides carry roughly {profile.words_per_slide} words (heading + body). Headings are punchy; "
        "one idea per slide. Each slide should make the reader want the next.",
        "- Deliver real value: specifics, examples, numbers, mini-templates. No filler slides.",
        "- You may wrap 1-3 key words of a heading in **double asterisks** to colour them with the accent.",
        "- Layout guidance:\n" + rules,
        f"- Write in this tone: {profile.tone}.",
        ("- For slides where a photo helps, fill `image_prompt` with a vivid, specific photo description "
         "(subject, setting, lighting, framing; no text in the image)."
         if profile.uses_photos else "- Leave `image_prompt` null: this style does not use photos."),
        f"- Caption: follow the caption style ({profile.caption_style}); under {MAX_CAPTION - 400} characters; "
        "do not put hashtags inside the caption.",
        f"- Hashtags: 5-{MAX_HASHTAGS} relevant hashtags mixing niche and broader tags, each starting with #.",
    ]
    if previous is not None:
        prev = {
            "slides": [s.model_dump(include={"archetype", "kicker", "heading", "body", "bullets"}) for s in previous.slides],
            "caption": previous.caption,
            "hashtags": previous.hashtags,
        }
        parts += ["", "Here is the previous version of this carousel:",
                  json.dumps(prev, ensure_ascii=False, indent=2)]
    if feedback:
        parts += ["", "The user reviewed it and gave this feedback. Apply it fully; keep what they didn't "
                      f"criticise:\n\"\"\"{feedback}\"\"\""]
    return "\n".join(parts)


def _hook_arch(p: StyleProfile) -> SlideArchetype:
    a = p.archetypes
    return (next((x for x in a if x.name.lower() == "hook"), None)
            or next((x for x in a if re.search(r"hook|cover|title|intro", x.name.lower())), None)
            or next((x for x in a if x.layout == "center_statement"), None)
            or a[0])


def _cta_arch(p: StyleProfile) -> SlideArchetype:
    a = p.archetypes
    return (next((x for x in a if x.name.lower() == "cta"), None)
            or next((x for x in a if x.layout == "cta"), None)
            or next((x for x in a if re.search(r"cta|outro|follow|close|end", x.name.lower())), None)
            or a[-1])


def _resolve_arch(p: StyleProfile, name: str, sc: SlideCopy) -> SlideArchetype:
    by_name = {a.name: a for a in p.archetypes}
    if name in by_name:
        return by_name[name]
    low = {a.name.lower().strip(): a for a in p.archetypes}
    key = (name or "").lower().strip()
    if key in low:
        return low[key]
    for a in p.archetypes:  # the model named a layout instead of an archetype
        if a.layout == key:
            return a
    close = difflib.get_close_matches(key, list(low), n=1, cutoff=0.5)
    if close:
        return low[close[0]]
    if sc.bullets:
        lst = next((a for a in p.archetypes if a.layout == "list"), None)
        if lst:
            return lst
    hook, cta = _hook_arch(p), _cta_arch(p)
    return next((a for a in p.archetypes if a is not hook and a is not cta), p.archetypes[0])


def _clean_tags(tags: List[str]) -> List[str]:
    out, seen = [], set()
    for t in tags:
        for piece in re.split(r"[\s,]+", t or ""):
            piece = re.sub(r"[^\w]", "", piece.lstrip("#"), flags=re.UNICODE)
            if piece and piece.lower() not in seen:
                seen.add(piece.lower())
                out.append("#" + piece)
    return out[:MAX_HASHTAGS]


def _trim(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("\n\n", ". ", "! ", "? ", "\n", " "):
        i = cut.rfind(sep)
        if i > limit * 0.6:
            return cut[: i + (1 if sep.strip() else 0)].rstrip()
    return cut.rstrip()


def _to_slides(profile: StyleProfile, copy: CarouselCopy, brand: dict) -> List[Slide]:
    raw = [s for s in copy.slides if (s.heading or "").strip()]
    if not raw:
        raise ValueError("Claude returned a carousel with no slides")
    if len(raw) > MAX_SLIDES:  # keep the hook, the CTA and as many middle slides as fit
        raw = raw[: MAX_SLIDES - 1] + [raw[-1]]
    hook, cta = _hook_arch(profile), _cta_arch(profile)
    slides: List[Slide] = []
    for i, sc in enumerate(raw, 1):
        if i == 1:
            arch = hook
        elif i == len(raw) and len(raw) > 1:
            arch = cta
        else:
            arch = _resolve_arch(profile, sc.archetype, sc)
            if arch is cta and len(profile.archetypes) > 2:  # CTA archetype only at the end
                arch = _resolve_arch(profile, "", SlideCopy(heading="", archetype="", bullets=sc.bullets))
        slides.append(Slide(
            index=i, archetype=arch.name, layout=arch.layout,
            kicker=(sc.kicker or "").strip() or None,
            heading=sc.heading.strip(),
            body=(sc.body or "").strip() or None,
            bullets=[b.strip() for b in sc.bullets if b and b.strip()],
            image_prompt=((sc.image_prompt or "").strip() or None) if profile.uses_photos else None,
        ))
    last = slides[-1]
    cta_text = (brand.get("call_to_action") or "").strip()
    if len(slides) > 1 and cta_text and not last.body and cta_text.lower() not in last.heading.lower():
        last.body = cta_text
    return slides


def _compose(profile: StyleProfile, brand: dict, copy: CarouselCopy) -> tuple[List[Slide], str, List[str]]:
    slides = _to_slides(profile, copy, brand)
    hashtags = _clean_tags(copy.hashtags)
    caption = copy.caption or ""
    # hashtags the model left inside the caption → move them to the list
    inline = re.findall(r"(?<!\w)#\w+", caption)
    if inline and len(inline) >= 3:
        caption = re.sub(r"(?:\s*(?<!\w)#\w+)+\s*$", "", caption)
        hashtags = _clean_tags(hashtags + inline)
    reserve = len(" ".join(hashtags)) + 2 if hashtags else 0  # publisher appends hashtags to the caption
    caption = _trim(caption, MAX_CAPTION - reserve)
    return slides, caption, hashtags


def _ask_copy(profile: StyleProfile, brand: dict, idea: Idea, feedback: Optional[str],
              previous: Optional[CarouselDraft]) -> CarouselCopy:
    prompt = _write_prompt(profile, brand, idea, feedback, previous)
    return llm.ask_json(prompt, CarouselCopy, system=SYSTEM)


def write_carousel(style: str, idea: Idea, feedback: Optional[str] = None) -> CarouselDraft:
    """Write slides + caption + hashtags for an idea in the given style; saves and returns a draft."""
    profile = store.load_profile(style)
    brand = get_settings().brand
    copy = _ask_copy(profile, brand, idea, feedback, None)
    slides, caption, hashtags = _compose(profile, brand, copy)
    draft = CarouselDraft(id=store.new_id("c_"), style=style, idea=idea, slides=slides,
                          caption=caption, hashtags=hashtags, feedback=feedback)
    store.save_draft(draft)
    return draft


def revise_draft(draft_id: str, feedback: str, render: bool = True) -> CarouselDraft:
    """Rewrite a draft using the reviewer's feedback and the previous version as context.

    Keeps the draft id, resets status to draft, stores the feedback and (by default)
    re-renders the slides so the PNGs match the new copy.
    """
    old = store.load_draft(draft_id)
    profile = store.load_profile(old.style)
    brand = get_settings().brand
    copy = _ask_copy(profile, brand, old.idea, feedback, old)
    slides, caption, hashtags = _compose(profile, brand, copy)
    old_images = {s.index: s.image_path for s in old.slides if s.image_path}
    for s in slides:  # keep generated photos where the slide position still asks for one
        if s.image_prompt and s.index in old_images:
            s.image_path = old_images[s.index]
    draft = old.model_copy(update=dict(
        slides=slides, caption=caption, hashtags=hashtags, status=DraftStatus.draft,
        feedback=feedback, error=None, ig_media_id=None, ig_permalink=None, updated_at=utcnow(),
    ))
    store.save_draft(draft)
    if render:
        try:
            from ..render import render_draft
            draft = render_draft(draft)
        except Exception as e:
            log.exception("Re-render of %s failed", draft_id)
            draft.error = f"render failed: {e}"
            store.save_draft(draft)
    return draft


def create_drafts(style: str, n: int = 3, theme: Optional[str] = None) -> List[CarouselDraft]:
    """Ideas → copy → rendered PNGs. Skips (and logs) individual failures."""
    from ..render import render_draft

    ideas = generate_ideas(style, n=n, theme=theme)
    drafts: List[CarouselDraft] = []
    for idea in ideas[:n]:
        try:
            draft = write_carousel(style, idea)
        except Exception:
            log.exception("Writing carousel for idea %r failed; skipping", idea.title)
            continue
        try:
            draft = render_draft(draft)
        except Exception as e:
            log.exception("Rendering draft %s failed; skipping", draft.id)
            draft.error = f"render failed: {e}"
            draft.status = DraftStatus.failed
            store.save_draft(draft)
            continue
        drafts.append(draft)
    return drafts
