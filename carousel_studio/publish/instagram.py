"""Instagram Graph API carousel publishing."""
from __future__ import annotations

import os
import time
from typing import Callable, List, Optional

try:
    import httpx
except ImportError:  # the httpx2 distribution
    import httpx2 as httpx  # type: ignore

from .. import store
from ..config import get_settings
from ..models import CarouselDraft, DraftStatus
from .hosting import upload_images

POLL_INTERVAL = 4.0
POLL_TIMEOUT = 120.0


class PublishError(RuntimeError):
    pass


def max_slides() -> int:
    try:
        return int(os.getenv("IG_MAX_SLIDES", "10"))
    except ValueError:
        return 10


def _creds():
    s = get_settings()
    if not s.ig_user_id:
        raise PublishError("IG_USER_ID is not set")
    if not s.ig_access_token:
        raise PublishError("IG_ACCESS_TOKEN is not set")
    return s, s.ig_user_id, s.ig_access_token


def _base(s) -> str:
    return f"https://graph.facebook.com/{s.graph_api_version}"


def _call(client, method: str, url: str, token: str, params: Optional[dict] = None) -> dict:
    params = dict(params or {})
    # Token goes in a header (not the query/form) so a secret-injecting proxy can supply it.
    headers = {"Authorization": f"Bearer {token}"}
    try:
        if method == "GET":
            r = client.get(url, params=params, headers=headers)
        else:
            r = client.post(url, data=params, headers=headers)
    except httpx.HTTPError as e:
        raise PublishError(f"Network error calling Instagram: {e}") from e
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code >= 400 or (isinstance(body, dict) and "error" in body):
        err = body.get("error", {}) if isinstance(body, dict) else {}
        msg = err.get("error_user_msg") or err.get("message") or r.text[:300]
        extra = f" (code {err['code']}" + (f", subcode {err['error_subcode']}" if err.get("error_subcode") else "") + ")" if err.get("code") else ""
        raise PublishError(f"Instagram API error {r.status_code}: {msg}{extra}")
    return body


def full_caption(draft: CarouselDraft) -> str:
    tags = " ".join("#" + t.strip().lstrip("#").replace(" ", "") for t in draft.hashtags if t.strip().lstrip("#"))
    return draft.caption + ("\n\n" + tags if tags else "")


def verify_credentials(client=None) -> dict:
    s, uid, tok = _creds()
    c = client or httpx.Client(timeout=30)
    return _call(c, "GET", f"{_base(s)}/{uid}", tok, {"fields": "username,media_count"})


def check_publishing_limit(client=None) -> dict:
    s, uid, tok = _creds()
    c = client or httpx.Client(timeout=30)
    return _call(c, "GET", f"{_base(s)}/{uid}/content_publishing_limit", tok, {"fields": "quota_usage,config"})


def _wait_finished(client, base, tok, container_id, sleep, timeout, interval):
    waited = 0.0
    while True:
        st = _call(client, "GET", f"{base}/{container_id}", tok, {"fields": "status_code"})
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise PublishError(f"Instagram media container {code}: {st.get('status', '')}".strip())
        if waited >= timeout:
            raise PublishError(f"Timed out waiting for Instagram container (last status: {code})")
        sleep(interval)
        waited += interval


def publish_draft(
    draft_id: str,
    client=None,
    sleep: Optional[Callable[[float], None]] = None,
    poll_timeout: float = POLL_TIMEOUT,
    poll_interval: float = POLL_INTERVAL,
    image_urls: Optional[List[str]] = None,
) -> CarouselDraft:
    draft = store.load_draft(draft_id)
    if draft.status != DraftStatus.approved:
        raise PublishError(f"Draft {draft_id} is '{draft.status.value}'; only approved drafts can be published")
    n, limit = len(draft.slides), max_slides()
    if n < 2 or n > limit:
        raise PublishError(f"Instagram carousels need 2-{limit} slides; this draft has {n}")
    sleep = sleep or time.sleep
    own = client is None
    c = client or httpx.Client(timeout=60)
    try:
        s, uid, tok = _creds()
        base = _base(s)
        urls = image_urls or upload_images(draft)
        children = []
        for u in urls:
            r = _call(c, "POST", f"{base}/{uid}/media", tok, {"image_url": u, "is_carousel_item": "true"})
            children.append(r["id"])
        r = _call(c, "POST", f"{base}/{uid}/media", tok, {
            "media_type": "CAROUSEL", "children": ",".join(children), "caption": full_caption(draft)})
        container = r["id"]
        _wait_finished(c, base, tok, container, sleep, poll_timeout, poll_interval)
        r = _call(c, "POST", f"{base}/{uid}/media_publish", tok, {"creation_id": container})
        media_id = r["id"]
        permalink = None
        try:
            permalink = _call(c, "GET", f"{base}/{media_id}", tok, {"fields": "permalink"}).get("permalink")
        except PublishError:
            pass  # published fine; permalink is cosmetic
        draft.status = DraftStatus.published
        draft.ig_media_id = media_id
        draft.ig_permalink = permalink
        draft.error = None
    except Exception as e:
        draft.status = DraftStatus.failed
        draft.error = str(e)
    finally:
        if own:
            c.close()
    store.save_draft(draft)
    return draft
