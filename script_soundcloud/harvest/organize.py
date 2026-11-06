from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import mutagen
import requests

from . import matcher
from .genres import resolve_genre

USER_AGENT = "harvest/0.1 (+slskd downloader)"


def _ffprobe(path: Path) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {}
        return json.loads(result.stdout or "{}")
    except Exception:
        return {}


def _quality_label(info: dict, ext: str) -> str:
    audio = next(
        (s for s in (info.get("streams") or []) if s.get("codec_type") == "audio"), {}
    )
    fmt = info.get("format") or {}
    codec = str(audio.get("codec_name") or ext).lower()
    parts: list[str] = []

    if codec in ("flac", "alac"):
        parts.append("FLAC" if codec == "flac" else "ALAC")
        bits = audio.get("bits_per_raw_sample") or audio.get("bits_per_sample")
        rate = audio.get("sample_rate")
        if bits:
            parts.append(f"{bits}bit")
        if rate:
            parts.append(f"{int(rate) / 1000:g}kHz")
    elif codec == "mp3":
        bitrate = audio.get("bit_rate") or fmt.get("bit_rate")
        parts.append("MP3")
        if bitrate:
            parts.append(f"{round(int(bitrate) / 1000)}kbps")
    elif codec in ("pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "wav"):
        parts.append("WAV")
        bits = audio.get("bits_per_raw_sample") or audio.get("bits_per_sample")
        rate = audio.get("sample_rate")
        if bits:
            parts.append(f"{int(bits)}bit")
        if rate:
            parts.append(f"{int(rate) / 1000:g}kHz")
    else:
        parts.append(codec.upper())

    return " ".join(parts)


def _sanitize(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:180] or "Sans titre"


def _download_artwork(url: str) -> bytes | None:
    if not url:
        return None
    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        if response.status_code == 200 and response.content:
            return response.content
    except requests.RequestException:
        pass
    return None


def _write_tags(
    path: Path,
    artist: str,
    title: str,
    genre: str,
    comment: str,
    image_bytes: bytes | None,
) -> None:
    audio = mutagen.File(str(path))
    if audio is None:
        return

    if isinstance(audio, mutagen.flac.FLAC):
        audio["artist"] = artist
        audio["title"] = title
        audio["genre"] = genre
        audio["comment"] = comment
        if image_bytes:
            pic = mutagen.flac.Picture()
            pic.data = image_bytes
            pic.type = 3
            pic.mime = "image/jpeg"
            audio.clear_pictures()
            audio.add_picture(pic)
        audio.save()
        return

    from mutagen.id3 import APIC, COMM, TCON, TIT2, TPE1

    if isinstance(audio, mutagen.mp3.MP3):
        tags = audio.tags
        if tags is None:
            audio.add_tags()
            tags = audio.tags
        tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
        tags.setall("TIT2", [TIT2(encoding=3, text=title)])
        tags.setall("TCON", [TCON(encoding=3, text=genre)])
        tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=comment)])
        if image_bytes:
            tags.setall(
                "APIC",
                [APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=image_bytes)],
            )
        audio.save()
        return

    if isinstance(audio, mutagen.wave.WAVE):
        if audio.tags is None:
            audio.add_tags()
            if audio.tags is None:
                return
        tags = audio.tags
        tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
        tags.setall("TIT2", [TIT2(encoding=3, text=title)])
        tags.setall("TCON", [TCON(encoding=3, text=genre)])
        tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=comment)])
        if image_bytes:
            tags.setall(
                "APIC",
                [APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=image_bytes)],
            )
        audio.save()


def _unique_path(directory: Path, name: str) -> Path:
    target = directory / name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    index = 2
    while True:
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def organize_track(db, config, track, log) -> bool:
    staged = track["local_path"]
    if not staged:
        db.update_track(track["id"], status="FAILED", error="fichier staging manquant")
        return False
    staged_path = Path(staged)
    if not staged_path.exists():
        db.update_track(track["id"], status="FAILED", error="fichier staging introuvable")
        return False

    ext = staged_path.suffix.lower().lstrip(".")
    info = _ffprobe(staged_path)
    quality = _quality_label(info, ext)

    artist, title = matcher.split_artist_title(track["artist"], track["title"])
    artist = artist or track["artist"] or "Inconnu"
    title = title or track["title"] or "Sans titre"
    # Le genre n'est plus utilisé pour le classement, seulement pour le tag.
    genre = resolve_genre(
        track["genre"],
        track["tags"],
        config.organize.genre_map,
        config.organize.unknown_genre_folder,
    )
    comment = f"Source SoundCloud : {track['permalink'] or ''}"

    # Vérification qualité minimale : MP3 sous le seuil => échec
    if ext == "mp3":
        audio = next(
            (s for s in (info.get("streams") or []) if s.get("codec_type") == "audio"), {}
        )
        bitrate = int(audio.get("bit_rate") or (info.get("format") or {}).get("bit_rate") or 0)
        if bitrate and round(bitrate / 1000) < int(config.quality.min_mp3_bitrate):
            db.update_track(
                track["id"],
                status="FAILED",
                error=f"MP3 {round(bitrate / 1000)}kbps < {config.quality.min_mp3_bitrate}",
            )
            log(f"  ✗ qualité insuffisante : {staged_path.name}")
            return False

    image_bytes = _download_artwork(track["artwork_url"] or "")
    try:
        _write_tags(staged_path, artist, title, genre, comment, image_bytes)
    except Exception as exc:  # les tags ne doivent pas bloquer le rangement
        log(f"  ! tags ignorés ({exc})")

    filename = config.organize.filename_template.format(
        artist=artist, title=title, quality=quality, genre=genre
    )
    filename = _sanitize(filename) + staged_path.suffix.lower()
    # Bibliothèque à plat : plus de sous-dossier par genre.
    target_dir = config.music_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_path(target_dir, filename)

    # Doublon probable : même durée à 1 s près, dans toute la bibliothèque.
    dupes_dir = config.music_dir / "_Doublons"
    new_duration = float((info.get("format") or {}).get("duration") or 0)
    for existing in target_dir.rglob(f"*{staged_path.suffix.lower()}"):
        if dupes_dir in existing.parents:
            continue
        existing_info = _ffprobe(existing)
        old_duration = float((existing_info.get("format") or {}).get("duration") or 0)
        if old_duration and new_duration and abs(old_duration - new_duration) < 1.0:
            dupes_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged_path), str(_unique_path(dupes_dir, staged_path.name)))
            db.update_track(
                track["id"],
                status="ORGANIZED",
                local_path=str(existing),
                error="doublon probable",
            )
            db.log_event(track["id"], "organize", f"doublon de {existing.name}")
            log(f"  = doublon probable de {existing.name}")
            return True

    shutil.move(str(staged_path), str(target))
    db.update_track(track["id"], status="ORGANIZED", local_path=str(target), error=None)
    db.log_event(track["id"], "organize", f"rangé : {target.name}")
    log(f"  → {target.name} [{quality}]")
    return True


def organize_all(db, config, log, limit: int | None = None) -> int:
    tracks = db.get_tracks(status="DOWNLOADED")
    if limit:
        tracks = tracks[:limit]
    log(f"{len(tracks)} morceau(x) à ranger")
    done = 0
    for index, track in enumerate(tracks, 1):
        log(f"[organize {index}/{len(tracks)}] {track['artist']} - {track['title']}")
        try:
            if organize_track(db, config, track, log):
                done += 1
        except Exception as exc:
            db.update_track(track["id"], status="FAILED", error=f"organize: {exc}")
            log(f"  ✗ erreur : {exc}")
    return done
