"""Plan the month, assign experiment arms, and match drafts to slots."""
from __future__ import annotations

from math import gcd
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from .. import store
from ..models import DraftStatus
from .calendar_store import (DEFAULT_TZ, Calendar, Slot, as_date, load_calendar,
                             save_calendar, slot_datetime)

DEFAULT_TIMES = ["08:30", "13:00", "19:30"]


def _slugs(styles: Sequence[str]) -> List[str]:
    return [store.slugify(s) for s in styles]


def _rot(day: int, ti: int, t: int, n: int) -> int:
    """Latin-square-style rotation: sequential index (balances styles overall) plus a shift
    every n/gcd(n,t) days so a style does not lock onto one time of day."""
    return (day * t + ti + day // (n // gcd(n, t))) % n


def plan_month(start_date, days: int = 30, posts_per_day: int = 3,
               times: Optional[Sequence[str]] = None, styles: Optional[Sequence[str]] = None,
               tz: str = DEFAULT_TZ, per_day: Optional[Sequence[int]] = None,
               phase_rules: Optional[dict] = None) -> Calendar:
    """Create slots for `days` days from start_date and save the calendar.

    Only the explore phase (default: first 7 days) gets styles, using a Latin-square
    rotation (see _rot), so every style gets every time of day about equally. Later days stay style=None until assign_week().
    `per_day` (e.g. [2,3,3]) cycles over days and overrides posts_per_day.
    Existing slots with the same id are kept untouched (safe to re-run).
    """
    rules = {"explore_days": 7, **(phase_rules or {})}
    times = list(times or DEFAULT_TIMES)
    styles = _slugs(styles or [])
    start = as_date(start_date)
    cal = load_calendar()
    have = {s.id for s in cal.slots}
    for d in range(days):
        day = start + timedelta(days=d)
        count = per_day[d % len(per_day)] if per_day else posts_per_day
        day_times = times[:count]
        if len(day_times) < count:
            raise ValueError(f"Need {count} times per day but only {len(times)} given")
        for ti, t in enumerate(day_times):
            sid = f"{day.isoformat()}-{ti + 1}"
            if sid in have:
                continue
            explore = d < rules["explore_days"] and styles
            cal.slots.append(Slot(
                id=sid, date=day.isoformat(), time=t, tz=tz,
                style=styles[_rot(d, ti, len(day_times), len(styles))] if explore else None,
                arm="explore" if explore else None))
    save_calendar(cal)
    return cal


def assign_week(week_start, champion: str, challengers: Sequence[str],
                champion_share: float = 0.6) -> List[Slot]:
    """Assign styles to the open, unfilled slots of the 7 days from week_start.

    Champion gets ~champion_share of slots, challengers split the rest evenly,
    balanced over each time of day. Returns the slots changed.
    """
    champion = store.slugify(champion)
    challengers = _slugs(challengers)
    if not challengers:
        champion_share = 1.0
    start = as_date(week_start)
    end = start + timedelta(days=6)
    cal = load_calendar()
    cols: Dict[str, List[Slot]] = {}
    for s in cal.slots:
        if s.status == "open" and not s.draft_id and start <= date.fromisoformat(s.date) <= end:
            cols.setdefault(s.time, []).append(s)
    total = sum(len(v) for v in cols.values())
    done = champ_done = 0
    chal_i = 0
    changed: List[Slot] = []
    for t in sorted(cols):
        slots = sorted(cols[t], key=lambda s: s.date)
        m = len(slots)
        done += m
        n_champ = max(0, min(m, round(champion_share * done) - champ_done))
        champ_done += n_champ
        # spread champion evenly through the column
        champ_pos = {int((i + 0.5) * m / n_champ) for i in range(n_champ)} if n_champ else set()
        for i, s in enumerate(slots):
            if i in champ_pos:
                s.style, s.arm = champion, "champion"
            else:
                s.style, s.arm = challengers[chal_i % len(challengers)], "challenger"
                chal_i += 1
            changed.append(s)
    save_calendar(cal)
    return changed


def open_slots(date_from=None, date_to=None, style: Optional[str] = None) -> List[Slot]:
    cal = load_calendar()
    lo = as_date(date_from) if date_from else None
    hi = as_date(date_to) if date_to else None
    want = store.slugify(style) if style else None
    out = []
    for s in cal.slots:
        if s.status != "open" or s.draft_id:
            continue
        d = date.fromisoformat(s.date)
        if (lo and d < lo) or (hi and d > hi):
            continue
        if want and s.style != want:
            continue
        out.append(s)
    return sorted(out, key=lambda s: (s.date, s.time))


def fill_slot(slot_id: str, draft_id: str) -> Slot:
    """Put a draft in a slot and stamp scheduling info on the draft."""
    cal = load_calendar()
    slot = cal.get(slot_id)
    if slot.status not in ("open", "filled"):
        raise ValueError(f"Slot {slot_id} is {slot.status}")
    draft = store.load_draft(draft_id)
    slot.draft_id, slot.status, slot.reason = draft_id, "filled", None
    draft.slot_id = slot.id
    draft.scheduled_at = slot_datetime(slot).isoformat()
    draft.experiment_arm = slot.arm
    store.save_draft(draft)
    save_calendar(cal)
    return slot


def attach_drafts_to_slots(now: Optional[datetime] = None) -> List[dict]:
    """Match unscheduled drafts to open slots of the same style, earliest slot first."""
    now = now or datetime.now(timezone.utc)
    drafts = [d for d in store.list_drafts()
              if not d.slot_id and d.status in (DraftStatus.draft, DraftStatus.approved)]
    drafts.sort(key=lambda d: d.created_at)
    cal = load_calendar()
    taken = {s.draft_id for s in cal.slots if s.draft_id}
    result = []
    for draft in drafts:
        if draft.id in taken:
            continue
        style = store.slugify(draft.style)
        slot = next((s for s in sorted(cal.slots, key=lambda s: (s.date, s.time))
                     if s.status == "open" and not s.draft_id and s.style == style
                     and slot_datetime(s) >= now), None)
        if not slot:
            continue
        slot.draft_id, slot.status = draft.id, "filled"
        draft.slot_id, draft.scheduled_at = slot.id, slot_datetime(slot).isoformat()
        draft.experiment_arm = slot.arm
        store.save_draft(draft)
        result.append({"draft_id": draft.id, "slot_id": slot.id, "scheduled_at": draft.scheduled_at,
                       "arm": slot.arm})
    save_calendar(cal)
    return result
