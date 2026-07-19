import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .models import Memory


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  event_type TEXT NOT NULL DEFAULT 'conversation',
  layer TEXT NOT NULL DEFAULT 'episodic',
  summary TEXT NOT NULL,
  details TEXT NOT NULL DEFAULT '',
  importance INTEGER NOT NULL DEFAULT 5 CHECK(importance BETWEEN 1 AND 10),
  tags TEXT NOT NULL DEFAULT '',
  conversation_id TEXT,
  valid_from TEXT,
  valid_to TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  merged_into INTEGER,
  access_count INTEGER NOT NULL DEFAULT 0,
  last_accessed TEXT,
  FOREIGN KEY(merged_into) REFERENCES memories(id)
);
CREATE INDEX IF NOT EXISTS idx_memories_active_time
  ON memories(archived, event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_conversation
  ON memories(conversation_id, event_type);
CREATE TABLE IF NOT EXISTS relations (
  from_id INTEGER NOT NULL,
  to_id INTEGER NOT NULL,
  relation TEXT NOT NULL DEFAULT 'related',
  PRIMARY KEY(from_id,to_id,relation),
  FOREIGN KEY(from_id) REFERENCES memories(id) ON DELETE CASCADE,
  FOREIGN KEY(to_id) REFERENCES memories(id) ON DELETE CASCADE
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  memory_id UNINDEXED, summary, details, tags, tokenize='unicode61'
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, path: str | Path = "tidal-memory.db"):
        self.path = str(path)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def transaction(self):
        try:
            yield self._db
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    @staticmethod
    def _memory(row) -> Memory:
        return Memory(
            id=row["id"], occurred_at=row["occurred_at"], recorded_at=row["recorded_at"],
            event_type=row["event_type"], layer=row["layer"], summary=row["summary"],
            details=row["details"] or "", importance=row["importance"], tags=row["tags"] or "",
            conversation_id=row["conversation_id"], valid_from=row["valid_from"],
            valid_to=row["valid_to"], archived=bool(row["archived"]), merged_into=row["merged_into"],
        )

    def add(
        self,
        summary: str,
        *,
        details: str = "",
        occurred_at: Optional[str] = None,
        event_type: str = "conversation",
        layer: str = "episodic",
        importance: int = 5,
        tags: str = "",
        conversation_id: Optional[str] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
    ) -> int:
        text = summary.strip()
        if not text:
            raise ValueError("summary cannot be empty")
        now = utcnow()
        with self.transaction() as db:
            cur = db.execute(
                """INSERT INTO memories
                (occurred_at,recorded_at,event_type,layer,summary,details,importance,tags,
                 conversation_id,valid_from,valid_to)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (occurred_at or now, now, event_type, layer, text, details.strip(),
                 importance, tags, conversation_id, valid_from, valid_to),
            )
            memory_id = int(cur.lastrowid)
            db.execute(
                "INSERT INTO memory_fts(memory_id,summary,details,tags) VALUES (?,?,?,?)",
                (memory_id, text, details.strip(), tags),
            )
        return memory_id

    def get(self, memory_id: int) -> Optional[Memory]:
        row = self._db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._memory(row) if row else None

    def upsert_window_impression(
        self, conversation_id: str, impression: str, *, title: str = "Untitled",
        occurred_at: Optional[str] = None, ongoing_threads: Optional[list[dict]] = None,
    ) -> int:
        row = self._db.execute(
            """SELECT id FROM memories WHERE event_type='window_impression'
               AND conversation_id=? ORDER BY id DESC LIMIT 1""", (conversation_id,),
        ).fetchone()
        details = json.dumps({
            "title": title[:80],
            "ongoing_threads": self._clean_ongoing_threads(ongoing_threads or []),
        }, ensure_ascii=False, separators=(",", ":"))
        if row:
            self.update_text(row["id"], impression, details=details, occurred_at=occurred_at)
            return int(row["id"])
        return self.add(
            impression, details=details, occurred_at=occurred_at,
            event_type="window_impression", layer="episodic", importance=4,
            tags="impression,window", conversation_id=conversation_id,
        )

    @staticmethod
    def _clean_ongoing_threads(items: list[dict]) -> list[dict]:
        cleaned = []
        for item in items[:6]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip().lower()[:40]
            label = str(item.get("label", "")).strip()[:60]
            if key and label:
                cleaned.append({
                    "key": key,
                    "label": label,
                    "status": "done" if item.get("status") == "done" else "active",
                })
        return cleaned

    @classmethod
    def _threads_from_details(cls, details: str) -> list[dict]:
        try:
            value = json.loads(details or "{}")
        except (TypeError, ValueError):
            return []  # Legacy ``title=...`` details contain no thread slot.
        return cls._clean_ongoing_threads(value.get("ongoing_threads", []))

    def ongoing_threads(
        self, current_conversation_id: str = "", *, days: int = 14,
        scan_windows: int = 12, limit: int = 4,
    ) -> list[str]:
        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
        windows = self.rows(
            "archived=0 AND event_type='window_impression' AND coalesce(conversation_id,'')<>?",
            (current_conversation_id,),
        )[:scan_windows]
        decided, active = set(), []
        for window in windows:  # newest state wins
            try:
                seen_at = datetime.fromisoformat(window.occurred_at.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if seen_at < cutoff:
                continue
            for item in self._threads_from_details(window.details):
                if item["key"] in decided:
                    continue
                decided.add(item["key"])
                if item["status"] == "active":
                    active.append(item["label"])
                if len(active) >= limit:
                    return active
        return active

    def update_text(
        self, memory_id: int, summary: str, *, details: Optional[str] = None,
        occurred_at: Optional[str] = None,
    ):
        old = self.get(memory_id)
        if not old:
            raise KeyError(memory_id)
        new_details = old.details if details is None else details
        new_time = old.occurred_at if occurred_at is None else occurred_at
        with self.transaction() as db:
            db.execute(
                "UPDATE memories SET summary=?,details=?,occurred_at=?,recorded_at=? WHERE id=?",
                (summary.strip(), new_details, new_time, utcnow(), memory_id),
            )
            db.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
            db.execute(
                "INSERT INTO memory_fts(memory_id,summary,details,tags) VALUES (?,?,?,?)",
                (memory_id, summary.strip(), new_details, old.tags),
            )

    def archive_many(self, memory_ids: Iterable[int], merged_into: Optional[int] = None):
        ids = list(memory_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self.transaction() as db:
            db.execute(
                f"UPDATE memories SET archived=1,merged_into=? WHERE id IN ({placeholders})",
                [merged_into, *ids],
            )
            db.execute(f"DELETE FROM memory_fts WHERE memory_id IN ({placeholders})", ids)

    def forget(self, memory_id: int):
        self.archive_many([memory_id])

    def link(self, from_id: int, to_id: int, relation: str = "related"):
        if from_id == to_id:
            raise ValueError("a memory cannot link to itself")
        if not self.get(from_id) or not self.get(to_id):
            raise KeyError("both memories must exist")
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO relations(from_id,to_id,relation) VALUES (?,?,?)",
                (from_id, to_id, relation),
            )

    def neighbors(self, memory_id: int) -> list[Memory]:
        rows = self._db.execute(
            """SELECT m.* FROM relations r JOIN memories m
               ON m.id=CASE WHEN r.from_id=? THEN r.to_id ELSE r.from_id END
               WHERE (r.from_id=? OR r.to_id=?) AND m.archived=0""",
            (memory_id, memory_id, memory_id),
        ).fetchall()
        return [self._memory(row) for row in rows]

    def supersede(self, old_id: int, new_summary: str, **kwargs) -> int:
        old = self.get(old_id)
        if not old:
            raise KeyError(old_id)
        now = utcnow()
        new_id = self.add(
            new_summary, occurred_at=kwargs.pop("occurred_at", now),
            event_type=kwargs.pop("event_type", old.event_type),
            layer=kwargs.pop("layer", old.layer),
            importance=kwargs.pop("importance", old.importance),
            tags=kwargs.pop("tags", old.tags), valid_from=now, **kwargs,
        )
        with self.transaction() as db:
            db.execute("UPDATE memories SET valid_to=?,archived=1,merged_into=? WHERE id=?",
                       (now, new_id, old_id))
            db.execute("DELETE FROM memory_fts WHERE memory_id=?", (old_id,))
        return new_id

    def rows(self, where: str = "archived=0", params: tuple = ()) -> list[Memory]:
        result = self._db.execute(
            "SELECT * FROM memories WHERE " + where + " ORDER BY occurred_at DESC,id DESC", params,
        ).fetchall()
        return [self._memory(row) for row in result]

    def impression_ladder(self, current_conversation_id: str = "", max_chars: int = 1000) -> str:
        windows = self.rows(
            "archived=0 AND event_type='window_impression' AND coalesce(conversation_id,'')<>?",
            (current_conversation_id,),
        )[:2]
        weekly = self.rows("archived=0 AND event_type='rollup_week'")[:1]
        monthly = self.rows("archived=0 AND event_type='rollup_month'")[:1]
        lines = [f"- Recent window: {item.summary}" for item in windows]
        threads = self.ongoing_threads(current_conversation_id)
        if threads:
            lines.append("- Ongoing: " + "; ".join(threads))
        lines += [f"- Recent week: {item.summary}" for item in weekly]
        lines += [f"- Older month: {item.summary}" for item in monthly]
        output = ""
        for line in lines:
            candidate = line if not output else output + "\n" + line
            if len(candidate) > max_chars:
                break
            output = candidate
        return output

    def stable_context(self, max_items: int = 6, max_chars: int = 1200) -> str:
        items = self.rows(
            """archived=0 AND (layer='core' OR (layer='semantic' AND importance>=9))
               AND (valid_to IS NULL OR valid_to='')"""
        )[:max_items]
        output = ""
        for item in items:
            line = "- " + item.summary
            candidate = line if not output else output + "\n" + line
            if len(candidate) > max_chars:
                break
            output = candidate
        return output
