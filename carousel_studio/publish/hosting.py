"""Public image hosting: Instagram only accepts public HTTPS JPEG URLs."""
from __future__ import annotations

import io
from pathlib import Path
from typing import List

from PIL import Image

from .. import config, store
from ..config import get_settings
from ..models import CarouselDraft

SIZE = (1080, 1350)


def resolve_slide_path(draft: CarouselDraft, rendered_path: str) -> Path:
    p = Path(rendered_path)
    if p.is_absolute() and p.exists():
        return p
    for base in (store.DRAFTS_DIR / draft.id, store.DRAFTS_DIR, config.DATA_DIR, config.ROOT, Path.cwd()):
        if (base / rendered_path).exists():
            return base / rendered_path
    if p.exists():
        return p
    raise FileNotFoundError(f"Rendered slide not found: {rendered_path}")


def to_jpeg_bytes(png_path: Path) -> bytes:
    with Image.open(png_path) as im:
        im = im.convert("RGB")
        if im.size != SIZE:
            im = im.resize(SIZE, Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=95, optimize=True)
        return buf.getvalue()


def _slide_sources(draft: CarouselDraft) -> List[Path]:
    out = []
    for s in sorted(draft.slides, key=lambda s: s.index):
        if not s.rendered_path:
            raise ValueError(f"Slide {s.index} has not been rendered yet")
        out.append(resolve_slide_path(draft, s.rendered_path))
    return out


def _s3_client():
    import boto3

    s = get_settings()
    return boto3.client("s3", endpoint_url=s.s3_endpoint_url or None)


def _vercel_put(pathname: str, data: bytes) -> str:
    import os

    from vercel.blob.sync import put_blob

    # The SDK reads the token from the environment; fill it from settings (which may be a
    # proxy placeholder carrying only the store id) when it isn't set there.
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        token = get_settings().blob_token
        if token:
            os.environ["BLOB_READ_WRITE_TOKEN"] = token
    result = put_blob(
        pathname, data, access="public", content_type="image/jpeg",
        add_random_suffix=True, content_length=len(data),
    )
    return result.url


def upload_images(draft: CarouselDraft, s3_client=None, blob_put=None) -> List[str]:
    """Convert slides to JPEG, host them publicly, return URLs in slide order."""
    s = get_settings()
    sources = _slide_sources(draft)
    host = (s.image_host or "vercel").lower()
    urls: List[str] = []
    if host == "vercel":
        if not s.blob_token:
            raise RuntimeError(
                "IMAGE_HOST=vercel requires BLOB_READ_WRITE_TOKEN (Vercel → Storage → your Blob store → .env.local)"
            )
        put = blob_put or _vercel_put
        for i, src in enumerate(sources, 1):
            # Random suffix keeps re-published drafts from hitting stale CDN copies.
            urls.append(put(f"carousels/{draft.id}/slide_{i:02d}.jpg", to_jpeg_bytes(src)))
        return urls
    if host == "local":
        if not s.public_base_url:
            raise RuntimeError("IMAGE_HOST=local requires PUBLIC_BASE_URL (e.g. your tunnel URL)")
        d = store.draft_dir(draft.id)
        for i, src in enumerate(sources, 1):
            name = f"slide_{i:02d}.jpg"
            (d / name).write_bytes(to_jpeg_bytes(src))
            urls.append(f"{s.public_base_url.rstrip('/')}/drafts/{draft.id}/{name}")
        return urls
    if host == "s3":
        missing = [n for n, v in (("S3_BUCKET", s.s3_bucket), ("S3_PUBLIC_BASE_URL", s.s3_public_base_url)) if not v]
        if missing:
            raise RuntimeError("IMAGE_HOST=s3 requires " + ", ".join(missing))
        client = s3_client or _s3_client()
        for i, src in enumerate(sources, 1):
            key = f"carousels/{draft.id}/slide_{i:02d}.jpg"
            client.put_object(Bucket=s.s3_bucket, Key=key, Body=to_jpeg_bytes(src), ContentType="image/jpeg")
            urls.append(f"{s.s3_public_base_url.rstrip('/')}/{key}")
        return urls
    raise RuntimeError(f"Unknown IMAGE_HOST '{s.image_host}' (use 'vercel', 's3' or 'local')")
