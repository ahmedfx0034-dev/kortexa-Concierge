"""Apply review decisions exported from the review web page into the repo's drafts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .. import store
from ..models import DraftStatus
from .calendar_store import load_calendar, save_calendar


def apply_reviews(path) -> List[dict]:
    """[{draft_id, decision: approve|reject|revise, caption?, hashtags?, feedback?}]"""
    items = json.loads(Path(path).read_text())
    if isinstance(items, dict):
        items = items.get("reviews", [items])
    cal = load_calendar()
    out: List[dict] = []
    for it in items:
        did, decision = it.get("draft_id"), (it.get("decision") or "").lower()
        try:
            draft = store.load_draft(did)
        except (FileNotFoundError, TypeError):
            out.append({"draft_id": did, "result": "error", "reason": "draft not found"})
            continue
        if decision not in ("approve", "reject", "revise"):
            out.append({"draft_id": did, "result": "error", "reason": f"bad decision {decision!r}"})
            continue
        if draft.status == DraftStatus.published:
            out.append({"draft_id": did, "result": "error", "reason": "already published"})
            continue
        if it.get("caption") is not None:
            draft.caption = it["caption"]
        if it.get("hashtags") is not None:
            draft.hashtags = list(it["hashtags"])
        if it.get("feedback") is not None:
            draft.feedback = it["feedback"]
        if decision == "approve":
            draft.status = DraftStatus.approved
        elif decision == "revise":
            draft.status = DraftStatus.draft
        else:
            draft.status = DraftStatus.rejected
            for slot in cal.slots:
                if slot.draft_id == did:
                    slot.draft_id, slot.reason = None, None
                    if slot.status == "filled":
                        slot.status = "open"
            draft.slot_id = draft.scheduled_at = None
        store.save_draft(draft)
        out.append({"draft_id": did, "result": decision})
    save_calendar(cal)
    return out
