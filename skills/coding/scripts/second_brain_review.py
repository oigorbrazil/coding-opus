"""Local weekly review of note metadata and unanswered conversations."""

from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3

from brain import BrainError
from chat_memory import ChatMemory


INTERVAL = timedelta(days=7)
NOTE_AGE = timedelta(days=90)
REPLY_GRACE = timedelta(days=1)
LIST_LIMIT = 24


def note_date(value):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date


def unanswered(root, now):
    try:
        memory = ChatMemory(root)
        if not memory.enabled() or not (memory.root / "memory.sqlite3").is_file():
            return None
        with memory.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT s.id, s.title, s.agent, s.project, m.timestamp AS updated
                FROM sessions s JOIN messages m ON m.position = (
                    SELECT max(position) FROM messages WHERE session_id=s.id
                )
                WHERE s.agent IN ('codex', 'claude') AND m.role='user'
                  AND s.pending NOT LIKE 'private:%' AND julianday(m.timestamp) <= julianday(?)
                ORDER BY julianday(m.timestamp), s.id
            """, ((now - REPLY_GRACE).isoformat(),))]
    except (BrainError, OSError, sqlite3.Error):
        return None


def findings(root, notes, now):
    inbox, stale = [], []
    for section, row, meta in notes:
        if str(meta.get("status", "")).casefold() == "arquivado":
            continue
        item = {"id": row["id"], "title": row["title"], "updated": row["updated"]}
        updated = note_date(row["updated"])
        if section.casefold() == "00-inbox" or str(meta.get("status", "")).casefold() == "inbox":
            inbox.append(item)
        elif updated is not None and updated <= now - NOTE_AGE:
            stale.append((updated, item))
    inbox.sort(key=lambda item: (item["updated"], item["id"]))
    stale.sort(key=lambda entry: (entry[0], entry[1]["id"]))
    replies = unanswered(root, now)

    def preview(items):
        return {"items": items[:LIST_LIMIT], "count": len(items)}

    return {"memoryAvailable": replies is not None, "inbox": preview(inbox),
            "stale": preview([item for _, item in stale]), "unanswered": preview(replies or [])}


@contextmanager
def review_transaction(database):
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        yield db


def snapshot(database, root, notes, force=False, now=None):
    if not root.is_dir():
        return {"exists": False}
    now = now or datetime.now(timezone.utc)
    key = os.path.normcase(str(root))
    with review_transaction(database) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS reviews (
            brain TEXT PRIMARY KEY, reviewed TEXT NOT NULL, result TEXT NOT NULL
        )""")
        previous = db.execute("SELECT reviewed, result FROM reviews WHERE brain=?", (key,)).fetchone()
        reviewed = note_date(previous[0]) if previous else None
        if force or reviewed is None or now >= reviewed + INTERVAL:
            result = findings(root, notes, now)
            reviewed = now
            db.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?)",
                       (key, reviewed.isoformat(), json.dumps(result, ensure_ascii=False)))
        else:
            result = json.loads(previous[1])
    return {"exists": True, "lastReviewed": reviewed.isoformat(),
            "nextReview": (reviewed + INTERVAL).isoformat(), **result}
