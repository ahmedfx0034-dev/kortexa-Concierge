"""Posting calendar persisted as one small JSON file (data/campaign/calendar.json)."""
from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from .. import config

DEFAULT_TZ = "Africa/Accra"


class Slot(BaseModel):
    id: str                                   # "2026-11-24-1"
    date: str                                 # YYYY-MM-DD (local date)
    time: str                                 # HH:MM local
    tz: str = DEFAULT_TZ
    style: Optional[str] = None
    arm: Optional[str] = None                 # explore | champion | challenger
    draft_id: Optional[str] = None
    status: str = "open"                      # open | filled | posted | skipped
    reason: Optional[str] = None              # why skipped / last note


class Calendar(BaseModel):
    slots: List[Slot] = Field(default_factory=list)

    def get(self, slot_id: str) -> Slot:
        for s in self.slots:
            if s.id == slot_id:
                return s
        raise KeyError(f"No such slot: {slot_id}")

    def sort(self) -> None:
        self.slots.sort(key=lambda s: (s.date, s.time, s.id))


def calendar_path() -> Path:
    return config.DATA_DIR / "campaign" / "calendar.json"


def load_calendar() -> Calendar:
    p = calendar_path()
    if not p.exists():
        return Calendar()
    return Calendar.model_validate_json(p.read_text())


def save_calendar(cal: Calendar) -> Path:
    cal.sort()
    p = calendar_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(cal.model_dump_json(indent=2) + "\n")
    return p


def get_tz(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except Exception:
        if name == DEFAULT_TZ:  # Accra is UTC+0 year-round
            return timezone.utc
        raise


def slot_datetime(slot: Slot) -> datetime:
    """Timezone-aware datetime of the slot."""
    h, m = (int(x) for x in slot.time.split(":"))
    d = date.fromisoformat(slot.date)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=get_tz(slot.tz))


def as_date(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else (
        v.date() if isinstance(v, datetime) else date.fromisoformat(str(v)))
