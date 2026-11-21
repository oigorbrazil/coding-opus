"""Read the local Codex and Claude Code catalogs without copying their history."""

from collections import deque
from contextlib import closing
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess


PROVIDERS = ("codex", "claude")
PAGE_SIZE = 40
UUID = r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}"
MAX_TEXT = 40000


def chat_home(agent):
    key = "CODEX_HOME" if agent == "codex" else "CLAUDE_CONFIG_DIR"
    return Path(os.environ.get(key) or Path.home() / f".{agent}").expanduser()


def project_key(value):
    return os.path.normcase(os.path.normpath(value))


def admitted(path, root):
    try:
        return path.is_file() and path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def json_records(lines):
    for line in lines:
        try:
            value = json.loads(line)
        except (UnicodeError, ValueError):
            continue
        if isinstance(value, dict):
            yield value


def content_text(content):
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n\n".join(item["text"] for item in content if isinstance(item, dict)
                       and item.get("type") in ("text", "input_text", "output_text")
                       and isinstance(item.get("text"), str)).strip()


def user_text(text):
    if text.startswith(("<environment_context>", "# AGENTS.md instructions for ")):
        return ""
    if text.startswith(("# Files mentioned by the user:", "# Files pasted by the user:")) and "## My request:" in text:
        text = text.partition("## My request:")[2].split("<image name=", 1)[0]
    return text.strip()


def codex_catalog(home):
    roots = home / "sessions"
    databases = sorted(home.glob("state_*.sqlite"), key=lambda p: int(p.stem.split("_")[-1])
                       if p.stem.split("_")[-1].isdigit() else -1, reverse=True)
    for database in databases:
        if not admitted(database, home):
            continue
        with closing(sqlite3.connect(database.absolute().as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(threads)")}
            if not {"id", "title", "cwd", "archived", "rollout_path", "updated_at"} <= columns:
                continue
            title = "COALESCE(NULLIF(name, ''), title)" if "name" in columns else "title"
            exclusion = " AND COALESCE(agent_role, '') = ''" if "agent_role" in columns else ""
            rows = db.execute(f"""SELECT id, {title}, cwd, rollout_path, updated_at FROM threads
                WHERE archived=0{exclusion} ORDER BY updated_at DESC LIMIT 1000""").fetchall()
        for identity, title, cwd, filename, updated in rows:
            if not cwd or not Path(cwd).is_absolute() or not filename or not re.fullmatch(UUID, identity, re.I):
                continue
            path = Path(filename)
            if not path.is_file() and path.suffix == ".jsonl":
                path = path.with_suffix(".jsonl.zst")
            if not admitted(path, roots):
                continue
            yield {"id": identity, "agent": "codex", "title": (title or "Codex")[:160],
                   "project": project_key(cwd), "cwd": cwd, "updatedAt": (updated or 0) * 1000, "path": path}
        break


@lru_cache(maxsize=1200)
def claude_metadata(path, size, modified):
    with path.open("rb") as source:
        head = source.read(min(size, 128 * 1024)).splitlines()
        tail = []
        if size > 128 * 1024:
            source.seek(max(0, size - 128 * 1024))
            tail = source.read().splitlines()[1:]
    cwd, first, title = "", "", ""
    for row in json_records((*head, *tail)):
        if row.get("sessionId") != path.stem or row.get("isSidechain") is True:
            continue
        directory = row.get("cwd")
        if isinstance(directory, str) and Path(directory).is_absolute():
            cwd = directory
        if row.get("type") == "custom-title" and isinstance(row.get("customTitle"), str):
            title = row["customTitle"].strip()
        elif not first and row.get("type") == "user" and isinstance(row.get("message"), dict):
            first = user_text(content_text(row["message"].get("content")))
    if cwd:
        return {"id": path.stem, "agent": "claude", "title": (title or first or "Claude")[:160],
                "project": project_key(cwd), "cwd": cwd, "updatedAt": modified * 1000, "path": path}
    return None


def claude_catalog(home):
    root = home / "projects"
    for path in root.glob("*/*.jsonl"):
        if not re.fullmatch(UUID, path.stem, re.I) or not admitted(path, root):
            continue
        try:
            info = path.stat()
            metadata = claude_metadata(path, info.st_size, info.st_mtime)
        except OSError:
            continue
        if metadata:
            yield metadata


def records(path):
    if path.suffix != ".zst":
        with path.open("rb") as source:
            yield from json_records(source)
        return
    node = shutil.which("node")
    if not node:
        raise OSError("Instale o Node.js para ler este histórico compactado.")
    result = subprocess.run([node, "-e", "process.stdout.write(require('node:zlib').zstdDecompressSync(require('node:fs').readFileSync(process.argv[1]), {maxOutputLength: 134217728}))", str(path)],
                            capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise OSError("O Node.js local não conseguiu abrir o histórico compactado do Codex.")
    yield from json_records(result.stdout.splitlines())


def codex_paths(thread):
    root = chat_home("codex") / "sessions"
    files = {}
    for file in root.glob(f"*/*/*/rollout-*{thread['id']}*.jsonl*"):
        suffix = rf"-{thread['id']}(?:_{UUID})?\.jsonl(?:\.zst)?$"
        if not re.search(suffix, file.name, re.I) or not admitted(file, root):
            continue
        logical = file.name.removesuffix(".zst")
        if logical not in files or file.suffix == ".jsonl":
            files[logical] = file
    logical = thread["path"].name.removesuffix(".zst")
    files.setdefault(logical, thread["path"])
    return [files[name] for name in sorted(files)]


def messages(thread, before=None):
    is_codex = thread["agent"] == "codex"
    paths = codex_paths(thread) if is_codex else [thread["path"]]
    items = deque(maxlen=PAGE_SIZE)
    count = 0
    for path in paths:
        for row in records(path):
            if before is not None and count >= before:
                return {"messages": list(items), "before": max(0, count - PAGE_SIZE) or None}
            if is_codex:
                payload = row.get("payload")
                if row.get("type") != "response_item" or not isinstance(payload, dict) or payload.get("type") != "message":
                    continue
                if payload.get("phase") == "commentary":
                    continue
                role, content = payload.get("role"), payload.get("content")
            else:
                if row.get("sessionId") != thread["id"] or row.get("isSidechain") is True:
                    continue
                role = row.get("type")
                payload = row.get("message")
                content = payload.get("content") if isinstance(payload, dict) else None
            if role not in ("user", "assistant"):
                continue
            text = content_text(content)
            if role == "user":
                text = user_text(text)
            if text:
                items.append({"role": role, "text": text[:MAX_TEXT], "timestamp": row.get("timestamp")})
                count += 1
    return {"messages": list(items), "before": max(0, count - PAGE_SIZE) or None}
