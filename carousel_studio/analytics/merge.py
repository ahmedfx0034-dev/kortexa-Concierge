"""Blend two style profiles into a new one."""
from __future__ import annotations

from typing import Dict, Optional

from .. import store
from ..models import StyleProfile

DEFAULT_TAKE = {"palette": "a", "decorations": "a", "typography": "b", "archetypes": "b", "voice": "a"}
VOICE_FIELDS = ("tone", "hook_patterns", "caption_style", "words_per_slide", "slide_count")


def merge_styles(a: str, b: str, name: str, take: Optional[Dict[str, str]] = None) -> StyleProfile:
    take = {**DEFAULT_TAKE, **(take or {})}
    bad = {k: v for k, v in take.items() if k not in DEFAULT_TAKE or v not in ("a", "b")}
    if bad:
        raise ValueError(f"Invalid 'take' entries {bad}; parts are {sorted(DEFAULT_TAKE)} and sources are 'a' or 'b'")
    pa, pb = store.load_profile(a), store.load_profile(b)
    src = {"a": pa, "b": pb}
    voice = src[take["voice"]]
    merged = StyleProfile(
        name=name,
        summary="",
        palette=src[take["palette"]].palette.model_copy(deep=True),
        typography=src[take["typography"]].typography.model_copy(deep=True),
        archetypes=[x.model_copy(deep=True) for x in src[take["archetypes"]].archetypes],
        decorations=list(src[take["decorations"]].decorations),
        uses_photos=src[take["archetypes"]].uses_photos,
        words_per_slide=voice.words_per_slide,
        slide_count=voice.slide_count,
        hook_patterns=list(voice.hook_patterns),
        tone=voice.tone,
        caption_style=voice.caption_style,
        reference_ids=sorted(set(pa.reference_ids) | set(pb.reference_ids)),
    )
    choice = ", ".join(f"{part} from {pa.name if take[part] == 'a' else pb.name}"
                       for part in ("palette", "typography", "archetypes", "decorations", "voice"))
    merged.summary = (f"A blend of '{pa.name}' and '{pb.name}' ({choice}). "
                      f"Voice: {voice.tone}.")
    store.save_profile(merged)
    return merged
