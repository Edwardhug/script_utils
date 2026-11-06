from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

from . import __version__, downloader, organize as organizer, soundcloud, soundcloud_dl
from .config import DEFAULT_CONFIG_PATH, load_config
from .db import Database
from .slskd_client import SlskdClient, SlskdError

console = Console()


def make_client(config) -> SlskdClient:
    if not config.slskd.api_key:
        console.print(
            "[red]Clé API slskd manquante.[/red] Renseigne slskd.api_key dans config.yaml "
            "(interface slskd → System → API Keys, rôle readwrite)."
        )
        sys.exit(1)
    client = SlskdClient(config.slskd.url, config.slskd.api_key)
    try:
        state = client.server_state()
    except SlskdError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    if not state.get("isLoggedIn"):
        console.print(
            "[yellow]slskd n'est pas connecté à Soulseek.[/yellow] "
            "Vérifie les identifiants dans l'interface http://localhost:5030"
        )
    return client


def cmd_fetch(args, config, db) -> None:
    url = args.url or config.soundcloud.likes_url
    if not url:
        console.print("[red]Aucune URL fournie.[/red]")
        sys.exit(1)
    tracks = soundcloud.fetch_likes(
        url,
        cookies_path=args.cookies,
        limit=args.limit,
        delay_s=config.soundcloud.delay_s,
        cache_dir=config.cache_dir,
        log=console.print,
    )
    created = 0
    updated = 0
    for track in tracks:
        is_new = not db.track_exists(track["sc_id"])
        db.upsert_track({**track, "source": url})
        if is_new:
            created += 1
        else:
            updated += 1
    console.print(
        f"[green]{created} nouveau(x)[/green], {updated} mis à jour, {len(tracks)} au total"
    )


def cmd_search(args, config, db) -> None:
    client = make_client(config)
    downloader.search_all(db, client, config, console.print, limit=args.limit)


def cmd_download(args, config, db) -> None:
    client = make_client(config)
    downloader.download_all(
        db, client, config, console.print, limit=args.limit, max_active=args.max_active
    )


def cmd_organize(args, config, db) -> None:
    organizer.organize_all(db, config, console.print, limit=args.limit)


def cmd_run(args, config, db) -> None:
    try:
        cmd_fetch(args, config, db)
        try:
            client = make_client(config)
            downloader.search_all(db, client, config, console.print)
            downloader.download_all(db, client, config, console.print)
        except SystemExit:
            console.print(
                "[yellow]Soulseek indisponible — passage au fallback SoundCloud.[/yellow]"
            )
        except Exception as exc:
            console.print(
                f"[yellow]Étape Soulseek interrompue ({exc}) — "
                "passage au fallback SoundCloud.[/yellow]"
            )
        # Fallback pour TOUS les morceaux non téléchargés, quel que soit leur statut.
        soundcloud_dl.fallback_all(
            db, config, console.print, cookies_path=args.cookies
        )
    finally:
        # Toujours ranger les fichiers déjà téléchargés, même si une étape a échoué
        # (slskd tombé, Ctrl-C…) : sinon les fichiers restent bloqués dans data/staging.
        organizer.organize_all(db, config, console.print)


def cmd_fallback(args, config, db) -> None:
    count = soundcloud_dl.fallback_all(
        db, config, console.print, limit=args.limit, cookies_path=args.cookies
    )
    console.print(f"[green]{count} morceau(x) récupérés depuis SoundCloud[/green]")


def cmd_status(args, config, db) -> None:
    counts = db.count_by_status()
    summary = Table(title="Statuts")
    summary.add_column("Statut")
    summary.add_column("Nombre", justify="right")
    for status, count in counts.items():
        summary.add_row(status, str(count))
    console.print(summary)

    tracks = db.get_tracks()
    tracks = sorted(tracks, key=lambda t: t["updated_at"] or "", reverse=True)[: args.limit]
    table = Table(title=f"{len(tracks)} derniers morceaux")
    table.add_column("id", justify="right")
    table.add_column("Artiste")
    table.add_column("Titre", max_width=40)
    table.add_column("Statut")
    table.add_column("Genre")
    table.add_column("Erreur", max_width=30)
    for track in tracks:
        table.add_row(
            str(track["id"]),
            track["artist"] or "?",
            track["title"] or "?",
            track["status"] or "?",
            track["genre"] or "",
            track["error"] or "",
        )
    console.print(table)


def cmd_retry(args, config, db) -> None:
    count = db.reset_failed()
    console.print(f"[green]{count} morceau(x) remis en file[/green]")


def cmd_report(args, config, db) -> None:
    import csv
    from datetime import datetime

    path = config.reports_dir / f"rapport_{datetime.now():%Y%m%d_%H%M}.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            [
                "id",
                "artiste",
                "titre",
                "duree_s",
                "genre_sc",
                "statut",
                "format",
                "bitrate",
                "chemin",
                "erreur",
            ]
        )
        for track in db.get_tracks():
            chosen = None
            for candidate in db.get_candidates(track["id"]):
                if candidate["status"] == "COMPLETED":
                    chosen = candidate
                    break
            writer.writerow(
                [
                    track["id"],
                    track["artist"] or "",
                    track["title"] or "",
                    track["duration"] or "",
                    track["genre"] or "",
                    track["status"] or "",
                    chosen["ext"] if chosen else "",
                    chosen["bitrate"] if chosen else "",
                    track["local_path"] or "",
                    track["error"] or "",
                ]
            )
    console.print(f"[green]Rapport écrit : {path}[/green]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harvest", description="SoundCloud → Soulseek → DJ")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--version", action="version", version=f"harvest {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="Extrait les likes SoundCloud vers la base")
    fetch.add_argument("url", nargs="?", default=None)
    fetch.add_argument("--limit", type=int, default=None)
    fetch.add_argument("--cookies", default=None)
    fetch.set_defaults(func=cmd_fetch)

    search = sub.add_parser("search", help="Cherche les morceaux sur Soulseek")
    search.add_argument("--limit", type=int, default=None)
    search.set_defaults(func=cmd_search)

    download = sub.add_parser("download", help="Télécharge les meilleurs candidats")
    download.add_argument("--limit", type=int, default=None)
    download.add_argument("--max-active", type=int, default=None)
    download.set_defaults(func=cmd_download)

    organize = sub.add_parser("organize", help="Tague et range dans la bibliothèque")
    organize.add_argument("--limit", type=int, default=None)
    organize.set_defaults(func=cmd_organize)

    fallback = sub.add_parser(
        "fallback", help="Récupère les introuvables depuis SoundCloud (MP3)"
    )
    fallback.add_argument("--limit", type=int, default=None)
    fallback.add_argument("--cookies", default=None)
    fallback.set_defaults(func=cmd_fallback)

    run = sub.add_parser("run", help="fetch + search + download + organize")
    run.add_argument("url", nargs="?", default=None)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--cookies", default=None)
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="État des morceaux")
    status.add_argument("--limit", type=int, default=30)
    status.set_defaults(func=cmd_status)

    retry = sub.add_parser("retry", help="Remet les échecs en file")
    retry.set_defaults(func=cmd_retry)

    report = sub.add_parser("report", help="Génère un rapport CSV")
    report.set_defaults(func=cmd_report)

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    config.ensure_dirs()
    db = Database(config.db_path)
    try:
        args.func(args, config, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
