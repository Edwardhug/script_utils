from __future__ import annotations

from .matcher import normalize


def resolve_genre(
    genre: str | None,
    tags: str | None,
    genre_map: dict,
    unknown_folder: str,
) -> str:
    """Détermine le dossier de genre à partir du genre SoundCloud et des tags."""
    if not genre_map:
        return unknown_folder
    haystack = normalize(" ".join(x for x in [genre or "", tags or ""] if x))
    if not haystack:
        return unknown_folder
    compact_haystack = haystack.replace(" ", "")
    for key in sorted(genre_map, key=len, reverse=True):
        normalized_key = normalize(key)
        if not normalized_key:
            continue
        if normalized_key in haystack or normalized_key.replace(" ", "") in compact_haystack:
            return str(genre_map[key])
    return unknown_folder
