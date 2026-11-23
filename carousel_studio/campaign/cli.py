"""Typer commands for the campaign calendar. Mount with app.add_typer(campaign_app, name="campaign")."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import typer

from .. import store
from . import apply_reviews as _apply_reviews
from . import assign_week as _assign_week
from . import attach_drafts_to_slots, load_calendar, plan_month
from . import publish_due as _publish_due

campaign_app = typer.Typer(help="Month-long posting calendar and style experiment.")


@campaign_app.command("plan")
def plan(start: str = typer.Argument(..., help="First day, YYYY-MM-DD"),
         days: int = typer.Option(30), per_day: int = typer.Option(3, "--per-day"),
         times: str = typer.Option("08:30,13:00,19:30", help="Comma-separated local HH:MM"),
         styles: str = typer.Option(..., help="Comma-separated style names for week 1"),
         tz: str = typer.Option("Africa/Accra")):
    """Create the slots; week 1 gets rotated styles, later weeks stay open."""
    cal = plan_month(date.fromisoformat(start), days=days, posts_per_day=per_day,
                     times=[t.strip() for t in times.split(",")],
                     styles=[s.strip() for s in styles.split(",") if s.strip()], tz=tz)
    typer.echo(f"Calendar has {len(cal.slots)} slots.")


@campaign_app.command("assign-week")
def assign_week_cmd(week_start: str, champion: str = typer.Option(...),
                    challenger: List[str] = typer.Option(..., help="Repeat for each challenger"),
                    champion_share: float = typer.Option(0.6)):
    """Assign styles for a later week: champion ~60%, challengers split the rest."""
    changed = _assign_week(date.fromisoformat(week_start), champion, challenger, champion_share)
    typer.echo(f"Assigned {len(changed)} slots.")


@campaign_app.command("attach")
def attach():
    """Match unscheduled drafts to open slots of their style."""
    res = attach_drafts_to_slots()
    for r in res:
        typer.echo(f"{r['draft_id']} -> {r['slot_id']} ({r['arm']}) {r['scheduled_at']}")
    typer.echo(f"Attached {len(res)} drafts.")


@campaign_app.command("calendar")
def show_calendar(days: int = typer.Option(7)):
    """Show the upcoming days: time, style, status, title."""
    cal = load_calendar()
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=days)
    for s in cal.slots:
        if today <= date.fromisoformat(s.date) < end:
            title = ""
            if s.draft_id:
                try:
                    title = store.load_draft(s.draft_id).idea.title
                except FileNotFoundError:
                    title = "(missing draft)"
            typer.echo(f"{s.date} {s.time}  {(s.style or '-'):<18} {(s.arm or '-'):<10} "
                       f"{s.status:<8} {title}{('  [' + s.reason + ']') if s.reason else ''}")


@campaign_app.command("publish-due")
def publish_due_cmd(dry_run: bool = typer.Option(False, "--dry-run"),
                    max_posts: int = typer.Option(3, "--max-posts")):
    """Post approved drafts whose slot time has come."""
    res = _publish_due(dry_run=dry_run, max_posts=max_posts)
    typer.echo(json.dumps(res, indent=2))


@campaign_app.command("apply-reviews")
def apply_reviews_cmd(path: str):
    """Apply a JSON export of review decisions to drafts."""
    typer.echo(json.dumps(_apply_reviews(path), indent=2))


@campaign_app.command("review-bundle")
def review_bundle_cmd(week_start: str, out: str = typer.Option("review_page", help="Output folder")):
    """Export a week's scheduled carousels (preview JPEGs + data.json) for the review page."""
    from .review_bundle import build_review_bundle

    data = build_review_bundle(week_start, out)
    typer.echo(f"{len(data['items'])} carousels exported to {out}/")


@campaign_app.command("log")
def log_cmd(last: int = typer.Option(20, help="How many entries to show")):
    """Show the post log (what was posted, when, and any failures)."""
    from .post_log import read_log

    for r in read_log()[-last:]:
        typer.echo(f"{r['logged_at']}  {r.get('slot_id',''):<14} {r.get('action',''):<8} "
                   f"{r.get('title','')}  {r.get('permalink') or r.get('reason') or ''}")


@campaign_app.command("sync-reviews")
def sync_reviews_cmd(folder: str):
    """Apply decisions saved by the review page (a folder exported with ArtifactData out_dir)."""
    import json as _json
    import tempfile

    from .reviews import apply_reviews, collect_review_dir

    items = collect_review_dir(folder)
    if not items:
        typer.echo("No review decisions found.")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        _json.dump(items, fh)
    for r in apply_reviews(fh.name):
        typer.echo(r)
