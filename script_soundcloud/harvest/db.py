from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    source TEXT,
    sc_id TEXT UNIQUE,
    artist TEXT,
    title TEXT,
    duration REAL,
    genre TEXT,
    tags TEXT,
    permalink TEXT,
    artwork_url TEXT,
    status TEXT DEFAULT 'NEW',
    attempts INTEGER DEFAULT 0,
    local_path TEXT,
    error TEXT,
    added_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    track_id INTEGER NOT NULL,
    username TEXT,
    filename TEXT,
    size INTEGER,
    ext TEXT,
    bitrate INTEGER,
    bitdepth INTEGER,
    samplerate INTEGER,
    length REAL,
    score REAL,
    status TEXT DEFAULT 'NEW',
    queued_at TEXT,
    created_at TEXT,
    FOREIGN KEY(track_id) REFERENCES tracks(id)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT,
    track_id INTEGER,
    kind TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
CREATE INDEX IF NOT EXISTS idx_candidates_track ON candidates(track_id, status);
CREATE INDEX IF NOT EXISTS idx_events_track ON events(track_id);
"""

TRACK_FIELDS = (
    "source",
    "sc_id",
    "artist",
    "title",
    "duration",
    "genre",
    "tags",
    "permalink",
    "artwork_url",
    "status",
    "attempts",
    "local_path",
    "error",
)

CANDIDATE_FIELDS = (
    "username",
    "filename",
    "size",
    "ext",
    "bitrate",
    "bitdepth",
    "samplerate",
    "length",
    "score",
    "status",
    "queued_at",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ tracks
    def track_exists(self, sc_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM tracks WHERE sc_id = ?", (str(sc_id),)).fetchone()
        return row is not None

    def upsert_track(self, data: dict[str, Any]) -> int:
        sc_id = str(data.get("sc_id") or "")
        if not sc_id:
            raise ValueError("upsert_track: sc_id requis")
        row = self.conn.execute("SELECT id FROM tracks WHERE sc_id = ?", (sc_id,)).fetchone()
        now = utcnow()
        if row:
            values = {k: data[k] for k in TRACK_FIELDS if k in data}
            values["updated_at"] = now
            assignments = ", ".join(f"{k} = ?" for k in values)
            self.conn.execute(
                f"UPDATE tracks SET {assignments} WHERE id = ?",
                (*values.values(), row["id"]),
            )
            self.conn.commit()
            return int(row["id"])

        values = {k: data.get(k) for k in TRACK_FIELDS}
        values["sc_id"] = sc_id
        values["status"] = data.get("status") or "NEW"
        values["attempts"] = int(data.get("attempts") or 0)
        values["added_at"] = now
        values["updated_at"] = now
        columns = ", ".join(values)
        placeholders = ", ".join("?" * len(values))
        cur = self.conn.execute(
            f"INSERT INTO tracks ({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_track(self, track_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()

    def get_tracks(
        self,
        status: str | Sequence[str] | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM tracks"
        conds: list[str] = []
        params: list[Any] = []
        if status:
            if isinstance(status, str):
                conds.append("status = ?")
                params.append(status)
            else:
                placeholders = ", ".join("?" * len(status))
                conds.append(f"status IN ({placeholders})")
                params.extend(status)
        if source:
            conds.append("source = ?")
            params.append(source)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        return list(self.conn.execute(sql, params))

    def update_track(self, track_id: int, **fields: Any) -> None:
        values = {k: v for k, v in fields.items() if k in TRACK_FIELDS}
        if not values:
            return
        values["updated_at"] = utcnow()
        assignments = ", ".join(f"{k} = ?" for k in values)
        self.conn.execute(
            f"UPDATE tracks SET {assignments} WHERE id = ?",
            (*values.values(), track_id),
        )
        self.conn.commit()

    def count_by_status(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM tracks GROUP BY status ORDER BY status"
        )
        return {row["status"] or "?": row["n"] for row in rows}

    # -------------------------------------------------------------- candidates
    def add_candidate(self, track_id: int, data: dict[str, Any]) -> int:
        values = {k: data.get(k) for k in CANDIDATE_FIELDS}
        values["track_id"] = track_id
        values["status"] = data.get("status") or "NEW"
        values["created_at"] = utcnow()
        columns = ", ".join(values)
        placeholders = ", ".join("?" * len(values))
        cur = self.conn.execute(
            f"INSERT INTO candidates ({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_candidates(
        self, track_id: int, status: str | Sequence[str] | None = None
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM candidates WHERE track_id = ?"
        params: list[Any] = [track_id]
        if status:
            if isinstance(status, str):
                sql += " AND status = ?"
                params.append(status)
            else:
                placeholders = ", ".join("?" * len(status))
                sql += f" AND status IN ({placeholders})"
                params.extend(status)
        sql += " ORDER BY score DESC, id"
        return list(self.conn.execute(sql, params))

    def update_candidate(self, candidate_id: int, **fields: Any) -> None:
        values = {k: v for k, v in fields.items() if k in CANDIDATE_FIELDS}
        if not values:
            return
        assignments = ", ".join(f"{k} = ?" for k in values)
        self.conn.execute(
            f"UPDATE candidates SET {assignments} WHERE id = ?",
            (*values.values(), candidate_id),
        )
        self.conn.commit()

    def next_track_with_candidates(self) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT t.* FROM tracks t
            WHERE t.status = 'SEARCHED'
              AND EXISTS (
                  SELECT 1 FROM candidates c
                  WHERE c.track_id = t.id AND c.status = 'NEW'
              )
            ORDER BY t.id
            LIMIT 1
            """
        ).fetchone()

    def tracks_needing_search(self) -> list[sqlite3.Row]:
        """Nouveaux morceaux + ceux dont tous les candidats ont été consommés."""
        return list(
            self.conn.execute(
                """
                SELECT * FROM tracks t
                WHERE t.status = 'NEW'
                   OR (
                       t.status = 'SEARCHED'
                       AND NOT EXISTS (
                           SELECT 1 FROM candidates c
                           WHERE c.track_id = t.id AND c.status = 'NEW'
                       )
                   )
                ORDER BY t.id
                """
            )
        )

    def tracks_not_downloaded(self) -> list[sqlite3.Row]:
        """Tous les morceaux ni téléchargés ni rangés, quel que soit leur statut."""
        return list(
            self.conn.execute(
                """
                SELECT * FROM tracks t
                WHERE COALESCE(t.status, 'NEW') NOT IN ('DOWNLOADED', 'ORGANIZED')
                ORDER BY CASE COALESCE(t.status, 'NEW')
                             WHEN 'FAILED' THEN 0
                             WHEN 'SEARCHED' THEN 1
                             WHEN 'NEW' THEN 2
                             WHEN 'QUEUED' THEN 3
                             ELSE 4
                         END,
                         t.id
                """
            )
        )

    def get_queued_pairs(self) -> list[tuple[sqlite3.Row, sqlite3.Row]]:
        """Tracks en cours (status QUEUED) avec leur candidat en cours."""
        rows = self.conn.execute(
            """
            SELECT t.id AS track_id, t.status AS track_status,
                   c.id AS candidate_id, c.username, c.filename, c.size,
                   c.queued_at
            FROM tracks t
            JOIN candidates c ON c.track_id = t.id AND c.status = 'QUEUED'
            WHERE t.status = 'QUEUED'
            """
        ).fetchall()
        pairs = []
        for row in rows:
            track = self.get_track(row["track_id"])
            candidate = self.conn.execute(
                "SELECT * FROM candidates WHERE id = ?", (row["candidate_id"],)
            ).fetchone()
            if track and candidate:
                pairs.append((track, candidate))
        return pairs

    def reset_failed(self) -> int:
        """Remet les tracks FAILED en circulation, candidats restants inclus."""
        tracks = self.get_tracks(status="FAILED")
        for track in tracks:
            candidates = self.get_candidates(track["id"], status=["NEW", "FAILED", "QUEUED"])
            for candidate in candidates:
                self.update_candidate(candidate["id"], status="NEW")
            if candidates:
                self.update_track(track["id"], status="SEARCHED", error=None)
            else:
                self.update_track(track["id"], status="NEW", error=None)
        return len(tracks)

    # ------------------------------------------------------------------ events
    def log_event(self, track_id: int | None, kind: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO events (ts, track_id, kind, message) VALUES (?, ?, ?, ?)",
            (utcnow(), track_id, kind, message),
        )
        self.conn.commit()
