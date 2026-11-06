from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from . import matcher
from .slskd_client import SlskdClient, SlskdError

SUCCESS_STATES = {"completed", "succeeded"}
FAILURE_STATES = {"errored", "cancelled", "rejected", "timedout", "aborted", "failed"}


def flatten_downloads(data) -> list[tuple[str, dict]]:
    """Normalise la réponse de GET /api/v0/transfers/downloads en (username, file)."""
    if isinstance(data, dict):
        entries = list(data.values())
    else:
        entries = data or []
    items: list[tuple[str, dict]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        username = str(entry.get("username") or "")
        for directory in entry.get("directories") or []:
            for f in directory.get("files") or []:
                f = dict(f)
                items.append((username or str(f.get("username") or ""), f))
    return items


def _basename(filename: str) -> str:
    return filename.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _match_transfer(downloads: list[tuple[str, dict]], candidate) -> dict | None:
    wanted = _basename(candidate["filename"])
    for username, f in downloads:
        if username != candidate["username"]:
            continue
        if _basename(str(f.get("filename") or "")) == wanted:
            return f
    return None


def _transfer_states(transfer: dict | None) -> set[str]:
    """slskd renvoie des états composés, ex: 'Completed, TimedOut'."""
    raw = str((transfer or {}).get("state") or "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _online(client: SlskdClient) -> bool:
    try:
        return client.is_logged_in()
    except SlskdError:
        return False


def _ensure_online(client: SlskdClient, config, log) -> bool:
    """Vrai si slskd est connecté au réseau ; sinon attend la reconnexion."""
    if _online(client):
        return True
    log("  slskd déconnecté — attente de reconnexion…")
    return client.wait_for_login(
        timeout_s=int(config.slskd.wait_timeout_s), poll_s=5.0, log=log
    )


# --------------------------------------------------------------------- search
def search_track(db, client: SlskdClient, config, track, log) -> int:
    """Retourne le nombre de candidats ; 0 si aucun ; -1 si slskd déconnecté."""
    queries = matcher.build_queries(track["artist"], track["title"])
    for query in queries:
        search_id = client.start_search(query)
        log(f"    recherche Soulseek : {query!r} (id {search_id})")
        responses = client.wait_for_search(search_id, config.search.wait_timeout_s)
        if not _online(client):
            db.update_track(track["id"], error="slskd déconnecté pendant la recherche")
            db.log_event(track["id"], "search", "recherche interrompue (slskd déconnecté)")
            return -1
        candidates = matcher.rank_candidates(track, responses, config.quality, config.search)
        client.delete_search(search_id)
        if candidates:
            for candidate in candidates:
                db.add_candidate(track["id"], candidate)
            db.update_track(track["id"], status="SEARCHED", error=None)
            db.log_event(
                track["id"], "search", f"{len(candidates)} candidat(s) via {query!r}"
            )
            return len(candidates)
        log("    aucun résultat, requête suivante…")
    if not _online(client):
        db.update_track(track["id"], error="slskd déconnecté pendant la recherche")
        return -1
    db.update_track(track["id"], status="FAILED", error="aucun résultat Soulseek")
    db.log_event(track["id"], "search", "aucun candidat")
    return 0


def search_all(db, client: SlskdClient, config, log, limit: int | None = None) -> int:
    tracks = db.tracks_needing_search()
    if limit:
        tracks = tracks[:limit]
    log(f"{len(tracks)} morceau(x) à rechercher")
    if not tracks:
        return 0
    if not _ensure_online(client, config, log):
        log("  slskd indisponible, recherche annulée (l'état est conservé)")
        return 0

    processed = 0
    index = 0
    while index < len(tracks):
        track = tracks[index]
        log(f"[search {index + 1}/{len(tracks)}] {track['artist']} - {track['title']}")
        try:
            result = search_track(db, client, config, track, log)
        except SlskdError as exc:
            log(f"  slskd : {exc}")
            if not _ensure_online(client, config, log):
                log("  arrêt : slskd indisponible (morceaux en attente conservés)")
                break
            continue  # on retente le même morceau
        if result == -1:
            if not _ensure_online(client, config, log):
                log("  arrêt : slskd indisponible (morceaux en attente conservés)")
                break
            continue  # on retente le même morceau
        processed += 1
        index += 1
        time.sleep(float(config.search.interval_s))
    return processed


# ------------------------------------------------------------------- download
def _enqueue(db, client: SlskdClient, config, track, candidate, log) -> None:
    files = [{"filename": candidate["filename"], "size": candidate["size"]}]
    client.enqueue_download(candidate["username"], files)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.update_candidate(candidate["id"], status="QUEUED", queued_at=now)
    db.update_track(track["id"], status="QUEUED", error=None)
    db.log_event(
        track["id"], "download", f"enqueue {candidate['username']} :: {candidate['filename']}"
    )
    log(
        f"  → enqueue {candidate['username']} | "
        f"{Path(candidate['filename'].replace(chr(92), '/')).name} "
        f"[{candidate['ext']}] score {candidate['score']}"
    )


def _locate_downloaded(downloads_dir: Path, basename: str) -> Path | None:
    lowered = basename.lower()
    candidates = []
    for path in downloads_dir.rglob("*"):
        if path.is_file() and path.name.lower() == lowered:
            candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


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


def _finalize(db, config, track, candidate, log) -> bool:
    basename = Path(candidate["filename"].replace("\\", "/")).name
    source = _locate_downloaded(config.downloads_dir, basename)
    if source is None:
        db.update_track(track["id"], error=f"fichier introuvable : {basename}")
        return False
    config.staging_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_path(config.staging_dir, basename)
    shutil.move(str(source), str(destination))
    db.update_candidate(candidate["id"], status="COMPLETED")
    db.update_track(
        track["id"], status="DOWNLOADED", local_path=str(destination), error=None
    )
    db.log_event(track["id"], "download", f"terminé : {destination.name}")
    log(f"  ✓ téléchargé : {destination.name}")
    return True


def _fail_candidate(
    db, client, config, track, candidate, reason, log, transfer: dict | None = None
) -> None:
    if transfer is not None and transfer.get("id"):
        client.cancel_download(candidate["username"], str(transfer["id"]))
    db.update_candidate(candidate["id"], status="FAILED")
    remaining = db.get_candidates(track["id"], status="NEW")
    attempts = int(track["attempts"] or 0) + 1
    if remaining and attempts < int(config.download.max_candidate_tries):
        db.update_track(track["id"], status="SEARCHED", attempts=attempts, error=reason)
    else:
        db.update_track(track["id"], status="FAILED", attempts=attempts, error=reason)
    db.log_event(track["id"], "download", f"échec candidat ({reason})")
    log(f"  ✗ échec ({reason}) — candidat suivant")


def _active_entry(candidate) -> dict:
    now = time.monotonic()
    return {
        "candidate": candidate,
        "started": now,
        "last_change": now,
        "signature": None,
    }


def _bootstrap_active(db, client, config, log) -> dict:
    """Récupère les téléchargements en cours après une interruption."""
    active: dict[int, dict] = {}
    pairs = db.get_queued_pairs()
    if not pairs:
        return active
    log(f"{len(pairs)} téléchargement(s) en cours récupéré(s)")
    try:
        downloads = flatten_downloads(client.downloads())
    except SlskdError:
        downloads = []
    for track, candidate in pairs:
        transfer = _match_transfer(downloads, candidate)
        states = _transfer_states(transfer)
        if "succeeded" in states:
            _finalize(db, config, track, candidate, log)
        elif transfer is not None:
            if states & FAILURE_STATES:
                db.update_candidate(candidate["id"], status="FAILED")
                db.update_track(track["id"], status="SEARCHED", error=", ".join(states))
            else:
                active[track["id"]] = _active_entry(candidate)
        else:
            # Transfert perdu : on reprendra avec le même candidat.
            db.update_candidate(candidate["id"], status="NEW")
            db.update_track(track["id"], status="SEARCHED")
    return active


def download_all(
    db, client: SlskdClient, config, log, limit: int | None = None, max_active: int | None = None
) -> None:
    max_active = int(max_active or config.download.max_active)
    if not _ensure_online(client, config, log):
        log("slskd indisponible, téléchargement annulé (l'état est conservé)")
        return

    active = _bootstrap_active(db, client, config, log)
    started = 0

    while True:
        while len(active) < max_active:
            if limit and started >= limit:
                break
            track = db.next_track_with_candidates()
            if track is None:
                break
            candidates = db.get_candidates(track["id"], status="NEW")
            if not candidates:
                continue
            candidate = candidates[0]
            try:
                _enqueue(db, client, config, track, candidate, log)
                active[track["id"]] = _active_entry(candidate)
                started += 1
            except SlskdError as exc:
                if not _ensure_online(client, config, log):
                    log("  slskd indisponible, arrêt des mises en file")
                    break
                # slskd répond : le candidat lui-même est en cause (peer hors ligne…).
                log(f"  candidat inutilisable ({exc})")
                db.update_candidate(candidate["id"], status="FAILED")
                remaining = db.get_candidates(track["id"], status="NEW")
                db.update_track(
                    track["id"],
                    status="SEARCHED" if remaining else "FAILED",
                    error=str(exc),
                )
                continue

        if not active:
            if limit and started >= limit:
                break
            if db.next_track_with_candidates() is None:
                break

        time.sleep(int(config.download.poll_interval_s))
        try:
            downloads = flatten_downloads(client.downloads())
        except SlskdError as exc:
            log(f"  slskd injoignable ({exc}) — attente…")
            if not _ensure_online(client, config, log):
                log("  arrêt : slskd indisponible (reprise possible avec ./run.sh)")
                break
            continue

        for track_id in list(active.keys()):
            track = db.get_track(track_id)
            entry = active[track_id]
            candidate = entry["candidate"]
            if track is None:
                active.pop(track_id, None)
                continue
            transfer = _match_transfer(downloads, candidate)
            states = _transfer_states(transfer)

            signature = None
            if transfer is not None:
                signature = "{}:{}:{}".format(
                    transfer.get("state") or "",
                    transfer.get("bytesTransferred") or 0,
                    transfer.get("percentComplete") or 0,
                )
            if signature != entry["signature"]:
                entry["signature"] = signature
                entry["last_change"] = time.monotonic()

            if "succeeded" in states:
                if _finalize(db, config, track, candidate, log):
                    active.pop(track_id, None)
            elif states & FAILURE_STATES:
                active.pop(track_id, None)
                _fail_candidate(
                    db, client, config, track, candidate, ", ".join(states), log, transfer
                )
            elif time.monotonic() - entry["last_change"] > int(
                config.download.track_timeout_s
            ):
                active.pop(track_id, None)
                _fail_candidate(db, client, config, track, candidate, "timeout", log, transfer)
