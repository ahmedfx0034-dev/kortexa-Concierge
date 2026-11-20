"""JSON state files under data/analytics/ (committed to git; DATA_DIR read at call time)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import config

DEFAULT_GOALS = {
    "weights": {
        "follows": 10.0,
        "profile_visits": 4.0,
        "shares": 3.0,
        "saved": 3.0,
        "comments": 2.0,
        "likes": 0.5,
    },
    "per_reach": 1000,
    "snapshot_target_hours": 48,
}


def analytics_dir() -> Path:
    d = Path(config.DATA_DIR) / "analytics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(name: str, default: Any) -> Any:
    p = analytics_dir() / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except ValueError:
        return default


def write_json(name: str, data: Any) -> Path:
    p = analytics_dir() / name
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return p


def load_goals() -> dict:
    p = analytics_dir() / "goals.json"
    if not p.exists():
        write_json("goals.json", DEFAULT_GOALS)
        return json.loads(json.dumps(DEFAULT_GOALS))
    goals = read_json("goals.json", {})
    out = json.loads(json.dumps(DEFAULT_GOALS))
    out["weights"].update(goals.get("weights", {}))
    for k in ("per_reach", "snapshot_target_hours"):
        if k in goals:
            out[k] = goals[k]
    return out
