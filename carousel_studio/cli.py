"""`studio` command line.

Typical flow:
  studio learn my-style ./screenshots @someaccount https://instagram.com/p/XYZ/
  studio preview my-style
  studio make my-style -n 3
  studio review            # approve / edit / publish in the browser
"""
from __future__ import annotations

import json
from typing import List, Optional

import typer

from . import store
from .config import BRAND_FILE, get_settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Carousel Studio")


@app.command()
def learn(
    style: str = typer.Argument(..., help="Name for this style, e.g. 'bold-dark'"),
    sources: List[str] = typer.Argument(..., help="Folders of screenshots, post links and/or @handles"),
    per_account: int = typer.Option(8, help="Carousels to pull per @handle"),
    analyze: bool = typer.Option(True, help="Run style analysis right after ingesting"),
):
    """Collect reference carousels you like, then learn their style."""
    from .ingest import ingest_accounts, ingest_local, ingest_post_urls, parse_inputs

    folders, urls, handles = parse_inputs(sources)
    refs = []
    for f in folders:
        refs += ingest_local(style, f)
    if urls:
        refs += ingest_post_urls(style, urls)
    if handles:
        refs += ingest_accounts(style, handles, per_account=per_account)
    total = len(store.list_references(style))
    typer.echo(f"Added {len(refs)} carousels ({total} total) to style '{store.slugify(style)}'.")
    if analyze:
        _analyze(style)


def _analyze(style: str) -> None:
    from .style import analyze_style

    typer.echo("Analysing style with Claude…")
    p = analyze_style(style)
    typer.echo(f"\n{p.name}: {p.summary}\n  palette: {p.palette.model_dump()}\n"
               f"  fonts: {p.typography.heading_font} / {p.typography.body_font}\n"
               f"  slides: ~{p.slide_count}, ~{p.words_per_slide} words each\n  tone: {p.tone}")


@app.command()
def analyze(style: str):
    """Re-run style analysis on the references already collected."""
    _analyze(style)


@app.command()
def preview(style: str):
    """Render sample slides so you can check the style was captured well."""
    from .render import render_preview

    for p in render_preview(style):
        typer.echo(p)


@app.command()
def ideas(style: str, n: int = 8, theme: Optional[str] = None):
    """Brainstorm carousel ideas (nothing is saved)."""
    from .generate import generate_ideas

    for i, idea in enumerate(generate_ideas(style, n=n, theme=theme), 1):
        typer.echo(f"{i}. {idea.title}\n   hook: {idea.hook}\n   why: {idea.angle}\n")


@app.command()
def make(style: str, n: int = typer.Option(3, "-n"), theme: Optional[str] = None):
    """Generate and render N new carousel drafts for review."""
    from .generate import create_drafts

    for d in create_drafts(style, n=n, theme=theme):
        typer.echo(f"[{d.id}] {d.idea.title} — {len(d.slides)} slides")
    typer.echo("\nOpen the review app to approve:  studio review")


@app.command("list")
def list_cmd():
    """List drafts and their status."""
    for d in store.list_drafts():
        typer.echo(f"{d.status.value:<10} {d.id}  {d.idea.title}  ({d.style})"
                   + (f"  {d.ig_permalink}" if d.ig_permalink else ""))


@app.command()
def approve(draft_id: str):
    """Approve a draft from the terminal."""
    from .models import DraftStatus

    d = store.load_draft(draft_id)
    d.status = DraftStatus.approved
    store.save_draft(d)
    typer.echo(f"Approved {draft_id}")


@app.command()
def publish(draft_id: str, yes: bool = typer.Option(False, "--yes", help="Skip confirmation")):
    """Post an approved draft to Instagram."""
    from .publish import publish_draft

    d = store.load_draft(draft_id)
    if not yes:
        typer.confirm(f"Post '{d.idea.title}' ({len(d.slides)} slides) to Instagram now?", abort=True)
    d = publish_draft(draft_id)
    typer.echo(f"{d.status.value}: {d.ig_permalink or d.error}")


@app.command()
def review(host: str = "127.0.0.1", port: int = 8000):
    """Start the review web app."""
    import uvicorn

    from .review import create_app

    typer.echo(f"Review app: http://{host}:{port}")
    uvicorn.run(create_app(), host=host, port=port)


@app.command()
def brand():
    """Show where your niche/audience settings live."""
    get_settings()
    typer.echo(f"Edit {BRAND_FILE}:\n")
    typer.echo(BRAND_FILE.read_text())


@app.command()
def doctor():
    """Check that keys and accounts are configured."""
    import os

    s = get_settings()
    checks = {
        "Claude API key": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")),
        "Apify token (for links/@handles)": bool(s.apify_token),
        "Instagram user id + token": bool(s.ig_user_id and s.ig_access_token),
        "Image host": {"vercel": bool(s.blob_token), "s3": bool(s.s3_bucket and s.s3_public_base_url)}.get(
            s.image_host, bool(s.public_base_url)),
        "Niche set in brand.json": "CHANGE ME" not in json.dumps(s.brand),
    }
    for k, ok in checks.items():
        typer.echo(f"{'OK ' if ok else '-- '} {k}")
    if checks["Instagram user id + token"]:
        from .publish import check_publishing_limit, verify_credentials

        try:
            typer.echo(f"Instagram account: {verify_credentials()}")
            typer.echo(f"Publishing quota: {check_publishing_limit()}")
        except Exception as e:  # noqa: BLE001
            typer.echo(f"Instagram check failed: {e}")


if __name__ == "__main__":
    app()
