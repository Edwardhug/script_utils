from __future__ import annotations

import time
from pathlib import Path

import yt_dlp

from .db import Database


def download_track(
    track,
    config,
    cookies_path: str | None = None,
    bitrate: int = 320,
    log=print,
) -> Path | None:
    """Télécharge la version SoundCloud d'origine d'un morceau, convertie en MP3."""
    permalink = track["permalink"]
    if not permalink:
        log("  ! permalien SoundCloud manquant")
        return None

    staging = config.staging_dir
    staging.mkdir(parents=True, exist_ok=True)
    sc_id = track["sc_id"] or str(track["id"])

    options = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": str(staging / f"sc_{sc_id}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(bitrate),
            }
        ],
        "overwrites": True,
    }
    if cookies_path:
        options["cookiefile"] = cookies_path

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([permalink])
    except Exception as exc:
        log(f"  ! échec SoundCloud : {exc}")
        return None

    target = staging / f"sc_{sc_id}.mp3"
    if not target.exists():
        matches = sorted(staging.glob(f"sc_{sc_id}.*"))
        if not matches:
            log("  ! fichier SoundCloud introuvable après téléchargement")
            return None
        target = matches[0]
    return target


def fallback_all(
    db: Database,
    config,
    log,
    limit: int | None = None,
    cookies_path: str | None = None,
    bitrate: int = 320,
) -> int:
    """Récupère depuis SoundCloud tous les morceaux non téléchargés."""
    tracks = db.tracks_not_downloaded()
    if limit:
        tracks = tracks[:limit]
    log(f"{len(tracks)} morceau(x) non téléchargé(s) à récupérer depuis SoundCloud")
    done = 0
    for index, track in enumerate(tracks, 1):
        log(f"[fallback {index}/{len(tracks)}] {track['artist']} - {track['title']}")
        target = download_track(
            track, config, cookies_path=cookies_path, bitrate=bitrate, log=log
        )
        if target is None:
            # On conserve le statut d'origine (NEW/SEARCHED/QUEUED/FAILED) pour
            # permettre une nouvelle tentative Soulseek au prochain passage.
            db.update_track(track["id"], error="fallback SoundCloud impossible")
            db.log_event(track["id"], "fallback", "échec du téléchargement SoundCloud")
            continue
        db.update_track(track["id"], status="DOWNLOADED", local_path=str(target), error=None)
        db.log_event(track["id"], "fallback", f"récupéré depuis SoundCloud : {target.name}")
        log(f"  ✓ {target.name}")
        done += 1
        time.sleep(1.0)
    return done
