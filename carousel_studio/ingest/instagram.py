"""Ingest reference carousels from Instagram via the Apify Instagram Scraper (REST)."""
from __future__ import annotations

import logging
import re
import shutil
from typing import Any, Dict, List, Optional

try:
    import httpx  # type: ignore
except ImportError:  # installed under a different name in some environments
    import httpx2 as httpx  # type: ignore

from .. import store
from ..config import get_settings
from ..models import ReferenceCarousel, ReferenceSource
from .common import dedupe, normalize_bytes, ref_exists, safe_id, slide_name

log = logging.getLogger(__name__)

APIFY_URL = "https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items"
APIFY_TIMEOUT = 300.0
DOWNLOAD_TIMEOUT = 60.0
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


class ApifyError(RuntimeError):
    pass


# ------------------------------------------------------------------ apify

def _token() -> str:
    token = get_settings().apify_token
    if not token:
        raise ApifyError(
            "APIFY_TOKEN is not set. Create a token at https://console.apify.com/account/integrations "
            "and add APIFY_TOKEN=... to your .env (or ingest local screenshots instead)."
        )
    return token


def run_scraper(direct_urls: List[str], results_limit: int) -> List[Dict[str, Any]]:
    payload = {
        "directUrls": direct_urls,
        "resultsType": "posts",
        "resultsLimit": results_limit,
        "addParentData": False,
    }
    try:
        resp = httpx.post(
            APIFY_URL, headers={"Authorization": f"Bearer {_token()}"}, json=payload, timeout=APIFY_TIMEOUT
        )
    except httpx.TimeoutException as e:
        raise ApifyError(f"Apify scraper timed out after {APIFY_TIMEOUT:.0f}s") from e
    except httpx.HTTPError as e:
        raise ApifyError(f"Could not reach Apify: {e}") from e
    if resp.status_code >= 400:
        raise ApifyError(f"Apify returned HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    if isinstance(data, dict):  # some error shapes / wrappers
        data = data.get("items") or data.get("data") or []
    items = [it for it in data if isinstance(it, dict)]
    for it in items:
        if it.get("error"):
            log.warning("Apify item error for %s: %s", it.get("url") or it.get("inputUrl"), it.get("error"))
    return [it for it in items if not it.get("error")]


# ------------------------------------------------------------- item parsing

def _get(d: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _int(v) -> Optional[int]:
    try:
        return int(v) if v is not None and int(v) >= 0 else None
    except (TypeError, ValueError):
        return None


def item_type(item: Dict[str, Any]) -> str:
    t = str(_get(item, "type", "productType", "__typename", default="")).lower()
    if "sidecar" in t or "carousel" in t:
        return "Sidecar"
    if "video" in t or "clip" in t or "reel" in t:
        return "Video"
    if t:
        return "Image"
    children = _get(item, "childPosts", "children", "sidecarChildren", default=[]) or []
    return "Sidecar" if len(children) > 1 or len(item.get("images") or []) > 1 else "Image"


def _is_video_child(child: Dict[str, Any]) -> bool:
    t = str(_get(child, "type", "__typename", default="")).lower()
    return "video" in t or bool(child.get("isVideo")) or (bool(child.get("videoUrl")) and "image" not in t)


def slide_urls(item: Dict[str, Any]) -> List[str]:
    """Image URLs for each slide, in order, skipping video children."""
    children = _get(item, "childPosts", "children", "sidecarChildren", default=[]) or []
    urls: List[str] = []
    if children:
        for c in children:
            if isinstance(c, str):
                urls.append(c)
            elif isinstance(c, dict) and not _is_video_child(c):
                u = _get(c, "displayUrl", "imageUrl", "display_url", "url")
                if isinstance(u, str) and u.startswith("http") and "instagram.com/p/" not in u:
                    urls.append(u)
    if not urls:
        imgs = item.get("images") or []
        urls = [u if isinstance(u, str) else _get(u, "url", "displayUrl", default="") for u in imgs]
    if not urls and item_type(item) != "Video":
        u = _get(item, "displayUrl", "imageUrl")
        if u:
            urls = [u]
    return dedupe(u for u in urls if isinstance(u, str) and u.startswith("http"))


def engagement(item: Dict[str, Any]) -> int:
    return (_int(_get(item, "likesCount", "likes", "likeCount")) or 0) + (
        _int(_get(item, "commentsCount", "comments", "commentCount")) or 0
    )


def shortcode(item: Dict[str, Any]) -> Optional[str]:
    sc = _get(item, "shortCode", "shortcode", "code")
    if not sc:
        m = re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reel|tv)/([A-Za-z0-9_-]+)", str(item.get("url") or ""))
        sc = m.group(1) if m else None
    return str(sc) if sc else None


# --------------------------------------------------------------- download

def _download(client, url: str) -> bytes:
    r = client.get(url)
    r.raise_for_status()
    return r.content


def save_item(style: str, item: Dict[str, Any], source: ReferenceSource, origin: str) -> Optional[ReferenceCarousel]:
    sc = shortcode(item)
    ref_id = safe_id(sc) if sc else store.new_id("ref_")
    if ref_exists(style, ref_id):
        log.info("Skipping %s: already ingested", ref_id)
        return None
    urls = slide_urls(item)
    if not urls:
        log.warning("No image slides found for %s", item.get("url") or ref_id)
        return None

    dest = store.ref_dir(style, ref_id)
    paths: List[str] = []
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}) as client:
        for u in urls:
            try:
                out = normalize_bytes(_download(client, u), dest / slide_name(len(paths) + 1))
                paths.append(str(out))
            except Exception as e:
                log.warning("Failed to download slide %s for %s: %s", u[:80], ref_id, e)
    if not paths:
        shutil.rmtree(dest, ignore_errors=True)
        log.warning("Could not download any slides for %s (CDN links may have expired)", ref_id)
        return None

    ref = ReferenceCarousel(
        id=ref_id,
        source=source,
        origin=origin,
        slide_paths=paths,
        caption=_get(item, "caption", "text"),
        likes=_int(_get(item, "likesCount", "likes", "likeCount")),
        comments=_int(_get(item, "commentsCount", "comments", "commentCount")),
    )
    store.save_reference(style, ref)
    return ref


