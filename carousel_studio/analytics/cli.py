"""Typer commands for analytics. Mount with: app.add_typer(analytics_app, name="analytics")."""
from __future__ import annotations

import json
from typing import Optional

import typer

analytics_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Style experiment analytics")


@analytics_app.command()
def snapshot():
    """Save current Instagram metrics for every published post, plus follower count."""
    from . import insights
    try:
        res = insights.snapshot_all()
        acct = insights.account_snapshot()
    except insights.InsightsError as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(f"Snapshotted {len(res['snapshotted'])} post(s); followers: {acct.get('followers_count')}")
    for did, err in res["errors"].items():
        typer.secho(f"  {did}: {err}", fg=typer.colors.YELLOW)


@analytics_app.command()
def report(
    as_json: bool = typer.Option(False, "--json", help="Print JSON for a dashboard"),
    min_posts: int = typer.Option(5, help="Posts per style needed before deciding"),
):
    """Compare styles and print the report."""
    from .report import render_report
    md, data = render_report(min_posts=min_posts)
    typer.echo(json.dumps(data, indent=2, default=str) if as_json else md)


@analytics_app.command()
def decide(min_posts: int = typer.Option(5, help="Posts per style needed before deciding")):
    """Pick champion/challengers and save data/analytics/champion.json."""
    from .report import apply_decision, recommend
    rec = recommend(min_posts=min_posts)
    apply_decision(rec)
    typer.echo(f"Champion: {rec.champion or 'not chosen yet'}")
    typer.echo("Challengers: " + (", ".join(rec.challengers) or "none"))
    typer.echo("Consider dropping: " + (", ".join(rec.dropped) or "none"))
    for r in rec.reasons:
        typer.echo(f"- {r}")


@analytics_app.command("merge-styles")
def merge_styles_cmd(
    a: str = typer.Argument(...), b: str = typer.Argument(...),
    name: str = typer.Option(..., "--name"),
    palette: Optional[str] = typer.Option(None, help="a or b (default a)"),
    typography: Optional[str] = typer.Option(None, help="a or b (default b)"),
    archetypes: Optional[str] = typer.Option(None, help="a or b (default b)"),
    decorations: Optional[str] = typer.Option(None, help="a or b (default a)"),
    voice: Optional[str] = typer.Option(None, help="a or b (default a)"),
):
    """Blend two learned styles into a new one."""
    from .merge import merge_styles
    take = {k: v for k, v in dict(palette=palette, typography=typography, archetypes=archetypes,
                                  decorations=decorations, voice=voice).items() if v}
    try:
        p = merge_styles(a, b, name, take)
    except (ValueError, FileNotFoundError) as e:
        typer.secho(str(e), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(f"Saved style '{p.name}': {p.summary}")
