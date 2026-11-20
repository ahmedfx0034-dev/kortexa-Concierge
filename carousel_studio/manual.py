"""Session mode: no Claude API key needed.

Claude (in a Claude Code session, on the owner's subscription) does the thinking
and writes JSON files; these functions validate them and hand them to the
renderer. The API-based functions in generate/ and style/ stay available for
anyone who sets ANTHROPIC_API_KEY.

  studio import-style  data/styles/<name>/profile.json   (or any path)
  studio import-carousel <style> carousel.json [--render]

carousel.json shape (same as generate.writer.CarouselCopy plus an idea):
{
  "idea": {"title": "...", "angle": "...", "hook": "..."},
  "slides": [{"archetype": "hook", "kicker": null, "heading": "...", "body": "...", "bullets": []}, ...],
  "caption": "...",
  "hashtags": ["#realestate", ...]
}
A file may also hold a list of such objects.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from pydantic import BaseModel

from . import store
from .config import get_settings
from .models import CarouselDraft, Idea, StyleProfile


class CarouselFile(BaseModel):
    idea: Idea
    slides: list
    caption: str
    hashtags: list = []


def import_style(path: str | Path, name: str | None = None) -> StyleProfile:
    data = json.loads(Path(path).read_text())
    if name:
        data["name"] = name
    profile = StyleProfile.model_validate(data)
    profile.name = store.slugify(profile.name)
    store.save_profile(profile)
    return profile


def import_carousels(style: str, path: str | Path, render: bool = True,
                     draft_id: str | None = None) -> List[CarouselDraft]:
    from .generate.writer import CarouselCopy, _compose

    raw = json.loads(Path(path).read_text())
    items = raw if isinstance(raw, list) else [raw]
    profile = store.load_profile(style)
    brand = get_settings().brand
    out: List[CarouselDraft] = []
    for item in items:
        cf = CarouselFile.model_validate(item)
        copy = CarouselCopy.model_validate({"slides": cf.slides, "caption": cf.caption, "hashtags": cf.hashtags})
        slides, caption, hashtags = _compose(profile, brand, copy)
        did = item.get("id") or (draft_id if len(items) == 1 else None) or store.new_id("c_")
        draft = CarouselDraft(id=did, style=profile.name, idea=cf.idea, slides=slides,
                              caption=caption, hashtags=hashtags)
        for k in ("scheduled_at", "slot_id", "experiment_arm"):  # optional campaign fields
            if k in item and k in CarouselDraft.model_fields:
                setattr(draft, k, item[k])
        store.save_draft(draft)
        if render:
            from .render import render_draft

            draft = render_draft(draft)
        out.append(draft)
    return out
