"""Get reference carousels onto disk: local screenshots, post URLs, or whole accounts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from .instagram import ApifyError, ingest_accounts, ingest_post_urls
from .local import ingest_local
from .pinterest import ingest_pinterest

__all__ = ["ingest_local", "ingest_post_urls", "ingest_accounts", "ingest_pinterest", "parse_inputs", "ApifyError"]

_POST_RE = re.compile(r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv)/[A-Za-z0-9_-]+", re.I)
_PROFILE_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)/?(?:\?.*)?$", re.I)
_PINTEREST_RE = re.compile(r"(?:^|[/.@])(?:[a-z]{2,3}\.)?pinterest\.[a-z.]+(?:/|$)|(?:^|[/.@])pin\.it/", re.I)
_RESERVED = {"p", "reel", "reels", "tv", "explore", "stories", "accounts", "direct"}


def parse_inputs(items: List[str]) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Sort a mixed list into (folders, post_urls, handles, pinterest_urls).

    instagram.com/p/... or /reel/... -> post URLs; instagram.com/<name> or '@name' -> handles;
    pinterest.com / pin.it URLs -> pinterest_urls; existing filesystem paths -> folders. Anything else raises ValueError.
    """
    folders: List[str] = []
    posts: List[str] = []
    handles: List[str] = []
    pins: List[str] = []
    unknown: List[str] = []
    for raw in items:
        s = (raw or "").strip()
        if not s:
            continue
        if _PINTEREST_RE.search(s):
            pins.append(s)
        elif _POST_RE.search(s):
            posts.append(s)
        elif "instagram.com" in s.lower():
            m = _PROFILE_RE.search(s)
            if m and m.group(1).lower() not in _RESERVED:
                handles.append(m.group(1))
            else:
                unknown.append(s)
        elif s.startswith("@") and len(s) > 1:
            handles.append(s[1:])
        elif Path(s).expanduser().exists():
            folders.append(str(Path(s).expanduser()))
        else:
            unknown.append(s)
    if unknown:
        raise ValueError(
            "Could not interpret: " + ", ".join(unknown)
            + " (expected a folder path, an instagram.com/p/... URL, or an @handle, or a pinterest.com / pin.it URL)"
        )
    return folders, posts, handles, pins
