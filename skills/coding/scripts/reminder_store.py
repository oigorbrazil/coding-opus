"""Persistent reminders for the Coding Opus editor."""

from datetime import date
import uuid

from brain import BrainError
from second_brain_review import review_transaction


def day(value):
    if isinstance(value, str) and len(value) == 10:
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        except ValueError:
            pass
    raise BrainError("Informe uma data válida.")


def reminders(database, request, today=None):
    client_day = request.get("today")
    today = today or (day(client_day) if client_day is not None else date.today())
    operation = request.get("action")
    if operation not in ("list", "save", "complete", "reopen"):
        raise BrainError("Ação de lembrete desconhecida.")
    with review_transaction(database) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, due TEXT NOT NULL,
            shortcut TEXT NOT NULL DEFAULT '', completed TEXT
        )""")
        db.execute("INSERT OR IGNORE INTO reminders (id,title,due,shortcut) VALUES ('document', '', ?, 'document')",
                   (today.isoformat(),))
        identity = request.get("id")
        if operation == "save":
            title, due = request.get("title"), request.get("due")
            title = title.strip() if isinstance(title, str) else ""
            if not title or len(title) > 120 or "\n" in title or "\r" in title:
                raise BrainError("Informe um título de até 120 caracteres.")
            due = day(due).isoformat()
            if identity is None:
                db.execute("INSERT INTO reminders (id,title,due) VALUES (?,?,?)", (uuid.uuid4().hex, title, due))
            elif not db.execute("UPDATE reminders SET title=?,due=? WHERE id=? AND completed IS NULL",
                                (title, due, identity)).rowcount:
                raise BrainError("Lembrete pendente não encontrado.")
        elif operation in ("complete", "reopen"):
            completed = today.isoformat() if operation == "complete" else None
            if not db.execute("UPDATE reminders SET completed=? WHERE id=?", (completed, identity)).rowcount:
                raise BrainError("Lembrete não encontrado.")
        columns = ("id", "title", "due", "shortcut", "completed")
        items = [dict(zip(columns, row)) for row in db.execute("""
            SELECT id,title,due,shortcut,completed FROM reminders
            ORDER BY completed IS NOT NULL, completed DESC, due, id
        """)]
    return {"today": today.isoformat(), "items": items}
