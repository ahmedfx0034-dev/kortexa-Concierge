"""One thin wrapper around the Claude API used by every module.

`ask_json(prompt, Model, images=[...])` returns a validated pydantic instance.
Uses structured outputs, adaptive thinking, streaming (long outputs) and the
server-side refusal fallback.
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Iterable, Type, TypeVar

import anthropic
from anthropic import transform_schema
from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def image_block(path: str | Path, max_side: int = 1568) -> dict:
    """Base64 image content block, downscaled so we don't send huge files."""
    from io import BytesIO

    from PIL import Image

    path = Path(path)
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=88)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


class ClaudeRefused(RuntimeError):
    pass


def ask_json(
    prompt: str,
    schema: Type[T],
    *,
    system: str | None = None,
    images: Iterable[str | Path] = (),
    max_tokens: int = 32000,
) -> T:
    s = get_settings()
    content: list[dict] = [image_block(p) for p in images]
    content.append({"type": "text", "text": prompt})
    kwargs = dict(
        model=s.model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={
            "effort": s.effort,
            "format": {"type": "json_schema", "schema": transform_schema(schema)},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
    )
    if system:
        kwargs["system"] = system
    with client().beta.messages.stream(**kwargs) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise ClaudeRefused(getattr(msg, "stop_details", None) or "Claude declined this request")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Claude ran out of output tokens; raise max_tokens")
    text = "".join(b.text for b in msg.content if b.type == "text")
    return schema.model_validate_json(text)
