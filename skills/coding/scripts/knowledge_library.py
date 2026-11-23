"""The standalone editor's local Second Brain and shared conversation browser."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading

import brain
from chat_memory import AUTOMATIC_TITLE, CONVERSATION_POSITIONS, DISPLAY_TITLE, ChatMemory, atomic_text, conversation_parts, saved_checkpoints
from reminder_store import reminders
from second_brain_review import review_transaction, snapshot


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


def review_notes(root):
    for section, path in note_paths(root, folder_names(root)):
        value = note_summary(root, path)
        if value is not None:
            yield section, *value


def note_detail(path, identity):
    original = path.read_bytes()
    meta, text = brain.split_frontmatter(original.decode("utf-8-sig"))
    source = re.search(r"\[\[memory/sessions/([a-f0-9]{24})/context\|Conversa de origem\]\]", text)
    return {"id": identity, "title": str(meta.get("title") or path.stem), "text": text,
            "sourceConversation": source[1] if source else None,
            "revision": hashlib.sha256(original).hexdigest()}


def update_note(path, identity, request):
    if path.name in brain.SKIP_FILES:
        raise brain.BrainError("Este arquivo não faz parte das notas para revisão.")
    original = path.read_bytes()
    if request.get("revision") != hashlib.sha256(original).hexdigest():
        raise brain.BrainError("A nota mudou fora do editor. Abra a versão atual para revisar.")
    source = original.decode("utf-8-sig")
    frontmatter = re.match(r"\A(---[ \t]*\r?\n)(.*?)(^---[ \t]*(?:\r?\n|\Z))", source, re.M | re.S)
    text = request.get("text")
    if text is not None and (not isinstance(text, str) or len(text) > 40000):
        raise brain.BrainError("Use até 40.000 caracteres no conteúdo da nota.")
    newline = "\r\n" if "\r\n" in source else "\n"
    body = source[frontmatter.end():] if frontmatter else source
    if text is not None:
        body = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
        if body and not body.endswith(newline):
            body += newline
    prefix = ""
    if frontmatter:
        updated = f"updated: {datetime.now(timezone.utc).date().isoformat()}"
        header, replaced = re.subn(r"^updated:[^\r\n]*", updated, frontmatter[2], flags=re.M | re.I)
        if not replaced:
            header += updated + newline
        prefix = frontmatter[1] + header + frontmatter[3]
        if body and not prefix.endswith(newline):
            prefix += newline
    bom = "\ufeff" if original.startswith(b"\xef\xbb\xbf") else ""
    if path.read_bytes() != original:
        raise brain.BrainError("A nota mudou durante a revisão. Abra a versão atual antes de salvar.")
    atomic_text(path, bom + prefix + body)
    return note_detail(path, identity)


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


def memory_switch(memory, exists, on):
    """Turn chat memory on or off from the editor, like `memory on|off`.

    On: enable it and install the capture hooks and the rules in Claude Code and Codex.
    Off: stop capturing; the history and the hooks stay, and the hooks skip a disabled memory.
    """
    if not isinstance(on, bool):
        raise brain.BrainError("Informe se a memória fica ligada ou desligada.")
    if on:
        if not exists:
            raise brain.BrainError("Pasta Second Brain ausente.")
        from chat_memory_setup import install

        memory.enable()
        report = install(memory, hooks=True, rules=True)
        return {"enabled": True, "hooks": report.get("hooks", []), "rules": report.get("rules", [])}
    if memory.root.is_dir():
        atomic_text(memory.root / "config.json", '{"enabled": false, "version": 1}\n')
    return {"enabled": False}


def conversation_index(memory, group, query, page):
    with memory.connect() as db:
        groups = db.execute("""SELECT scope AS id, min(project) AS project, count(*) AS count
            FROM (SELECT project_key(project) AS scope, min(project) AS project
                  FROM sessions GROUP BY scope,agent,source_session)
            GROUP BY scope ORDER BY project COLLATE NOCASE""").fetchall()
        where = f"""(? = '' OR project_key(s.project) = ?) AND
            (? = '' OR instr(lower(({DISPLAY_TITLE}) || ' ' || ({AUTOMATIC_TITLE}) || ' ' || s.summary || ' ' || s.agent), lower(?)) > 0
             OR EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.id AND instr(lower(m.content), lower(?)) > 0))"""
        params = (group, "" if group == "@general" else group, query, query, query)
        matched = f"""WITH matched AS (
            SELECT s.*, ROW_NUMBER() OVER (PARTITION BY s.agent,s.source_session ORDER BY s.updated DESC,s.id) AS rank
            FROM sessions s WHERE {where})"""
        total = db.execute(matched + " SELECT count(*) FROM matched WHERE rank=1", params).fetchone()[0]
        count = db.execute("SELECT count(*) FROM (SELECT 1 FROM sessions GROUP BY agent,source_session)").fetchone()[0]
        rows = db.execute(matched + f""" SELECT s.id,{DISPLAY_TITLE} AS title,s.agent,result.updated,
            result.project AS path,project_key(result.project) AS scope,
            (SELECT count(DISTINCT m.event_id) FROM messages m JOIN sessions part ON m.session_id=part.id
                WHERE part.agent=s.agent AND part.source_session=s.source_session) AS messages
            FROM matched result JOIN sessions s ON s.id=(
                SELECT origin.id FROM sessions origin WHERE origin.agent=result.agent
                AND origin.source_session=result.source_session ORDER BY origin.created,origin.id LIMIT 1)
            WHERE result.rank=1 ORDER BY result.updated DESC,s.id LIMIT ? OFFSET ?""",
            (*params, PAGE_SIZE, page * PAGE_SIZE)).fetchall()
    return {
        "groups": [{"id": group_row["id"] or "@general", "label": Path(group_row["project"]).name or "Geral",
                    "count": group_row["count"], "path": group_row["project"]} for group_row in groups],
        "count": count, "total": total,
        "entries": [{**dict(row), "group": Path(row["path"]).name or "Geral"} for row in rows],
    }


def conversation_links(db, parts):
    agent, source = parts[0]["agent"], parts[0]["source_session"]
    children = db.execute("""SELECT s.id FROM sessions s JOIN sessions origin ON origin.id=s.parent
        WHERE origin.agent=? AND origin.source_session=? ORDER BY s.updated DESC""", (agent, source))
    result = {}
    for key, ids in (("previous", [row["parent"] for row in parts if row["parent"]]),
                     ("continuations", [row["id"] for row in children])):
        refs = {}
        for identity in dict.fromkeys(ids):
            linked = conversation_parts(db, identity)
            if not linked or (linked[0]["agent"], linked[0]["source_session"]) == (agent, source):
                continue
            ref = linked[0]
            refs[ref["id"]] = {"id": ref["id"], "title": ref["display_title"], "agent": ref["agent"]}
        result[key] = list(refs.values())
    return result


def conversation(memory, identity, page):
    with memory.connect() as db:
        parts = conversation_parts(db, identity)
        if not parts:
            raise brain.BrainError("Conversa não encontrada.")
        first = parts[0]
        latest = max(parts, key=lambda row: (row["updated"], row["id"]))
        scope = (first["agent"], first["source_session"])
        count, newest = db.execute(
            f"SELECT count(*),coalesce(max(position),0) FROM ({CONVERSATION_POSITIONS})", scope
        ).fetchone()
        messages = db.execute(f"""SELECT * FROM (
            SELECT m.position,m.role,m.content,m.timestamp,s.project FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE m.position IN ({CONVERSATION_POSITIONS}) ORDER BY m.position DESC LIMIT ? OFFSET ?) ORDER BY position""",
            (*scope, MESSAGE_PAGE, page * MESSAGE_PAGE)).fetchall()
        history = saved_checkpoints(db, identity)
        summary = max((row for row in parts if row["summary"] or row["next_step"]),
                      key=lambda row: row["updated"], default=latest)
        checkpoint = history[0] if history else None
        links = conversation_links(db, parts)
    return {"id": first["id"], "title": first["display_title"], "customTitle": first["custom_title"],
            "agent": first["agent"], "project": latest["project"],
            "projects": list(dict.fromkeys(row["project"] for row in parts if row["project"])),
            "updated": latest["updated"], "state": latest["state"],
            "summary": checkpoint["summary"] if checkpoint else summary["summary"],
            "next_step": checkpoint["next_step"] if checkpoint else summary["next_step"],
            "checkpoint": checkpoint, "checkpointHistory": history[1:],
            "checkpointStale": newest > (checkpoint["through_position"] if checkpoint else 0)
                and (checkpoint is not None or bool(summary["summary"] or summary["next_step"])),
            **links, "count": count, "messages": [dict(row) for row in messages],
            "hasOlder": (page + 1) * MESSAGE_PAGE < count}


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
    def __init__(self, policy_path=None):
        self.write_lock = threading.Lock()
        self.review_database = policy_path.parent / "second-brain-review.sqlite3" if policy_path else None

    def action(self, request):
        try:
            return {"ok": True, "value": self._action(request)}
        except (brain.BrainError, OSError, UnicodeError, sqlite3.Error, TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    def _action(self, request):
        kind, action = request.get("kind"), request.get("action")
        if kind == "reminders" and self.review_database is not None:
            return reminders(self.review_database, request)
        if kind not in ("notes", "memory", "review"):
            raise brain.BrainError("Área desconhecida.")
        page = request.get("page", 0)
        if type(page) is not int or not 0 <= page <= 1000:
            raise brain.BrainError("Página inválida.")
        root = brain.brain_path()
        if redirected(root):
            raise brain.BrainError("O Second Brain usa um caminho redirecionado.")
        root = root.resolve()
        exists = root.is_dir()
        if kind == "review" and self.review_database is not None and action in ("status", "run"):
            return snapshot(self.review_database, root, review_notes(root), force=action == "run")
        if kind == "review":
            raise brain.BrainError("A revisão não está disponível.")
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
        if kind == "memory" and action == "switch":
            return memory_switch(memory, exists, request.get("enabled"))
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
            return note_detail(relative_note(root, identity), identity)
        if kind == "memory" and action == "rename" and "title" in request:
            memory.rename(identity, request["title"])
            return conversation(memory, identity, 0)
        if kind == "memory" and action == "delete":
            if request.get("confirm") is not True or not re.fullmatch(r"[0-9a-f]{24}", identity):
                raise brain.BrainError("Confirme a exclusão da conversa na Memória.")
            memory.delete_conversation(identity)
            return None
        if kind == "memory" and action == "checkpoint":
            summary, next_step = request.get("summary", ""), request.get("next_step", "")
            expected = request.get("through_position")
            if (not isinstance(summary, str) or not isinstance(next_step, str)
                    or len(summary) > 8000 or len(next_step) > 4000 or type(expected) is not int or expected < 0):
                raise brain.BrainError("Resumo ou próximo passo inválido.")
            current = conversation(memory, identity, 0)
            memory.checkpoint(identity, summary.strip(), next_step.strip(), current["state"],
                              details=request.get("details"), expected_position=expected)
            return conversation(memory, identity, 0)
        if kind == "notes" and action == "record":
            return self._record(root, request)
        if kind == "notes" and action == "update" and self.review_database is not None:
            with review_transaction(self.review_database):
                return update_note(relative_note(root, identity), identity, request)
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
        related = []
        origin = request.get("sourceConversation")
        if origin:
            memory = ChatMemory(root)
            with memory.connect() as db:
                parts = conversation_parts(db, origin)
            if not parts:
                raise brain.BrainError("Conversa de origem não encontrada.")
            related = [f"memory/sessions/{parts[0]['id']}/context|Conversa de origem"]
        args = argparse.Namespace(brain=str(root), folder=section, title=title, type=kind, area=brain.route_key(section),
                                  summary=text, no_report=True, orchestration=None, related=related, write=True,
                                  tag=[tag.strip()[:80] for tag in tags[:20] if tag.strip()])
        with self.write_lock:
            note, _ = brain.record_note(args)
        return {"id": note.relative_to(root).as_posix(), "title": title, "text": text}
