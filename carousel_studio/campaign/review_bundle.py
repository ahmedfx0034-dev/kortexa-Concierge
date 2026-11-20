"""Build the files the review page (an Artifact) shows: small JPEG slide previews
and data.json listing the week's scheduled carousels.

    studio campaign review-bundle 2026-11-24 --out review_page

The page saves decisions to its own database; Claude reads them back with the
ArtifactData tool, writes them to a JSON file and runs `studio campaign apply-reviews`.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from PIL import Image

from .. import store

PREVIEW_W = 540  # half of 1080 keeps the bundle small (~40-70 KB per slide)


def _in_week(iso: Optional[str], start: date) -> bool:
    if not iso:
        return False
    d = datetime.fromisoformat(iso).date()
    return start <= d < start + timedelta(days=7)


def build_review_bundle(week_start: str, out_dir: str | Path, render_missing: bool = True) -> dict:
    start = date.fromisoformat(week_start)
    out = Path(out_dir)
    (out / "slides").mkdir(parents=True, exist_ok=True)
    pillars = _pillars()
    items = []
    for d in store.list_drafts():
        if not _in_week(getattr(d, "scheduled_at", None), start):
            continue
        if d.status.value in ("published", "rejected"):
            continue
        if render_missing and any(not s.rendered_path or not Path(s.rendered_path).exists() for s in d.slides):
            from ..render import render_draft

            d = render_draft(d)
        rels = []
        for s in sorted(d.slides, key=lambda s: s.index):
            rel = f"slides/{d.id}/{s.index:02d}.jpg"
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(s.rendered_path) as im:
                im = im.convert("RGB")
                im.thumbnail((PREVIEW_W, PREVIEW_W * 5 // 4))
                im.save(dest, "JPEG", quality=82, optimize=True)
            rels.append(rel)
        items.append({
            "id": d.id, "title": d.idea.title, "style": d.style, "pillar": pillars.get(d.idea.title),
            "scheduled_at": d.scheduled_at, "status": d.status.value,
            "caption": d.caption, "hashtags": d.hashtags, "slides": rels,
        })
    items.sort(key=lambda i: i["scheduled_at"])
    data = {"week": start.strftime("%-d %B %Y"), "items": items}
    (out / "data.json").write_text(json.dumps(data, indent=1))
    return data


def _pillars() -> dict:
    """Map idea titles to content pillars using the briefs the writers produced."""
    out = {}
    briefs = store.DRAFTS_DIR.parent / "briefs"
    for p in briefs.glob("week*-*.json"):
        try:
            for item in json.loads(p.read_text()):
                out[item["idea"]["title"]] = item.get("pillar")
        except (ValueError, KeyError, TypeError):
            continue
    return out


def bundle_files(out_dir: str | Path) -> dict:
    """Map of published path -> local path, for the Artifact tool's `files`."""
    out = Path(out_dir)
    files = {"data.json": str(out / "data.json")}
    for p in sorted((out / "slides").rglob("*.jpg")):
        files[str(p.relative_to(out))] = str(p)
    return files
