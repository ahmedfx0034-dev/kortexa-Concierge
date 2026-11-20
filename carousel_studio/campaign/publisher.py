"""Post due, approved slots to Instagram (run from scheduled cloud sessions)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .. import store
from ..models import DraftStatus, utcnow
from ..publish.hosting import resolve_slide_path, upload_images
from ..publish.instagram import publish_draft
from .calendar_store import load_calendar, save_calendar, slot_datetime

STALE_AFTER = timedelta(hours=6)
IG_DAILY_LIMIT = 25


def _render(draft):
    from ..render import render_draft  # lazy: pulls in playwright

    return render_draft(draft)


def _slides_present(draft) -> bool:
    for sl in draft.slides:
        if not sl.rendered_path:
            return False
        try:
            resolve_slide_path(draft, sl.rendered_path)
        except FileNotFoundError:
            return False
    return True


def posts_in_last_24h(now: datetime) -> int:
    n = 0
    for d in store.list_drafts():
        if d.published_at:
            try:
                t = datetime.fromisoformat(d.published_at)
            except ValueError:
                continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if timedelta(0) <= now - t < timedelta(hours=24):
                n += 1
    return n


def _log(entry: dict, draft) -> None:
    try:
        from .post_log import log_event

        log_event({**{k: v for k, v in entry.items() if k != "media_id"},
                   "draft_id": draft.id, "title": draft.idea.title, "style": draft.style})
    except Exception:  # the log must never block posting
        pass


def publish_due(now: Optional[datetime] = None, dry_run: bool = False, max_posts: int = 3) -> List[dict]:
    """Publish approved drafts whose slot time has passed (within 6h). Returns a summary list."""
    now = now or datetime.now(timezone.utc)
    cal = load_calendar()
    summary: List[dict] = []
    posted_now = 0
    used_24h = posts_in_last_24h(now)
    for slot in sorted(cal.slots, key=lambda s: (s.date, s.time)):
        if slot.status != "filled" or not slot.draft_id:
            continue
        when = slot_datetime(slot)
        if when > now:
            continue
        late = now - when
        try:
            draft = store.load_draft(slot.draft_id)
        except FileNotFoundError:
            draft = None
        approved = bool(draft and draft.status == DraftStatus.approved)
        entry = {"slot_id": slot.id, "draft_id": slot.draft_id}
        if late > STALE_AFTER:
            reason = "stale" if approved else "not approved"
            if not dry_run:
                slot.status, slot.reason = "skipped", reason
            summary.append({**entry, "action": "skipped", "reason": reason})
            continue
        if not approved:
            summary.append({**entry, "action": "waiting", "reason": "not approved yet"})
            continue
        if posted_now >= max_posts:
            summary.append({**entry, "action": "deferred", "reason": "max_posts reached"})
            continue
        if used_24h + posted_now >= IG_DAILY_LIMIT:
            summary.append({**entry, "action": "deferred", "reason": "Instagram 25 posts/24h limit"})
            continue
        if dry_run:
            summary.append({**entry, "action": "would_post"})
            posted_now += 1
            continue
        try:
            if not _slides_present(draft):
                draft = _render(draft)
            draft.image_urls = upload_images(draft)
            store.save_draft(draft)
            result = publish_draft(draft.id, image_urls=draft.image_urls)
        except Exception as e:  # render/upload failure: draft is untouched, retry next run
            slot.reason = f"error: {e}"
            summary.append({**entry, "action": "error", "reason": str(e)})
            continue
        if result.status == DraftStatus.published:
            result.published_at = utcnow()
            store.save_draft(result)
            slot.status, slot.reason = "posted", None
            posted_now += 1
            summary.append({**entry, "action": "posted", "permalink": result.ig_permalink,
                            "media_id": result.ig_media_id})
            _log({**entry, "action": "posted", "permalink": result.ig_permalink}, draft)
        else:
            slot.status, slot.reason = "skipped", f"publish failed: {result.error}"
            summary.append({**entry, "action": "failed", "reason": result.error})
            _log({**entry, "action": "failed", "reason": result.error}, draft)
        save_calendar(cal)  # persist after each post so a crash can't double-post
    if not dry_run:
        save_calendar(cal)
    return summary
