"""Local review web app: approve carousel drafts before they are posted."""
from __future__ import annotations

import base64
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Dict

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .. import config, store
from ..models import DraftStatus

TEMPLATES = Path(__file__).parent / "templates"
SAFE_NAME = re.compile(r"^[\w.-]+\.(png|jpg|jpeg)$")
PUBLIC_JPG = re.compile(r"^/drafts/[\w-]+/slide_\d+\.jpg$")
STATUS_ORDER = ["draft", "approved", "failed", "published", "rejected"]

# in-memory registry of running background jobs: key -> description
_jobs: Dict[str, str] = {}
_jobs_lock = threading.Lock()
_errors: Dict[str, str] = {}


def _job_start(key: str, text: str) -> None:
    with _jobs_lock:
        _jobs[key] = text
        _errors.pop(key, None)


def _job_end(key: str, error: str | None = None) -> None:
    with _jobs_lock:
        _jobs.pop(key, None)
        if error:
            _errors[key] = error


def _slide_url(draft, slide) -> str | None:
    if not slide.rendered_path:
        return None
    return f"/drafts-files/{draft.id}/{Path(slide.rendered_path).name}?v={draft.updated_at}"


def create_app() -> FastAPI:
    app = FastAPI(title="Carousel Studio review")
    templates = Jinja2Templates(directory=str(TEMPLATES))
    templates.env.globals["slide_url"] = _slide_url

    # ---- optional basic auth
    @app.middleware("http")
    async def basic_auth(request: Request, call_next):
        password = os.getenv("REVIEW_PASSWORD")
        if password:
            # Instagram must fetch slide JPEGs unauthenticated when IMAGE_HOST=local.
            public = (
                config_image_host() == "local" and PUBLIC_JPG.match(request.url.path)
            )
            if not public:
                ok = False
                header = request.headers.get("authorization", "")
                if header.lower().startswith("basic "):
                    try:
                        _, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                        ok = secrets.compare_digest(pw, password)
                    except Exception:
                        ok = False
                if not ok:
                    return Response("Authentication required", status_code=401,
                                    headers={"WWW-Authenticate": 'Basic realm="Carousel Studio"'})
        return await call_next(request)

    def config_image_host() -> str:
        return (os.getenv("IMAGE_HOST") or config.get_settings().image_host or "s3").lower()

    def get_draft(draft_id: str):
        try:
            return store.load_draft(draft_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "Draft not found")

    def serve_image(draft_id: str, name: str):
        if not SAFE_NAME.match(name) or not re.match(r"^[\w-]+$", draft_id):
            raise HTTPException(404)
        p = store.DRAFTS_DIR / draft_id / name
        if not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "no-cache"})

    # ---------------------------------------------------------------- pages
    @app.get("/")
    def index(request: Request):
        drafts = store.list_drafts()
        groups = []
        for st in STATUS_ORDER:
            items = [d for d in drafts if d.status.value == st]
            if items:
                groups.append((st, items))
        try:
            styles = store.list_styles()
        except Exception:
            styles = []
        return templates.TemplateResponse(request, "index.html", {
            "groups": groups, "styles": styles, "jobs": list(_jobs.values()),
            "errors": list(_errors.values()), "total": len(drafts)})

    @app.post("/generate")
    def generate(background: BackgroundTasks, style: str = Form(...), count: int = Form(3),
                 theme: str = Form("")):
        count = max(1, min(count, 10))
        theme = theme.strip() or None
        key = f"gen-{secrets.token_hex(4)}"
        _job_start(key, f"Generating {count} draft(s) in style '{style}'" + (f" about '{theme}'" if theme else ""))

        def run():
            try:
                from carousel_studio.generate import create_drafts
                from carousel_studio.render import render_draft

                for d in create_drafts(style, n=count, theme=theme):
                    # Rendering is a no-op if create_drafts already rendered.
                    if not all(s.rendered_path for s in d.slides):
                        store.save_draft(render_draft(d))
                _job_end(key)
            except Exception as e:  # noqa: BLE001
                _job_end(key, f"Generation failed: {e}")

        background.add_task(run)
        return RedirectResponse("/", status_code=303)

    @app.get("/drafts/{draft_id}")
    def detail(request: Request, draft_id: str):
        d = get_draft(draft_id)
        return templates.TemplateResponse(request, "detail.html", {
            "d": d, "busy": _jobs.get(f"rev-{draft_id}"), "job_error": _errors.get(f"rev-{draft_id}"),
            "full_text": d.caption + ("\n\n" + " ".join("#" + t.lstrip("#") for t in d.hashtags) if d.hashtags else "")})

    @app.get("/drafts-files/{draft_id}/{name}")
    def files(draft_id: str, name: str):
        return serve_image(draft_id, name)

    @app.get("/drafts/{draft_id}/{name}")
    def public_files(draft_id: str, name: str):
        # Instagram fetches these via PUBLIC_BASE_URL when IMAGE_HOST=local.
        if config_image_host() != "local":
            raise HTTPException(404)
        return serve_image(draft_id, name)

    # ---------------------------------------------------------------- actions
    def back(draft_id: str):
        return RedirectResponse(f"/drafts/{draft_id}", status_code=303)

    @app.post("/drafts/{draft_id}/caption")
    def caption(draft_id: str, caption: str = Form("")):
        d = get_draft(draft_id)
        # a trailing block of #tags becomes the hashtag list; the rest is the caption
        text = caption.strip()
        trailing = re.search(r"((?:\s+|^)#\w+)+\s*$", text)
        d.hashtags = re.findall(r"#(\w+)", trailing.group(0)) if trailing else []
        d.caption = text[: trailing.start()].strip() if trailing else text
        store.save_draft(d)
        return back(draft_id)

    @app.post("/drafts/{draft_id}/approve")
    def approve(draft_id: str):
        d = get_draft(draft_id)
        if d.status == DraftStatus.published:
            raise HTTPException(400, "Already published")
        d.status = DraftStatus.approved
        d.error = None
        store.save_draft(d)
        return back(draft_id)

    @app.post("/drafts/{draft_id}/reject")
    def reject(draft_id: str):
        d = get_draft(draft_id)
        if d.status == DraftStatus.published:
            raise HTTPException(400, "Already published")
        d.status = DraftStatus.rejected
        store.save_draft(d)
        return back(draft_id)

    @app.post("/drafts/{draft_id}/revise")
    def revise(draft_id: str, background: BackgroundTasks, feedback: str = Form(...)):
        d = get_draft(draft_id)
        if d.status == DraftStatus.published:
            raise HTTPException(400, "Already published")
        key = f"rev-{draft_id}"
        _job_start(key, "Revising with your feedback")

        def run():
            try:
                from carousel_studio.generate import revise_draft
                from carousel_studio.render import render_draft

                new = revise_draft(draft_id, feedback)
                store.save_draft(render_draft(new))
                _job_end(key)
            except Exception as e:  # noqa: BLE001
                _job_end(key, f"Revision failed: {e}")

        background.add_task(run)
        return back(draft_id)

    @app.post("/drafts/{draft_id}/publish")
    def publish(draft_id: str):
        from carousel_studio.publish import publish_draft  # lazy

        get_draft(draft_id)
        try:
            publish_draft(draft_id)
        except Exception as e:  # not approved, bad config, ...
            d = get_draft(draft_id)
            if d.status != DraftStatus.published:
                d.error = str(e)
                if d.status == DraftStatus.approved:
                    d.status = DraftStatus.failed
                store.save_draft(d)
        return back(draft_id)

    return app


app = None  # use create_app(); `uvicorn carousel_studio.review.app:create_app --factory`
