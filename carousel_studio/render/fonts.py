"""Google Fonts loader.

Fonts are fetched once from fonts.googleapis.com by Python, cached on disk and
inlined into the page as base64 @font-face rules. That makes renders
deterministic, fast and offline-friendly. If the network is blocked we fall back
to a sensible local font stack (the page never waits on a dead <link>).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

# A modern desktop UA makes the css2 API answer with woff2 files.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_TIMEOUT = 8
_offline = False  # set after the first network failure so we don't retry per font

SERIF_HINTS = (
    "serif", "playfair", "garamond", "lora", "merriweather", "libre baskerville", "baskerville",
    "cormorant", "dm serif", "fraunces", "crimson", "bodoni", "prata", "spectral", "newsreader",
    "instrument serif", "abril", "cardo", "eb garamond", "noto serif", "source serif", "pt serif",
    "bitter", "zilla", "roboto slab", "arvo", "domine", "gloock", "young serif", "literata",
)
MONO_HINTS = ("mono", "code", "courier", "space mono", "ibm plex mono")
DISPLAY_HINTS = ("bebas", "anton", "oswald", "league gothic", "archivo black", "druk", "impact",
                 "barlow condensed", "big shoulders", "fjalla")


def cache_dir() -> Path:
    d = Path(os.getenv("STUDIO_FONT_CACHE", Path.home() / ".cache" / "carousel-studio" / "fonts"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def fallback_stack(family: str) -> str:
    f = family.lower()
    if any(h in f for h in MONO_HINTS):
        return "'JetBrains Mono', 'DejaVu Sans Mono', ui-monospace, monospace"
    if any(h in f for h in SERIF_HINTS) and "sans" not in f:
        return "Georgia, 'Times New Roman', 'Liberation Serif', 'DejaVu Serif', serif"
    if any(h in f for h in DISPLAY_HINTS):
        return "'Inter Display', 'Inter', 'Arial Narrow', 'Helvetica Neue', Arial, sans-serif"
    return "'Inter', 'Helvetica Neue', Helvetica, Arial, 'Liberation Sans', sans-serif"


def css_stack(family: str) -> str:
    return f"'{family}', {fallback_stack(family)}"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read()


def _cached(url: str, suffix: str) -> bytes | None:
    """Download url once; returns None when unavailable (bad weight, offline...)."""
    global _offline
    key = hashlib.sha1(url.encode()).hexdigest()
    p = cache_dir() / f"{key}{suffix}"
    miss = cache_dir() / f"{key}.missing"
    if p.exists():
        return p.read_bytes()
    if miss.exists() or _offline:
        return None
    try:
        data = _get(url)
    except urllib.error.HTTPError as e:  # 400 = family/weight doesn't exist: remember that
        if e.code == 400:
            miss.write_text(str(e))
        return None
    except Exception as e:  # network blocked / DNS / timeout
        log.info("Google Fonts unreachable (%s); using local font stacks", e)
        _offline = True
        return None
    p.write_bytes(data)
    return data


def _face_css(family: str, weight: int | None, italic: bool = False) -> str | None:
    if weight is None:  # the family's default (only) weight
        q = urllib.parse.quote_plus(family)
    else:
        axis = f"ital,wght@1,{weight}" if italic else f"wght@{weight}"
        q = urllib.parse.quote_plus(family) + ":" + axis
    url = f"https://fonts.googleapis.com/css2?family={q}&display=block"
    raw = _cached(url, ".css")
    if not raw:
        return None
    css = raw.decode("utf-8", "replace")

    def inline(m: re.Match) -> str:
        font_url = m.group(1)
        data = _cached(font_url, Path(urllib.parse.urlparse(font_url).path).suffix or ".woff2")
        if data is None:
            return m.group(0)
        mime = "font/woff2" if font_url.endswith(".woff2") else "font/ttf"
        return f"url(data:{mime};base64,{base64.b64encode(data).decode()})"

    css = re.sub(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", inline, css)
    if "fonts.gstatic.com" in css:  # some file failed to download — drop the whole face
        return None
    return css


def font_css(requests: Iterable[tuple[str, Iterable[int]]], italic_body: str | None = None) -> str:
    """Return inline @font-face CSS for (family, weights) pairs. Empty when offline."""
    out: list[str] = []
    seen = set()
    for family, weights in requests:
        if not family:
            continue
        for w in sorted({int(x) for x in weights}):
            if (family, w) in seen:
                continue
            seen.add((family, w))
            css = _face_css(family, w)
            if not css:
                # Single-weight families (Archivo Black, Bebas Neue, Anton...) reject wght@N.
                # Serve their only file under the requested weight so the browser
                # neither falls back to another family nor fakes a bold.
                base = _face_css(family, None)
                if base:
                    css = re.sub(r"font-weight:\s*\d+;", f"font-weight: {w};", base)
            if css:
                out.append(css)
    if italic_body:
        css = _face_css(italic_body, 400, italic=True)
        if css:
            out.append(css)
    return "\n".join(out)
