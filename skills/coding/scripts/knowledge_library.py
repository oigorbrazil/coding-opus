"""The standalone editor's local Second Brain and shared conversation browser."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading

import brain
from chat_memory import ChatMemory


PAGE_SIZE = 24
MESSAGE_PAGE = 24
NOTE_TYPES = ("nota", "decisao", "estudo", "ideia", "meeting")
SKIP_DIRS = {"memory", *(name.casefold() for name in brain.SKIP_DIRS)}


def headline(path):
    return re.sub(r"^\d+[-_ ]*", "", path) or path


def redirected(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def disallowed(name):
    return name.startswith(".") or name.casefold() in SKIP_DIRS


def folder_names(root):
    return [name for name in brain.top_folders(root)
            if not disallowed(name) and not redirected(root / name)]


def relative_note(root, relative):
    parts = relative.split("/")
    if any(not part or part == ".." or disallowed(part) or ":" in part or "\\" in part for part in parts):
        raise brain.BrainError("Nota fora do Second Brain.")
    candidate = root
    for part in parts:
        candidate = candidate / part
        if redirected(candidate):
            raise brain.BrainError("A nota usa um caminho redirecionado.")
    if candidate.suffix.lower() != ".md" or not brain.inside(candidate, root) or not candidate.is_file():
        raise brain.BrainError("Nota não encontrada.")
    return candidate


def note_summary(root, path):
    try:
        with path.open(encoding="utf-8-sig") as handle:
            meta = read_metadata(handle)
        modified = path.stat().st_mtime
    except (OSError, UnicodeError):
        return None
    tags = meta.get("tags")
    summary = {
        "id": path.relative_to(root).as_posix(),
        "title": str(meta.get("title") or path.stem),
        "type": str(meta.get("type") or ""),
        "updated": str(meta.get("updated") or datetime.fromtimestamp(modified, timezone.utc).isoformat()),
        "tags": tags if isinstance(tags, list) else [],
    }
    return summary, meta


def read_metadata(handle):
    opening = handle.readline(16384)
    if opening.strip() != "---":
        return {}
    lines = [opening]
    size = len(opening)
    while size < 16384:
        line = handle.readline(16384 - size)
        if not line:
            break
        lines.append(line)
        if line.strip() == "---":
            return brain.split_frontmatter("".join(lines))[0]
        size += len(line)
    return {}


def note_paths(root, folders):
    for folder in folders:
        for current, children, names in os.walk(root / folder, followlinks=False):
            directory = Path(current)
            children[:] = [name for name in children if not disallowed(name) and not redirected(directory / name)]
            for name in names:
                path = directory / name
                if path.suffix.lower() == ".md" and not disallowed(name) and name not in brain.SKIP_FILES and not redirected(path):
                    yield folder, path
    for path in root.iterdir():
        if path.suffix.lower() == ".md" and path.is_file() and not disallowed(path.name) and path.name not in brain.SKIP_FILES and not redirected(path):
            yield "", path


def note_index(root, group, query, page):
    groups = folder_names(root)
    counts = Counter()
    entries = []
    words = [brain.fold(word) for word in query.split()][:12]
    for section, path in note_paths(root, groups):
        counts[section] += 1
        if group and section != group:
            continue
        value = note_summary(root, path)
        if value is None:
            continue
        row, meta = value
        if words and not brain.score_meta(path, meta, words):
            continue
        entries.append({**row, "group": section})
    entries.sort(key=lambda entry: (entry["updated"], entry["title"]), reverse=True)
    start = page * PAGE_SIZE
    return {
        "groups": [{"id": folder, "label": headline(folder), "count": counts[folder]} for folder in groups],
        "count": sum(counts.values()), "total": len(entries), "entries": entries[start:start + PAGE_SIZE],
    }


def conversation_index(memory, group, query, page):
    with memory.connect() as db:
        groups = db.execute("""SELECT project_key(project) AS id, project, count(*) AS count
            FROM sessions GROUP BY project_key(project) ORDER BY project COLLATE NOCASE""").fetchall()
        where = """(? = '' OR project_key(s.project) = ?) AND
            (? = '' OR instr(lower(s.title || ' ' || s.summary || ' ' || s.agent), lower(?)) > 0
             OR EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.id AND instr(lower(m.content), lower(?)) > 0))"""
        params = (group, "" if group == "@general" else group, query, query, query)
        total = db.execute("SELECT count(*) FROM sessions s WHERE " + where, params).fetchone()[0]
        rows = db.execute("""SELECT s.id,s.title,s.agent,s.updated,s.project AS path,project_key(s.project) AS scope,
            (SELECT count(*) FROM messages m WHERE m.session_id=s.id) AS messages
            FROM sessions s WHERE """ + where + " ORDER BY s.updated DESC LIMIT ? OFFSET ?",
            (*params, PAGE_SIZE, page * PAGE_SIZE)).fetchall()
    return {
        "groups": [{"id": group_row["id"] or "@general", "label": Path(group_row["project"]).name or "Geral",
                    "count": group_row["count"], "path": group_row["project"]} for group_row in groups],
        "count": sum(row["count"] for row in groups), "total": total,
        "entries": [{**dict(row), "group": Path(row["path"]).name or "Geral"} for row in rows],
    }


def conversation(memory, identity, page):
    with memory.connect() as db:
        record = db.execute("""SELECT id,title,agent,project,updated,summary,next_step,
            (SELECT count(*) FROM messages WHERE session_id=s.id) AS count
            FROM sessions s WHERE id=?""", (identity,)).fetchone()
        if not record:
            raise brain.BrainError("Conversa não encontrada.")
        messages = db.execute("""SELECT position,role,content,timestamp FROM (
            SELECT position,role,content,timestamp FROM messages WHERE session_id=?
            ORDER BY position DESC LIMIT ? OFFSET ?) ORDER BY position""",
            (identity, MESSAGE_PAGE, page * MESSAGE_PAGE)).fetchall()
    return {**dict(record), "messages": [dict(row) for row in messages],
            "hasOlder": (page + 1) * MESSAGE_PAGE < record["count"]}


def reveal(folder):
    if not folder.is_dir():
        raise brain.BrainError("Pasta não encontrada.")
    if os.name == "nt":
        os.startfile(folder)
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


class KnowledgeLibrary:
    def __init__(self):
        self.write_lock = threading.Lock()

    def action(self, request):
        try:
            return {"ok": True, "value": self._action(request)}
        except (brain.BrainError, OSError, UnicodeError, sqlite3.Error, TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    def _action(self, request):
        kind, action = request.get("kind"), request.get("action")
        if kind not in ("notes", "memory"):
            raise brain.BrainError("Área desconhecida.")
        page = request.get("page", 0)
        if type(page) is not int or not 0 <= page <= 1000:
            raise brain.BrainError("Página inválida.")
        root = brain.brain_path()
        if redirected(root):
            raise brain.BrainError("O Second Brain usa um caminho redirecionado.")
        root = root.resolve()
        exists = root.is_dir()
        memory = ChatMemory(root)
        directory = root if kind == "notes" else memory.root
        enabled = kind == "notes" or (exists and not redirected(directory) and memory.enabled() and
                                      (directory / "memory.sqlite3").is_file() and
                                      not redirected(directory / "memory.sqlite3"))
        if action == "list":
            group, query = str(request.get("group", ""))[:4096], str(request.get("query", ""))[:300].strip()
            result = {"entries": [], "groups": [], "total": 0, "count": 0}
            if exists and enabled:
                result = note_index(root, group, query, page) if kind == "notes" else conversation_index(memory, group, query, page)
            return {**result, "path": str(directory), "exists": exists, "enabled": enabled, "pageSize": PAGE_SIZE}
        if action == "reveal":
            if redirected(directory):
                raise brain.BrainError("A pasta usa um caminho redirecionado.")
            reveal(directory)
            return None
        if not exists or not enabled:
            raise brain.BrainError("Esta área não está disponível.")
        identity = str(request.get("id", ""))
        if action == "read":
            if kind == "memory":
                return conversation(memory, identity, page)
            path = relative_note(root, identity)
            meta, text = brain.split_frontmatter(path.read_text(encoding="utf-8-sig"))
            return {"id": identity, "title": str(meta.get("title") or path.stem), "text": text}
        if kind == "notes" and action == "record":
            return self._record(root, request)
        raise brain.BrainError("Ação desconhecida.")

    def _record(self, root, request):
        title = str(request.get("title", "")).strip()
        section = str(request.get("group", "")) or "00-Inbox"
        kind = request.get("type")
        text = str(request.get("text", "")).strip()
        tags = str(request.get("tags", "")).split(",")
        if not title or len(title) > 180 or "\n" in title or "\r" in title or not brain.slugify(title) or kind not in NOTE_TYPES:
            raise brain.BrainError("Informe um título e tipo válidos.")
        if section not in folder_names(root) or len(text) > 40000:
            raise brain.BrainError("Escolha uma seção válida e use até 40.000 caracteres.")
        args = argparse.Namespace(brain=str(root), folder=section, title=title, type=kind, area=brain.route_key(section),
                                  summary=text, no_report=True, orchestration=None, related=[], write=True,
                                  tag=[tag.strip()[:80] for tag in tags[:20] if tag.strip()])
        with self.write_lock:
            note, _ = brain.record_note(args)
        return {"id": note.relative_to(root).as_posix(), "title": title, "text": text}
