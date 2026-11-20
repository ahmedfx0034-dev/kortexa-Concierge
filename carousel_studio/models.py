"""Shared data models. Every module reads and writes these — keep them stable."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- style input

class ReferenceSource(str, Enum):
    local = "local"          # images the user dropped in a folder
    post_url = "post_url"    # a single instagram.com/p/... link
    account = "account"      # an @handle we pulled recent carousels from


class ReferenceCarousel(BaseModel):
    """One carousel the user likes, downloaded to data/styles/<style>/refs/<id>/."""
    id: str
    source: ReferenceSource
    origin: str = Field(description="Folder path, post URL, or @handle it came from")
    slide_paths: List[str] = Field(description="Local image paths, in slide order")
    caption: Optional[str] = None
    likes: Optional[int] = None
    comments: Optional[int] = None


# ------------------------------------------------------------- style profile

class Palette(BaseModel):
    background: str = Field(description="Hex colour, e.g. #0F0F0F")
    surface: str = Field(description="Hex colour for cards/panels")
    text: str = Field(description="Main text hex colour")
    muted_text: str = Field(description="Secondary text hex colour")
    accent: str = Field(description="Primary accent hex colour")
    accent_2: str = Field(description="Secondary accent hex colour")


class Typography(BaseModel):
    heading_font: str = Field(description="A Google Fonts family name closest to the headings")
    body_font: str = Field(description="A Google Fonts family name closest to the body text")
    heading_weight: int = Field(description="CSS font-weight for headings, 400-900")
    heading_case: str = Field(description="'upper', 'title' or 'sentence'")
    heading_size: str = Field(description="'xl', 'l' or 'm' — how dominant headings are")


class SlideArchetype(BaseModel):
    """A recurring slide layout seen in the references."""
    name: str = Field(description="Short id, e.g. 'hook', 'numbered_point', 'quote', 'cta'")
    description: str = Field(description="What the slide looks like and how text is placed")
    layout: str = Field(
        description="One of: 'center_statement', 'top_heading_body', 'numbered', "
                    "'split_image', 'list', 'quote', 'cta'"
    )


class StyleProfile(BaseModel):
    """The distilled 'look and voice' of a set of reference carousels."""
    name: str
    summary: str = Field(description="2-3 sentences describing the overall style")
    palette: Palette
    typography: Typography
    archetypes: List[SlideArchetype]
    decorations: List[str] = Field(
        description="Visual motifs to reproduce, e.g. 'slide counter top-right', "
                    "'handle bottom-left', 'thin accent underline', 'grain texture'"
    )
    uses_photos: bool = Field(description="Whether slides rely on photographic imagery")
    words_per_slide: int = Field(description="Typical word count on a content slide")
    slide_count: int = Field(description="Typical number of slides, 3-20")
    hook_patterns: List[str] = Field(description="How the first slide hooks the reader")
    tone: str = Field(description="Voice of the copy, e.g. 'blunt, punchy, second person'")
    caption_style: str = Field(description="How captions are written: length, emojis, hashtags")
    reference_ids: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow)


# ----------------------------------------------------------------- drafts

class Slide(BaseModel):
    index: int = Field(description="1-based position in the carousel")
    archetype: str = Field(description="Name of a StyleProfile archetype")
    layout: str = Field(description="Layout id copied from that archetype")
    kicker: Optional[str] = Field(default=None, description="Small label above the heading")
    heading: str
    body: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)
    image_prompt: Optional[str] = Field(
        default=None, description="Only if the style uses photos: what image to generate"
    )
    image_path: Optional[str] = Field(default=None, description="Rendered/generated asset")
    rendered_path: Optional[str] = Field(default=None, description="Final 1080x1350 PNG")


class DraftStatus(str, Enum):
    draft = "draft"          # generated, waiting for review
    approved = "approved"    # user approved, ready to publish
    rejected = "rejected"
    published = "published"
    failed = "failed"


class Idea(BaseModel):
    title: str
    angle: str = Field(description="Why this is interesting to the audience")
    hook: str = Field(description="The first-slide line")


class CarouselDraft(BaseModel):
    id: str
    style: str = Field(description="StyleProfile name used")
    idea: Idea
    slides: List[Slide]
    caption: str
    hashtags: List[str] = Field(default_factory=list)
    status: DraftStatus = DraftStatus.draft
    feedback: Optional[str] = Field(default=None, description="User notes from review")
    ig_media_id: Optional[str] = None
    ig_permalink: Optional[str] = None
    error: Optional[str] = None
    # campaign scheduling (all optional; older draft.json files still load)
    scheduled_at: Optional[str] = Field(default=None, description="ISO 8601 with offset")
    slot_id: Optional[str] = None
    experiment_arm: Optional[str] = Field(default=None, description="'explore', 'champion', 'challenger'")
    image_urls: List[str] = Field(default_factory=list, description="Public URLs once uploaded")
    published_at: Optional[str] = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
