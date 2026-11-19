"""Shared helpers for ingest: image normalisation, natural sort, ref-id checks."""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Iterable, List

from PIL import Image

from .. import store

try:  # optional HEIC support
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except Exception:  # pragma: no cover - optional dependency
    pass

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".gif", ".tif", ".tiff"}
JPEG_QUALITY = 92


def natural_key(s: str) -> list:
    """'slide2' < 'slide10' (natural / human sort order)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def is_image(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")


def _to_rgb(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def save_jpeg(im: Image.Image, dest: Path) -> Path:
    try:
        im.seek(0)  # first frame of animated formats
    except Exception:
        pass
    _to_rgb(im).save(dest, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return dest


def normalize_file(src: Path, dest: Path) -> Path:
    with Image.open(src) as im:
        return save_jpeg(im, dest)


def normalize_bytes(data: bytes, dest: Path) -> Path:
    with Image.open(io.BytesIO(data)) as im:
        return save_jpeg(im, dest)


def slide_name(i: int) -> str:
    return f"slide_{i:02d}.jpg"


def ref_exists(style: str, ref_id: str) -> bool:
    # NB: store.ref_dir() creates the directory, so check the path directly.
    return (store.style_dir(style) / "refs" / ref_id / "ref.json").exists()


def safe_id(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_") or store.new_id("ref_")


def dedupe(seq: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
