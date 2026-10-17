import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .models import Observation, now_iso


class Store:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "screenshots").mkdir(exist_ok=True)
        temporary = self.directory / "inference-temp"
        temporary.mkdir(exist_ok=True)
        # This folder is owned exclusively by the recorder, under the application lock.
        for path in temporary.iterdir():
            if path.is_file() and path.suffix in {".jpg", ".txt", ".mp4"}:
                path.unlink()
        self.revision = 0
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / "memory.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, goal TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL, session_id TEXT NOT NULL REFERENCES sessions(id),
                timestamp TEXT NOT NULL, application TEXT NOT NULL, window_title TEXT NOT NULL,
                event_type TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS observations_time ON observations(timestamp);
            CREATE INDEX IF NOT EXISTS observations_session ON observations(session_id, sequence);
            CREATE TABLE IF NOT EXISTS recommendations (
                id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id),
                timestamp TEXT NOT NULL, provider TEXT NOT NULL, response TEXT NOT NULL,
                evidence_ids TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL, attachment TEXT
            );
        """)
        # A previous run may have ended without closing its session.
        self.db.execute("UPDATE sessions SET ended_at=? WHERE ended_at IS NULL", (now_iso(),))
        self.db.commit()

    def start_session(self, goal: str) -> str:
        session = uuid4().hex
        with self.lock, self.db:
            self.db.execute("INSERT INTO sessions VALUES (?, ?, NULL, ?)", (session, now_iso(), goal))
        return session

    def end_session(self, session: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE sessions SET ended_at=? WHERE id=?", (now_iso(), session))

    def add(self, event: Observation) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO observations(id,session_id,timestamp,application,window_title,event_type,payload) VALUES (?,?,?,?,?,?,?)",
                            (event.id, event.session_id, event.timestamp, event.application,
                             event.window_title, event.event_type, json.dumps(event.to_dict(), ensure_ascii=False)))
            self.revision += 1

    def update_observer(self, observation_id: str, **fields) -> bool:
        allowed = {"interpretation", "observer_status", "observer_model", "observer_latency_ms", "observer_error", "observer_notes", "observer_input"}
        if set(fields) - allowed:
            raise ValueError("Only observer interpretation fields may be updated.")
        with self.lock, self.db:
            row = self.db.execute("SELECT payload FROM observations WHERE id=?", (observation_id,)).fetchone()
            if row is None:
                return False
            event = json.loads(row[0])
            event.update(fields)
            self.db.execute("UPDATE observations SET payload=? WHERE id=?", (json.dumps(event, ensure_ascii=False), observation_id))
            self.revision += 1
            return True

    def query(self, *, session_id: str | None = None, search: str = "", since: str | None = None,
              limit: int = 500) -> list[dict]:
        clauses, args = [], []
        if session_id:
            clauses.append("session_id=?")
            args.append(session_id)
        if search:
            clauses.append("payload LIKE ? ESCAPE '\\'")
            args.append("%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if since:
            clauses.append("timestamp>=?")
            args.append(since)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.lock:
            rows = self.db.execute("SELECT payload FROM observations" + where + " ORDER BY sequence DESC LIMIT ?",
                                   [*args, min(max(limit, 1), 10000)]).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def sessions(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 200")]

    def count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    def save_chat(self, role, content, attachment=None):
        if role not in {"user", "assistant", "notice"}:
            raise ValueError("Invalid chat role")
        with self.lock, self.db:
            self.db.execute("INSERT INTO chat_messages(timestamp,role,content,attachment) VALUES (?,?,?,?)",
                            (now_iso(), role, content, attachment))

    def chat_history(self, limit=200):
        with self.lock:
            rows = self.db.execute("SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in reversed(rows)]

    def clear_chat(self):
        with self.lock, self.db:
            self.db.execute("DELETE FROM chat_messages")

    def save_response(self, session_id: str | None, provider: str, response: str, evidence_ids: list[str]) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO recommendations VALUES (?,?,?,?,?,?)",
                            (uuid4().hex, session_id, now_iso(), provider, response, json.dumps(evidence_ids)))

    def responses(self, session_id: str | None = None) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM recommendations" + (" WHERE session_id=?" if session_id else "") +
                                   " ORDER BY timestamp DESC LIMIT 20", (session_id,) if session_id else ()).fetchall()
        return [dict(row) for row in reversed(rows)]

    def evidence_path(self, relative: str) -> Path | None:
        path = (self.directory / relative).resolve()
        return path if path.is_relative_to(self.directory / "screenshots") and path.is_file() else None

    def maintain(self, retention_days: int, budget_mb: int) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="milliseconds")
        removed = 0
        with self.lock, self.db:
            self.db.execute("DELETE FROM observations WHERE timestamp<?", (cutoff,))
            self.db.execute("DELETE FROM recommendations WHERE timestamp<?", (cutoff,))
            self.db.execute("DELETE FROM chat_messages WHERE timestamp<?", (cutoff,))
            self.db.execute("DELETE FROM sessions WHERE started_at<? AND ended_at IS NOT NULL AND id NOT IN (SELECT session_id FROM observations) AND id NOT IN (SELECT session_id FROM recommendations WHERE session_id IS NOT NULL)", (cutoff,))
            referenced = {json.loads(r[0]).get("screenshot") for r in self.db.execute("SELECT payload FROM observations")}
            files = sorted((self.directory / "screenshots").glob("*.jpg"), key=lambda p: p.stat().st_mtime)
            total = sum(p.stat().st_size for p in files)
            for path in files:
                relative = path.relative_to(self.directory).as_posix()
                if relative not in referenced or total > budget_mb * 1024 * 1024:
                    total -= path.stat().st_size
                    path.unlink()
                    removed += 1
        # Old event references deliberately remain; export reports missing evidence.
        return {"screenshots_removed": removed, "screenshot_bytes": total}

    def clear(self) -> None:
        with self.lock:
            with self.db:
                self.db.execute("DELETE FROM recommendations")
                self.db.execute("DELETE FROM chat_messages")
                self.db.execute("DELETE FROM observations")
                self.db.execute("DELETE FROM sessions")
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.execute("VACUUM")
            for path in (self.directory / "screenshots").glob("*.jpg"):
                path.unlink()
            for path in (self.directory / "inference-temp").iterdir():
                if path.is_file() and path.suffix in {".jpg", ".txt", ".mp4"}:
                    path.unlink()
            self.revision += 1

    def close(self) -> None:
        with self.lock:
            self.db.close()
