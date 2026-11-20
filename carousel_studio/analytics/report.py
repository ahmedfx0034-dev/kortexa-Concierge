"""Compare styles, decide champion/challengers, and render a report."""
from __future__ import annotations

import random
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .. import store
from . import paths
from .insights import parse_time

EARLY_HOURS = 44.0      # a snapshot younger than this is flagged "early"
SWITCH_MARGIN = 1.10    # challenger mean must beat champion by 10%
BOOTSTRAP_N = 2000


# ------------------------------------------------------------------ scoring

def score_metrics(metrics: dict, goals: Optional[dict] = None) -> float:
    goals = goals or paths.load_goals()
    w = goals["weights"]
    total = sum(float(metrics.get(k) or 0) * float(v) for k, v in w.items())
    return total / max(float(metrics.get("reach") or 0), 1.0) * goals.get("per_reach", 1000)


def pick_snapshot(snapshots: List[dict], target_hours: float = 48.0) -> Tuple[Optional[dict], bool]:
    """Snapshot nearest to target age. Flag early if it is younger than EARLY_HOURS."""
    snaps = [s for s in snapshots if s.get("hours_since_post") is not None]
    if not snaps:
        return (snapshots[-1], True) if snapshots else (None, True)
    best = min(snaps, key=lambda s: abs(s["hours_since_post"] - target_hours))
    return best, best["hours_since_post"] < EARLY_HOURS


def post_records(goals: Optional[dict] = None) -> List[dict]:
    goals = goals or paths.load_goals()
    out = []
    for did, rec in sorted(paths.read_json("metrics.json", {}).items()):
        snap, early = pick_snapshot(rec.get("snapshots", []), goals["snapshot_target_hours"])
        if not snap:
            continue
        m = snap.get("metrics", {})
        out.append({
            "draft_id": did, "style": rec.get("style") or "unknown",
            "posted_at": rec.get("posted_at"), "hours": snap.get("hours_since_post"),
            "early": early, "reach": m.get("reach") or 0, "metrics": m,
            "score": score_metrics(m, goals),
        })
    return out


# ------------------------------------------------------------------ per style

def bootstrap_interval(values: List[float], level: float = 0.90, n: int = BOOTSTRAP_N,
                       seed: int = 1234) -> Tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    k = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(k)) / k for _ in range(n))
    lo = means[int(((1 - level) / 2) * n)]
    hi = means[min(n - 1, int((1 - (1 - level) / 2) * n))]
    return (lo, hi)


def style_stats(records: List[dict]) -> Dict[str, dict]:
    by: Dict[str, List[dict]] = {}
    for r in records:
        by.setdefault(r["style"], []).append(r)
    out = {}
    for style, rs in by.items():
        scores = [r["score"] for r in rs]
        lo, hi = bootstrap_interval(scores)
        totals: Dict[str, float] = {}
        for r in rs:
            for k, v in r["metrics"].items():
                if isinstance(v, (int, float)):
                    totals[k] = totals.get(k, 0) + v
        out[style] = {
            "style": style, "n": len(rs), "mean": statistics.fmean(scores),
            "median": statistics.median(scores), "ci_low": lo, "ci_high": hi,
            "mean_reach": statistics.fmean(r["reach"] for r in rs),
            "totals": totals, "early_posts": sum(1 for r in rs if r["early"]),
        }
    return out


# ------------------------------------------------------------------ decision

@dataclass
class Recommendation:
    champion: Optional[str]
    previous_champion: Optional[str] = None
    changed: bool = False
    challengers: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


def load_champion() -> dict:
    return paths.read_json("champion.json", {})


def _recent_scores(records, style, now, days=14):
    cutoff = now - timedelta(days=days)
    out = []
    for r in records:
        t = parse_time(r["posted_at"])
        if r["style"] == style and t and t >= cutoff:
            out.append(r["score"])
    return out


