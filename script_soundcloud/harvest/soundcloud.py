from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path

import yt_dlp


def _ydl_opts(flat: bool, cookies_path: str | None = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noprogress": True,
        "extract_flat": flat,
    }
    if not flat:
        opts["noplaylist"] = True
    if cookies_path:
        opts["cookiefile"] = cookies_path
    return opts


def _best_thumbnail(info: dict) -> str:
    thumbs = info.get("thumbnails") or []
    if thumbs:
        url = thumbs[-1].get("url")
        if url:
            return str(url)
    return str(info.get("thumbnail") or "")


def _tags_to_str(info: dict) -> str:
    tags = info.get("tags") or info.get("tag_list") or []
    if isinstance(tags, str):
        return tags
    if isinstance(tags, (list, tuple)):
        return ", ".join(str(t) for t in tags if t)
    return ""


def _uploader_from_permalink(url: str) -> str:
    """Déduit l'uploader depuis https://soundcloud.com/<uploader>/<slug>."""
    try:
        path = urllib.parse.urlparse(url or "").path.strip("/")
    except Exception:
        return ""
    if not path:
        return ""
    first = path.split("/", 1)[0]
    if first in {"discover", "search", "you", "feed", "stream", "charts", "pages", "mobile"}:
        return ""
    return first


def _extract_track(track_url: str, cookies_path: str | None) -> dict | None:
    """Extraction complète (simulée) d'un morceau pour récupérer genre/tags/artwork."""
    try:
        with yt_dlp.YoutubeDL(_ydl_opts(flat=False, cookies_path=cookies_path)) as ydl:
            info = ydl.extract_info(track_url, download=False)
    except Exception:
        return None
    if not info:
        return None
    duration = info.get("duration")
    permalink = str(info.get("permalink_url") or info.get("webpage_url") or track_url)
    artist = str(info.get("uploader") or info.get("creator") or "")
    return {
        "sc_id": str(info.get("id") or ""),
        "artist": artist or _uploader_from_permalink(permalink),
        "title": str(info.get("title") or ""),
        "duration": float(duration) if duration else None,
        "genre": str(info.get("genre") or ""),
        "tags": _tags_to_str(info),
        "permalink": permalink,
        "artwork_url": _best_thumbnail(info),
        "error": "",
    }


def fetch_likes(
    url: str,
    cookies_path: str | None = None,
    limit: int | None = None,
    delay_s: float = 1.2,
    cache_dir: str | Path = "data/cache/soundcloud",
    log=print,
) -> list[dict]:
    """Liste les morceaux likés d'un utilisateur SoundCloud avec métadonnées enrichies."""
    log(f"Lecture de la page : {url}")
    try:
        with yt_dlp.YoutubeDL(_ydl_opts(flat=True, cookies_path=cookies_path)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise RuntimeError(f"Impossible de lire la page SoundCloud : {exc}") from exc

    if not info:
        raise RuntimeError("Page SoundCloud vide ou inaccessible.")

    entries = [e for e in (info.get("entries") or []) if e]
    if limit:
        entries = entries[:limit]
    log(f"{len(entries)} morceau(x) dans les likes")

    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for index, entry in enumerate(entries, 1):
        sc_id = str(entry.get("id") or "")
        if not sc_id:
            continue
        cached_file = cache / f"{sc_id}.json"
        data = None
        if cached_file.exists():
            try:
                data = json.loads(cached_file.read_text(encoding="utf-8"))
            except Exception:
                data = None
            if data is not None and data.get("error"):
                data = None  # on retente l'extraction complète

        if data is None:
            track_url = entry.get("url") or entry.get("webpage_url")
            if not track_url:
                track_url = f"https://api.soundcloud.com/tracks/{sc_id}"
            data = _extract_track(track_url, cookies_path)
            if data is None:
                duration = entry.get("duration")
                permalink = str(track_url)
                data = {
                    "sc_id": sc_id,
                    "artist": str(entry.get("uploader") or "")
                    or _uploader_from_permalink(permalink),
                    "title": str(entry.get("title") or ""),
                    "duration": float(duration) if duration else None,
                    "genre": "",
                    "tags": "",
                    "permalink": permalink,
                    "artwork_url": _best_thumbnail(entry),
                    "error": "extraction complète impossible",
                }
            if not data.get("error"):
                cached_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            time.sleep(delay_s)

        artist = data.get("artist") or "?"
        title = data.get("title") or "?"
        log(f"[{index}/{len(entries)}] {artist} - {title}")
        results.append(data)

    return results
