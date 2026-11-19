"""Ingest reference carousels from a folder of screenshots."""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import List

from .. import store
from ..models import ReferenceCarousel, ReferenceSource
from .common import is_image, natural_key, normalize_file, ref_exists, slide_name

log = logging.getLogger(__name__)


def _images_in(folder: Path) -> List[Path]:
    return sorted((p for p in folder.iterdir() if is_image(p)), key=lambda p: natural_key(p.name))


def _content_id(images: List[Path]) -> str:
    """Stable id from file contents so re-ingesting the same folder is a no-op."""
    h = hashlib.sha1()
    for p in images:
        h.update(p.read_bytes())
    return "ref_" + h.hexdigest()[:10]


def _ingest_group(style: str, images: List[Path], origin: Path) -> ReferenceCarousel | None:
    ref_id = _content_id(images)
    if ref_exists(style, ref_id):
        log.info("Skipping %s: already ingested as %s", origin, ref_id)
        return None
    dest = store.ref_dir(style, ref_id)
    paths: List[str] = []
    try:
        for p in images:
            try:
                out = normalize_file(p, dest / slide_name(len(paths) + 1))
                paths.append(str(out))
            except Exception as e:  # unreadable / unsupported (e.g. HEIC without plugin)
                log.warning("Skipping unreadable image %s: %s", p, e)
        if not paths:
            raise ValueError("no readable images")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        log.warning("No readable images in %s", origin)
        return None
    ref = ReferenceCarousel(
        id=ref_id, source=ReferenceSource.local, origin=str(origin), slide_paths=paths
    )
    store.save_reference(style, ref)
    return ref


def ingest_local(style: str, folder: str) -> List[ReferenceCarousel]:
    """Ingest a folder of screenshots.

    Subfolders -> one carousel each (images in natural filename order).
    Only loose images -> the whole folder is one carousel.
    Already-ingested carousels (same image contents) are skipped.
    """
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Not a folder: {folder}")

    subdirs = sorted(
        (d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")),
        key=lambda d: natural_key(d.name),
    )
    groups = [(d, _images_in(d)) for d in subdirs]
    groups = [(d, imgs) for d, imgs in groups if imgs]
    if not groups:
        loose = _images_in(root)
        if not loose:
            raise ValueError(f"No images found in {folder} (accepted: jpg, jpeg, png, webp, heic)")
        groups = [(root, loose)]
    elif _images_in(root):
        log.warning("Ignoring loose images in %s because it has carousel subfolders", root)

    refs = []
    for origin, imgs in groups:
        ref = _ingest_group(style, imgs, origin)
        if ref:
            refs.append(ref)
    return refs