def recommend(min_posts: int = 5, now: Optional[datetime] = None) -> Recommendation:
    now = now or datetime.now(timezone.utc)
    records = post_records()
    stats = style_stats(records)
    known = set(stats) | set(store.list_styles())
    champ = load_champion().get("champion")
    reasons: List[str] = []

    if not champ:
        short = sorted(s for s in known if stats.get(s, {}).get("n", 0) < min_posts)
        if short or not stats:
            if not stats:
                reasons.append("No posts have been measured yet, so there is no champion.")
            else:
                reasons.append(
                    f"Still testing: every style needs at least {min_posts} measured posts before we pick a "
                    "champion. Still short: " + ", ".join(
                        f"{s} ({stats.get(s, {}).get('n', 0)}/{min_posts})" for s in short) + ".")
            return Recommendation(champion=None, reasons=reasons)
        ranked = sorted(stats.values(), key=lambda x: -x["mean"])
        champ = ranked[0]["style"]
        chall = [x["style"] for x in ranked[1:3]]
        reasons.append(
            f"'{champ}' is the first champion: it earned {ranked[0]['mean']:.1f} points per 1,000 people "
            f"reached across {ranked[0]['n']} posts, the best of {len(ranked)} styles.")
        if chall:
            reasons.append("Runners-up that keep being tested as challengers: " + ", ".join(chall) + ".")
        return Recommendation(champion=champ, changed=True, challengers=chall,
                              dropped=_dropped(stats, champ, ranked[0]["mean"], min_posts, reasons),
                              reasons=reasons)

    cs = stats.get(champ)
    if not cs:
        reasons.append(f"Champion '{champ}' has no measured posts yet; keeping it.")
        ranked = sorted((x for s, x in stats.items()), key=lambda x: -x["mean"])
        return Recommendation(champion=champ, previous_champion=champ,
                              challengers=[x["style"] for x in ranked[:2]], reasons=reasons)
    cmean = cs["mean"]
    winners = []
    for s, st in stats.items():
        if s == champ:
            continue
        if st["n"] < min_posts:
            reasons.append(f"'{s}' has only {st['n']} of {min_posts} posts needed, so it cannot take over yet.")
            continue
        if st["mean"] < cmean * SWITCH_MARGIN:
            reasons.append(
                f"'{s}' scores {st['mean']:.1f} vs the champion's {cmean:.1f}; it is not at least 10% better.")
            continue
        recent = _recent_scores(records, s, now)
        consistent = len(recent) >= 2 and all(x > cmean for x in recent)
        if st["ci_low"] > cmean:
            winners.append((st["mean"], s, "its low-end estimate is still above the champion's average"))
        elif consistent:
            winners.append((st["mean"], s, "every one of its posts in the last two weeks beat the champion's average"))
        else:
            reasons.append(
                f"'{s}' is more than 10% ahead ({st['mean']:.1f} vs {cmean:.1f}) but the lead is not "
                "convincing yet (could be luck); keep testing.")
    new_champ, prev, changed = champ, champ, False
    if winners:
        winners.sort(reverse=True)
        m, new_champ, why = winners[0]
        changed = True
        reasons.insert(0, f"Switching champion from '{champ}' to '{new_champ}': it scores {m:.1f} vs "
                          f"{cmean:.1f} (more than 10% better) and {why}.")
        nm = stats[new_champ]["mean"]
    else:
        reasons.insert(0, f"Keeping '{champ}' as champion ({cmean:.1f} points per 1,000 reached over "
                          f"{cs['n']} posts); no challenger has clearly beaten it.")
        nm = cmean
    ranked = sorted((x for s, x in stats.items() if s != new_champ), key=lambda x: -x["mean"])
    chall = [x["style"] for x in ranked[:2]]
    if changed and champ not in chall and champ in stats:
        chall = ([champ] + chall)[:2]
    dropped = _dropped(stats, new_champ, nm, min_posts, reasons)
    chall = [c for c in chall if c not in dropped]
    return Recommendation(champion=new_champ, previous_champion=prev, changed=changed,
                          challengers=chall, dropped=dropped, reasons=reasons)


def _dropped(stats, champ, champ_mean, min_posts, reasons) -> List[str]:
    out = []
    for s, st in stats.items():
        if s != champ and st["n"] >= min_posts and st["ci_high"] < champ_mean:
            out.append(s)
            reasons.append(f"Consider dropping '{s}': even on a good day it ({st['ci_high']:.1f}) "
                           f"would not reach the champion's average ({champ_mean:.1f}).")
    return out


def apply_decision(rec: Recommendation, now: Optional[datetime] = None) -> dict:
    """Persist to champion.json, appending to history when the champion changes."""
    now = now or datetime.now(timezone.utc)
    cur = load_champion()
    history = cur.get("history", [])
    if rec.champion and (rec.changed or rec.champion != cur.get("champion")):
        history.append({"at": now.isoformat(timespec="seconds"), "from": cur.get("champion"),
                        "to": rec.champion, "reasons": rec.reasons})
    data = {"champion": rec.champion, "challengers": rec.challengers, "dropped": rec.dropped,
            "updated_at": now.isoformat(timespec="seconds"), "history": history}
    paths.write_json("champion.json", data)
    return data