# ----------------------------------------------------------------- public

def _norm_post_url(u: str) -> str:
    u = u.strip()
    if not u.startswith("http"):
        u = "https://" + u.lstrip("/")
    return u.split("?")[0]


def ingest_post_urls(style: str, urls: List[str]) -> List[ReferenceCarousel]:
    """Download specific Instagram posts (carousels; single images accepted, videos skipped)."""
    urls = dedupe(_norm_post_url(u) for u in urls if u and u.strip())
    if not urls:
        return []
    _token()  # fail fast before any work
    items = run_scraper(urls, results_limit=1)
    by_sc = {}
    for u in urls:
        m = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", u)
        if m:
            by_sc[m.group(1)] = u
    refs: List[ReferenceCarousel] = []
    seen = set()
    for it in items:
        sc = shortcode(it)
        if sc in seen:
            continue
        seen.add(sc)
        if item_type(it) == "Video" and not slide_urls(it):
            log.warning("Skipping video post %s", it.get("url"))
            continue
        origin = by_sc.get(sc or "", None) or _get(it, "url", "inputUrl", default=urls[0])
        ref = save_item(style, it, ReferenceSource.post_url, origin)
        if ref:
            refs.append(ref)
    return refs


def _norm_handle(h: str) -> str:
    h = h.strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", h)
    if m:
        h = m.group(1)
    return h.lstrip("@").strip("/").lower()


def _owner(item: Dict[str, Any]) -> str:
    o = _get(item, "ownerUsername", "username")
    if not o and isinstance(item.get("owner"), dict):
        o = item["owner"].get("username")
    if not o:
        m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", str(item.get("inputUrl") or ""))
        o = m.group(1) if m else ""
    return str(o).lower()


def ingest_accounts(style: str, handles: List[str], per_account: int = 8) -> List[ReferenceCarousel]:
    """Pull recent posts from each account and keep the top `per_account` carousels by likes+comments."""
    handles = dedupe(_norm_handle(h) for h in handles if h and h.strip())
    if not handles:
        return []
    _token()
    direct = [f"https://www.instagram.com/{h}/" for h in handles]
    # Fetch more than needed: many posts are reels/single images, and we rank by engagement.
    items = run_scraper(direct, results_limit=max(per_account * 4, 24))

    groups: Dict[str, List[Dict[str, Any]]] = {h: [] for h in handles}
    for it in items:
        if item_type(it) != "Sidecar":
            continue
        o = _owner(it)
        if o in groups:
            groups[o].append(it)
        elif len(handles) == 1:
            groups[handles[0]].append(it)

    refs: List[ReferenceCarousel] = []
    for h, its in groups.items():
        if not its:
            log.warning("No carousel posts found for @%s", h)
            continue
        uniq = {shortcode(i) or id(i): i for i in its}.values()
        top = sorted(uniq, key=engagement, reverse=True)[:per_account]
        for it in top:
            ref = save_item(style, it, ReferenceSource.account, f"@{h}")
            if ref:
                refs.append(ref)
    return refs
