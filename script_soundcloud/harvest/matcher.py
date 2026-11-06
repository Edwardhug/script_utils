from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Suffixes marketing fréquents sur SoundCloud, retirés des titres.
JUNK_RE = re.compile(
    r"[\[(]\s*(?:free\s*dl|free\s*download|out\s*now|premiere|premiered|exclusive|"
    r"official\s*(?:audio|video|clip)?|clip\s*officiel|new\s*edit)\s*[\])]",
    re.IGNORECASE,
)
BRACKET_RE = re.compile(r"[\[(][^\])]*[\])]")
FEAT_RE = re.compile(r"\b(?:feat|ft|featuring)\.?\s+[^,\-|]+", re.IGNORECASE)
SEP_RE = re.compile(r"\s*[-–—|]\s*")

# Mots à ignorer dans les calculs de correspondance.
STOPWORDS = {
    "original", "mix", "edit", "remix", "vip", "intro", "extended", "club",
    "dub", "version", "instrumental", "bootleg", "mashup", "free", "dl",
    "download", "out", "now", "premiere", "premiered", "exclusive", "official",
    "audio", "video", "feat", "ft", "featuring", "with", "the",
}

FORMAT_SCORES = {
    "flac": 100.0,
    "alac": 96.0,
    "wav": 92.0,
    "aiff": 88.0,
    "aif": 88.0,
    "mp3": 72.0,
}


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_for_query(text: str | None) -> str:
    """Titre débarrassé du bruit (parenthèses, tags label, 'Free DL'…)."""
    value = JUNK_RE.sub(" ", text or "")
    value = re.sub(
        r"\|\s*(?:free\s*dl|free\s*download|out\s*now|premiere)\b.*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b(?:free\s*dl|free\s*download)\b", " ", value, flags=re.IGNORECASE)
    value = BRACKET_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" -–—|/")
    return value


def split_artist_title(uploader: str | None, title: str | None) -> tuple[str, str]:
    """Sépare au mieux artiste / titre (format 'Artiste - Titre' ou 'Artiste | Titre')."""
    uploader = (uploader or "").strip()
    title = (title or "").strip()
    cleaned = JUNK_RE.sub(" ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—|/")

    if " - " in cleaned or " | " in cleaned:
        parts = SEP_RE.split(cleaned, maxsplit=1)
        if len(parts) == 2:
            first, rest = parts[0].strip(), parts[1].strip()
            first = FEAT_RE.sub("", first).strip(" -")
            if first and rest:
                return first, rest
    return uploader, cleaned or title


def build_queries(artist: str | None, title: str | None) -> list[str]:
    split_artist, split_title = split_artist_title(artist, title)
    query_title = clean_for_query(split_title)
    queries: list[str] = []

    def add(query: str) -> None:
        query = re.sub(r"\s+", " ", query).strip()
        if query and len(query) >= 3 and query.lower() not in (q.lower() for q in queries):
            queries.append(query)

    if split_artist:
        add(f"{split_artist} {query_title}")
        if artist and normalize(artist) != normalize(split_artist):
            add(f"{artist} {query_title}")  # ex: label en uploader
    else:
        add(query_title)
    add(split_artist)
    add(query_title)
    return queries


def _tokens(text: str | None) -> set[str]:
    return {t for t in normalize(text).split() if t and t not in STOPWORDS}


def _row_get(obj, key: str, default=None):
    try:
        value = obj[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def rank_candidates(track, responses, quality_cfg, search_cfg) -> list[dict]:
    """Classe les fichiers Soulseek pour un morceau (meilleur score en premier)."""
    if isinstance(responses, dict):
        responses = responses.get("responses") or []
    responses = responses or []

    artist = _row_get(track, "artist") or ""
    title = _row_get(track, "title") or ""
    split_artist, split_title = split_artist_title(artist, title)
    query_title = clean_for_query(split_title)
    title_tokens = _tokens(query_title)
    artist_tokens = _tokens(split_artist) or _tokens(artist)

    duration = float(_row_get(track, "duration") or 0)
    preferred = {e.lower().lstrip(".") for e in quality_cfg.preferred_ext}
    tolerance = float(quality_cfg.duration_tolerance_s)

    results: list[dict] = []
    for response in responses:
        if not isinstance(response, dict):
            continue
        username = str(response.get("username") or "")
        has_slot = bool(response.get("hasFreeUploadSlot"))
        queue_length = int(response.get("queueLength") or 0)
        upload_speed = int(response.get("uploadSpeed") or 0)
        for f in response.get("files") or []:
            filename = str(f.get("filename") or "")
            if not filename or f.get("isLocked"):
                continue
            posix_name = filename.replace("\\", "/")
            ext = Path(posix_name).suffix.lower().lstrip(".")
            if ext not in preferred:
                continue
            bitrate = int(f.get("bitRate") or 0)
            if ext == "mp3" and bitrate and bitrate < int(quality_cfg.min_mp3_bitrate):
                continue
            length = float(f.get("length") or 0)
            delta = abs(length - duration) if (length and duration) else None
            if delta is not None and delta > tolerance:
                continue

            file_tokens = _tokens(Path(posix_name).stem)
            title_overlap = (
                len(title_tokens & file_tokens) / len(title_tokens) if title_tokens else 0.0
            )
            artist_match = bool(artist_tokens & file_tokens) if artist_tokens else False

            # Règles dures de correspondance du nom.
            if title_tokens:
                if title_overlap == 0:
                    continue
                if artist_tokens:
                    if not artist_match and not (title_overlap == 1.0 and len(title_tokens) >= 3):
                        continue
                else:
                    # Pas d'artiste connu : exiger la phrase complète dans le nom.
                    phrase = normalize(query_title)
                    if not phrase or phrase not in normalize(Path(posix_name).stem):
                        continue
            elif not artist_match:
                continue

            score = FORMAT_SCORES.get(ext, 50.0)
            if ext == "mp3" and not bitrate:
                score -= 8.0
            score += 30.0 * title_overlap
            if artist_match:
                score += 8.0
            if delta is not None:
                score += max(0.0, 8.0 - 2.0 * delta)
            if has_slot:
                score += 4.0
            score -= min(queue_length, 10) * 0.5
            score += min(upload_speed / 500_000.0, 3.0)

            size = int(f.get("size") or 0)
            if size > 0 and length and bitrate:
                expected = bitrate * 1000 / 8 * length
                if size < expected * 0.5:
                    score -= 15.0

            results.append(
                {
                    "username": username,
                    "filename": filename,
                    "size": size,
                    "ext": ext,
                    "bitrate": bitrate or None,
                    "bitdepth": int(f.get("bitDepth") or 0) or None,
                    "samplerate": int(f.get("sampleRate") or 0) or None,
                    "length": length or None,
                    "score": round(score, 1),
                }
            )

    results.sort(key=lambda c: c["score"], reverse=True)

    # Déduplication : même fichier (utilisateur + nom de fichier) une seule fois.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for candidate in results:
        key = (
            candidate["username"],
            candidate["filename"].replace("\\", "/").rsplit("/", 1)[-1].lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    kept = [c for c in deduped if c["score"] >= float(search_cfg.min_candidate_score)]
    return kept[: int(search_cfg.max_candidates_kept)]
