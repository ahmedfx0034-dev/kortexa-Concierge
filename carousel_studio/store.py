"""File-based storage for references, style profiles and drafts (no database needed)."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import List

from .config import DRAFTS_DIR, STYLES_DIR
from .models import CarouselDraft, ReferenceCarousel, StyleProfile, utcnow


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "style"


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


# ----- styles

def style_dir(style: str) -> Path:
    d = STYLES_DIR / slugify(style)
    d.mkdir(parents=True, exist_ok=True)
    return d


def ref_dir(style: str, ref_id: str) -> Path:
    d = style_dir(style) / "refs" / ref_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_reference(style: str, ref: ReferenceCarousel) -> None:
    (ref_dir(style, ref.id) / "ref.json").write_text(ref.model_dump_json(indent=2))


def list_references(style: str) -> List[ReferenceCarousel]:
    refs_root = style_dir(style) / "refs"
    if not refs_root.exists():
        return []
    return [
        ReferenceCarousel.model_validate_json(p.read_text())
        for p in sorted(refs_root.glob("*/ref.json"))
    ]


def save_profile(profile: StyleProfile) -> Path:
    p = style_dir(profile.name) / "profile.json"
    p.write_text(profile.model_dump_json(indent=2))
    return p


def load_profile(style: str) -> StyleProfile:
    p = style_dir(style) / "profile.json"
    if not p.exists():
        raise FileNotFoundError(f"No style profile for '{style}'. Run: studio analyze {style}")
    return StyleProfile.model_validate_json(p.read_text())


def list_styles() -> List[str]:
    return sorted(p.parent.name for p in STYLES_DIR.glob("*/profile.json"))


# ----- drafts

def draft_dir(draft_id: str) -> Path:
    d = DRAFTS_DIR / draft_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_draft(draft: CarouselDraft) -> None:
    draft.updated_at = utcnow()
    (draft_dir(draft.id) / "draft.json").write_text(draft.model_dump_json(indent=2))


def load_draft(draft_id: str) -> CarouselDraft:
    return CarouselDraft.model_validate_json((DRAFTS_DIR / draft_id / "draft.json").read_text())


def list_drafts() -> List[CarouselDraft]:
    drafts = [CarouselDraft.model_validate_json(p.read_text()) for p in DRAFTS_DIR.glob("*/draft.json")]
    return sorted(drafts, key=lambda d: d.created_at, reverse=True)


def recent_titles(limit: int = 40) -> List[str]:
    """So idea generation doesn't repeat itself."""
    return [d.idea.title for d in list_drafts()[:limit]]
