"""Settings come from environment variables (or a .env file) plus brand.yaml-free
plain JSON in data/brand.json so the user can edit their niche without code."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("STUDIO_DATA_DIR", ROOT / "data"))
STYLES_DIR = DATA_DIR / "styles"     # styles/<name>/refs/<ref_id>/*.jpg + profile.json
DRAFTS_DIR = DATA_DIR / "drafts"     # drafts/<draft_id>/draft.json + slide_01.png ...
BRAND_FILE = DATA_DIR / "brand.json"

DEFAULT_BRAND = {
    "brand_name": "Kortexa",
    "instagram_handle": "@kortexa",
    "niche": "CHANGE ME — e.g. 'AI tools for real estate agents'",
    "audience": "CHANGE ME — who the carousels are for",
    "goals": "Grow followers and drive profile visits",
    "call_to_action": "Follow for more",
    "topics_to_avoid": [],
    "language": "English",
}


@dataclass
class Settings:
    model: str = field(default_factory=lambda: os.getenv("STUDIO_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: os.getenv("STUDIO_EFFORT", "high"))
    apify_token: str | None = field(default_factory=lambda: os.getenv("APIFY_TOKEN"))
    ig_user_id: str | None = field(default_factory=lambda: os.getenv("IG_USER_ID"))
    ig_access_token: str | None = field(default_factory=lambda: os.getenv("IG_ACCESS_TOKEN"))
    graph_api_version: str = field(default_factory=lambda: os.getenv("IG_GRAPH_VERSION", "v23.0"))
    # Public hosting for slide images (Instagram fetches them by URL).
    image_host: str = field(default_factory=lambda: os.getenv("IMAGE_HOST", "s3"))  # "s3" (S3/R2/etc) or "local" (PUBLIC_BASE_URL)
    s3_bucket: str | None = field(default_factory=lambda: os.getenv("S3_BUCKET"))
    s3_endpoint_url: str | None = field(default_factory=lambda: os.getenv("S3_ENDPOINT_URL"))
    s3_public_base_url: str | None = field(default_factory=lambda: os.getenv("S3_PUBLIC_BASE_URL"))
    public_base_url: str | None = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL"))
    brand: dict = field(default_factory=dict)


def load_brand() -> dict:
    if not BRAND_FILE.exists():
        BRAND_FILE.parent.mkdir(parents=True, exist_ok=True)
        BRAND_FILE.write_text(json.dumps(DEFAULT_BRAND, indent=2))
    return {**DEFAULT_BRAND, **json.loads(BRAND_FILE.read_text())}


def get_settings() -> Settings:
    for d in (STYLES_DIR, DRAFTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    s = Settings()
    s.brand = load_brand()
    return s
