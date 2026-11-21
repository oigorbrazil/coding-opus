"""Resolve display titles for conversations already in the shared memory."""

from itertools import chain
import json
import os
from pathlib import Path
import re
import unicodedata


SESSION_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
TITLE_FIELDS = {"custom-title": "customTitle", "ai-title": "aiTitle"}


def jsonl_records(path, markers=()):
    try:
        with path.open("rb") as source:
            for line in source:
                if markers and not any(marker in line for marker in markers):
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record
    except (OSError, ValueError):
        return


def single_line_title(value):
    return " ".join(value.split())[:240].rstrip() if isinstance(value, str) else ""


def codex_titles():
    root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    titles = {}
    for record in jsonl_records(root / "session_index.jsonl"):
        identity = record.get("id")
        title = single_line_title(record.get("thread_name"))
        if title and isinstance(identity, str) and SESSION_ID.fullmatch(identity):
            titles[identity.lower()] = title
    return titles


def claude_title(identity, project):
    folder = project.replace("\\", "/")
    if folder != "/" and not re.fullmatch(r"[a-zA-Z]:/", folder):
        folder = folder.rstrip("/")
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser() / "projects"
    variants = dict.fromkeys((folder, unicodedata.normalize("NFC", folder))) if folder else ()
    filename = f"{identity}.jsonl"
    preferred = [root / re.sub(r"[^a-zA-Z0-9]", "-", variant) / filename for variant in variants]
    # A resumed chat keeps its original transcript bucket even when the hook reports a new cwd.
    other_buckets = (path for path in root.glob(f"*/{filename}") if path not in preferred)
    for path in chain(preferred, other_buckets):
        try:
            if not path.resolve(strict=True).is_relative_to(root.resolve()):
                continue
        except (OSError, RuntimeError):
            continue
        titles = {}
        for record in jsonl_records(path, (b'"custom-title"', b'"ai-title"')):
            kind = record.get("type")
            if (kind not in ("custom-title", "ai-title") or record.get("sessionId", identity) != identity
                    or record.get("isSidechain") is True):
                continue
            title = single_line_title(record.get(TITLE_FIELDS[kind]))
            if title or kind == "custom-title":
                titles[kind] = title
        title = titles.get("custom-title") or titles.get("ai-title")
        if title:
            return title
    return ""


class ChatTitles:
    def __init__(self):
        self.codex = None
        self.claude = {}

    def display(self, agent, source_session, project, fallback):
        if agent not in ("codex", "claude") or not SESSION_ID.fullmatch(source_session):
            return fallback
        if agent == "codex":
            if self.codex is None:
                self.codex = codex_titles()
            return self.codex.get(source_session.lower()) or fallback
        key = (source_session, project)
        if key not in self.claude:
            self.claude[key] = claude_title(source_session, project)
        return self.claude[key] or fallback
