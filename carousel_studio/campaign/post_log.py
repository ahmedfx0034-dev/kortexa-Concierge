"""A simple, human-readable log of every posting attempt.

data/campaign/post_log.json  — one entry per attempt (posted / failed / skipped)
data/campaign/POST_LOG.md    — the same as a table, newest first
"""
from __future__ import annotations

import json
from typing import List

from .. import config
from ..models import utcnow


def _paths():
    d = config.DATA_DIR / "campaign"
    d.mkdir(parents=True, exist_ok=True)
    return d / "post_log.json", d / "POST_LOG.md"


def read_log() -> List[dict]:
    p, _ = _paths()
    return json.loads(p.read_text()) if p.exists() else []


def log_event(entry: dict) -> None:
    """entry: slot_id, draft_id, title, style, action, scheduled, permalink?, reason?"""
    p, md = _paths()
    rows = read_log()
    rows.append({"logged_at": utcnow(), **entry})
    p.write_text(json.dumps(rows, indent=1))
    md.write_text(render_markdown(rows))


def render_markdown(rows: List[dict]) -> str:
    out = ["# Kortexa post log", "",
           "| Logged (UTC) | Slot | Result | Format | Title | Link / reason |",
           "|---|---|---|---|---|---|"]
    for r in reversed(rows):
        link = r.get("permalink") or r.get("reason") or ""
        title = str(r.get("title", "")).replace("|", "/")
        out.append(f"| {r['logged_at']} | {r.get('slot_id','')} | {r.get('action','')} | "
                   f"{r.get('style','')} | {title} | {link} |")
    return "\n".join(out) + "\n"
