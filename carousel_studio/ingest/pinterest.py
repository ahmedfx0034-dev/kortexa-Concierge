"""Ingest reference images from Pinterest via the Apify Pinterest Scraper (REST)."""
from __future__ import annotations

import logging
import re
import shutil
from typing import Any, Dict, List, Optional

from .. import store
from ..models import ReferenceCarousel, ReferenceSource
from .common import dedupe, normalize_bytes, ref_exists, safe_id, slide_name
from .instagram import (  # shared token handling, errors, timeouts and HTTP client
    APIFY_TIMEOUT, DOWNLOAD_TIMEOUT, UA, ApifyError, _download, _int, _token, httpx,
)

log = logging.getLogger(__name__)

APIFY_URL = "https://api.apify.com/v2/acts/epctex~pinterest-scraper/run-sync-get-dataset-items"
_PIN_RE = re.compile(r"pinterest\.[a-z.]+/pin/(?:[^/?#]*--)?(\d+)", re.I)


def _norm_url(u: str) -> str:
    u = u.strip()
    if not u.startswith("http"):
        u = "https://" + u.lstrip("/")
    return u.split("#")[0]


def _is_pin_url(u: str) -> bool:
    return bool(_PIN_RE.search(u)) or "pin.it/" in u.lower()


def run_scraper(start_urls: List[str], max_items: int) -> List[Dict[str, Any]]:
    payload = {
        "startUrls": start_urls,
        "getDetails": True,
        "includeComments": False,
        "maxItems": max_items,
        "endPage": 1,
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
    if isinstance(data, dict):
        data = data.get("items") or data.get("data") or []
    items = [it for it in data if isinstance(it, dict)]
    for it in items:
        if it.get("error"):
            log.warning("Apify item error for %s: %s", it.get("url"), it.get("error"))
    return [it for it in items if not it.get("error")]


def best_image_url(item: Dict[str, Any]) -> Optional[str]:
    """orig, else 736x, else the largest available size."""
    imgs = item.get("images")
    if not isinstance(imgs, dict):
        return None

    def url_of(v: Any) -> Optional[str]:
        u = v.get("url") if isinstance(v, dict) else v if isinstance(v, str) else None
        return u if isinstance(u, str) and u.startswith("http") else None

    for key in ("orig", "736x"):
        u = url_of(imgs.get(key))
        if u:
            return u
    best, best_area = None, -1
    for v in imgs.values():
        u = url_of(v)
        if not u:
            continue
        area = (_int(v.get("width")) or 0) * (_int(v.get("height")) or 0) if isinstance(v, dict) else 0
        if area > best_area:
            best, best_area = u, area
    return best


def _likes(item: Dict[str, Any]) -> int:
    return _int(item.get("like_count")) or 0


def _group_key(item: Dict[str, Any]) -> str:
    b = item.get("board")
    if isinstance(b, dict):
        b = b.get("url") or b.get("id") or b.get("name")
    p = item.get("pinner")
    if isinstance(p, dict):
        p = p.get("username") or p.get("url")
    return str(b or p or "")


def _caption(item: Dict[str, Any]) -> Optional[str]:
    parts = [str(item.get(k)).strip() for k in ("grid_title", "description") if item.get(k)]
    parts = dedupe(p for p in parts if p)
    return "\n\n".join(parts) or None


def _save_pin(style: str, item: Dict[str, Any], origin: str) -> Optional[ReferenceCarousel]:
    pid = item.get("id")
    if not pid:
        m = _PIN_RE.search(str(item.get("url") or ""))
        pid = m.group(1) if m else None
    if not pid:
        log.warning("Skipping pin without id: %s", item.get("url"))
        return None
    ref_id = safe_id(f"pin_{pid}")
    if ref_exists(style, ref_id):
        log.info("Skipping %s: already ingested", ref_id)
        return None
    url = best_image_url(item)
    if not url:
        log.warning("No image found for pin %s (video or idea pin?)", pid)
        return None
    dest = store.ref_dir(style, ref_id)
    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}) as client:
            out = normalize_bytes(_download(client, url), dest / slide_name(1))
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        log.warning("Failed to download image for %s: %s", ref_id, e)
        return None
    ref = ReferenceCarousel(
        id=ref_id,
        source=ReferenceSource.pinterest,
        origin=origin,
        slide_paths=[str(out)],
        caption=_caption(item),
        likes=_int(item.get("like_count")),
    )
    store.save_reference(style, ref)
    return ref


def ingest_pinterest(style: str, urls: List[str], per_board: int = 12) -> List[ReferenceCarousel]:
    """Download Pinterest references: each pin becomes a one-slide reference.

    Pin URLs (and pin.it links) are taken as-is. Board / user / idea / search URLs are capped at
    `per_board` pins per board, preferring the most-liked.
    """
    urls = dedupe(_norm_url(u) for u in urls if u and u.strip())
    if not urls:
        return []
    _token()  # fail fast before any work
    pins = [u for u in urls if _is_pin_url(u)]
    colls = [u for u in urls if not _is_pin_url(u)]
    refs: List[ReferenceCarousel] = []

    if pins:
        items = run_scraper(pins, max_items=len(pins))
        seen = set()
        for it in items:
            if it.get("id") in seen:
                continue
            seen.add(it.get("id"))
            origin = next((u for u in pins if str(it.get("id")) in u), None) or (
                pins[0] if len(pins) == 1 else str(it.get("url") or pins[0])
            )
            ref = _save_pin(style, it, origin)
            if ref:
                refs.append(ref)

    if colls:
        # Fetch extra: some pins have no usable image, and we rank by likes.
        items = run_scraper(colls, max_items=max(per_board * 2, per_board + 6) * len(colls))
        groups: Dict[str, Dict[Any, Dict[str, Any]]] = {}
        for it in items:
            groups.setdefault(_group_key(it), {})[it.get("id") or id(it)] = it
        for key, by_id in groups.items():
            top = sorted(by_id.values(), key=_likes, reverse=True)[:per_board]
            for it in top:
                ref = _save_pin(style, it, colls[0] if len(colls) == 1 else (key or colls[0]))
                if ref:
                    refs.append(ref)
    return refs