# ------------------------------------------------------------------ account growth

def follower_growth() -> dict:
    hist = [h for h in paths.read_json("account.json", [])
            if h.get("followers_count") is not None and parse_time(h.get("at"))]
    hist.sort(key=lambda h: parse_time(h["at"]))
    if len(hist) < 2:
        return {"overall_per_day": None, "weeks": [], "snapshots": len(hist)}
    t0 = parse_time(hist[0]["at"])

    def rate(a, b):
        days = (parse_time(b["at"]) - parse_time(a["at"])).total_seconds() / 86400
        return None if days <= 0 else (b["followers_count"] - a["followers_count"]) / days

    weeks = []
    last = parse_time(hist[-1]["at"])
    k = 0
    while t0 + timedelta(days=7 * k) <= last:
        s, e = t0 + timedelta(days=7 * k), t0 + timedelta(days=7 * (k + 1))
        pts = [h for h in hist if s <= parse_time(h["at"]) < e or (e > last and parse_time(h["at"]) == last)]
        if len(pts) >= 2:
            weeks.append({"week": k + 1, "start": s.date().isoformat(),
                          "gained": pts[-1]["followers_count"] - pts[0]["followers_count"],
                          "per_day": rate(pts[0], pts[-1])})
        k += 1
    return {"overall_per_day": rate(hist[0], hist[-1]), "weeks": weeks, "snapshots": len(hist),
            "total_gained": hist[-1]["followers_count"] - hist[0]["followers_count"]}


# ------------------------------------------------------------------ render

def render_report(min_posts: int = 5, now: Optional[datetime] = None) -> Tuple[str, dict]:
    goals = paths.load_goals()
    records = post_records(goals)
    stats = style_stats(records)
    rec = recommend(min_posts=min_posts, now=now)
    growth = follower_growth()
    cur = load_champion()
    data = {
        "weights": goals["weights"],
        "styles": sorted(stats.values(), key=lambda x: -x["mean"]),
        "posts": records,
        "recommendation": asdict(rec),
        "current_champion": cur.get("champion"),
        "champion_history": cur.get("history", []),
        "follower_growth": growth,
        "min_posts": min_posts,
    }
    L = ["# Style experiment report", "",
         "Score = points per 1,000 people reached (follows x%g, profile visits x%g, shares x%g, saves x%g, "
         "comments x%g, likes x%g)." % tuple(goals["weights"][k] for k in
                                           ("follows", "profile_visits", "shares", "saved", "comments", "likes")), ""]
    L += ["## Styles", "", "| Style | Posts | Mean | Median | 90% range | Avg reach | Follows | Visits | Shares | Saves |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for s in data["styles"]:
        t = s["totals"]
        L.append(f"| {s['style']} | {s['n']} | {s['mean']:.1f} | {s['median']:.1f} | "
                 f"{s['ci_low']:.1f} to {s['ci_high']:.1f} | {s['mean_reach']:.0f} | {t.get('follows', 0):g} | "
                 f"{t.get('profile_visits', 0):g} | {t.get('shares', 0):g} | {t.get('saved', 0):g} |")
    if not stats:
        L.append("| (no measured posts yet) | | | | | | | | | |")
    early = sum(1 for r in records if r["early"])
    if early:
        L += ["", f"Note: {early} post(s) are less than 2 days old, so their numbers are early and will grow."]
    L += ["", "## Recommendation", ""]
    L.append(f"- Champion: {rec.champion or 'not chosen yet'}" + (" (changed)" if rec.changed else ""))
    L.append("- Challengers: " + (", ".join(rec.challengers) or "none"))
    L.append("- Consider dropping: " + (", ".join(rec.dropped) or "none"))
    L += [""] + [f"- {r}" for r in rec.reasons]
    L += ["", "## Follower growth", ""]
    if growth["overall_per_day"] is None:
        L.append("Not enough account snapshots yet (run `snapshot` on at least two different days).")
    else:
        L.append(f"Overall: {growth['overall_per_day']:+.1f} followers per day "
                 f"({growth['total_gained']:+d} in total).")
        for w in growth["weeks"]:
            L.append(f"- Week {w['week']} (from {w['start']}): {w['gained']:+d} followers, {w['per_day']:+.1f} per day")
    return "\n".join(L) + "\n", data
