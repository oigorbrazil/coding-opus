"""Local chat selection and native provider turns for the standalone editor."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import uuid
from urllib.parse import quote, urlencode

import orchestrate as runner
from native_chat_history import (PROVIDERS, UUID, chat_home, claude_catalog, codex_catalog,
                                 json_records, messages, project_key)
from workspace_projects import WorkspaceProjectError


@contextmanager
def turn_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab+") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise WorkspaceProjectError("Este chat já está respondendo em outra janela da Coding Opus.") from error
        yield


NESTED_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODING_OPUS_WORKER")


def provider_environment():
    env = os.environ.copy()
    for name in NESTED_ENV:
        env.pop(name, None)
    return env


def open_desktop_url(agent, url):
    try:
        if os.name == "nt":
            os.startfile(url)
            return True
        if sys.platform == "darwin":
            return subprocess.run(["open", url], capture_output=True, timeout=6).returncode == 0
        if shutil.which("xdg-mime") and shutil.which("xdg-open"):
            if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                return False
            handler = subprocess.run(["xdg-mime", "query", "default", f"x-scheme-handler/{agent}"],
                                     capture_output=True, timeout=5)
            if handler.returncode == 0 and handler.stdout.strip():
                subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def open_native_chat(agent, cwd, session):
    if not session and not cwd.is_dir():
        raise WorkspaceProjectError("A pasta do projeto está indisponível.")
    target = None
    if agent == "codex":
        target = (f"codex://threads/{session}" if session
                  else "codex://threads/new?" + urlencode({"path": str(cwd)}, quote_via=quote))
    elif not session:
        target = "claude://code/new?" + urlencode({"folder": str(cwd)}, quote_via=quote)
    if target and open_desktop_url(agent, target):
        return {"target": "desktop"}
    if not cwd.is_dir():
        raise WorkspaceProjectError("A pasta do projeto está indisponível.")
    args = runner.launch_command(runner.resolve_executable(agent))
    env = provider_environment()
    if agent == "claude" and session:
        desktop = [*args, "--desktop", "--resume", session]
        runner.refuse_batch_arguments(desktop)
        result = subprocess.run(desktop, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        diagnostic = ((result.stdout or b"") + (result.stderr or b"")).decode("utf-8", errors="replace").lower()
        if re.search(r"\bsession\b[^\r\n]*\b(?:already (?:open|running|active)|still running|open in another terminal)\b", diagnostic):
            raise WorkspaceProjectError("O Claude Code já tem esta sessão aberta. Encerre a sessão ativa para retomá-la no Desktop.")
        if result.returncode == 0 and "claude.com/download" not in diagnostic and "claude.ai/download" not in diagnostic:
            return {"target": "desktop"}
    if session:
        args += ["resume" if agent == "codex" else "--resume", session]
    runner.refuse_batch_arguments(args)
    if os.name == "nt":
        subprocess.Popen(args, cwd=cwd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        clean = ["env", *[part for name in NESTED_ENV for part in ("-u", name)], *args]
        runner.launch_terminal(runner.terminal_launcher(), "Codex" if agent == "codex" else "Claude Code", clean, cwd)
    return {"target": "terminal"}


def provider_turn(agent, cwd, prompt, session):
    launch = runner.launch_command(runner.resolve_executable(agent))
    with TemporaryDirectory(prefix="coding-opus-chat-") as folder:
        output = Path(folder) / "response.md"
        if agent == "codex":
            args = [*launch, "exec", "--sandbox", "workspace-write"]
            if session:
                args.append("resume")
            args += ["--json", "--output-last-message", str(output), "--skip-git-repo-check"]
            args += [session, "-"] if session else ["-"]
        else:
            args = [*launch, "--print", "--output-format", "stream-json", "--verbose", "--permission-mode", "default"]
            args += ["--resume", session] if session else ["--session-id", str(uuid.uuid4())]
        runner.refuse_batch_arguments(args)
        process = subprocess.run(args, cwd=cwd, input=prompt.encode("utf-8"), capture_output=True, env=provider_environment(),
                                 timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if process.returncode:
            raise WorkspaceProjectError(f"O CLI {agent} encerrou com código {process.returncode}. Confira a sessão e o login no CLI.")
        identity, text = session, ""
        for event in json_records(process.stdout.splitlines()):
            kind = event.get("type")
            if agent == "codex" and kind == "thread.started":
                identity = event.get("thread_id")
            if agent == "claude" and kind == "result" and not event.get("is_error"):
                identity, text = event.get("session_id"), event.get("result")
        if agent == "codex" and output.is_file():
            text = output.read_text(encoding="utf-8")
        if not isinstance(identity, str) or not re.fullmatch(UUID, identity, re.I) or (session and identity != session):
            raise WorkspaceProjectError("O CLI não retornou a sessão esperada.")
        if not isinstance(text, str) or not text.strip():
            raise WorkspaceProjectError("O CLI não retornou uma resposta de texto.")
        return identity, text.strip()[:40000]


class ChatWorkspace:
    def __init__(self, projects, run=provider_turn, open_chat=open_native_chat):
        self.projects = projects
        self.run = run
        self.open_chat = open_chat
        self.active = set()
        self.lock = threading.Lock()

    def catalog(self):
        indexed = {}
        failures = []
        for agent, collect in (("codex", codex_catalog), ("claude", claude_catalog)):
            try:
                indexed.update(((agent, item["id"]), item) for item in collect(chat_home(agent)))
            except (OSError, sqlite3.Error):
                failures.append(agent)
        projects = {}
        for item in indexed.values():
            directory = item["cwd"]
            projects.setdefault(item["project"], {"id": item["project"], "name": Path(directory).name or directory,
                                                   "path": directory})
        for item in self.projects.list():
            key = project_key(item["path"])
            projects[key] = {"id": key, "name": item["name"], "path": item["path"]}
        return projects, indexed, failures

    def action(self, request):
        try:
            return {"ok": True, "value": self._action(request)}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "O CLI excedeu o tempo de resposta. Confira o histórico antes de tentar novamente."}
        except (OSError, sqlite3.Error, WorkspaceProjectError, runner.PlanError, TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    def _action(self, request):
        action = request.get("action")
        added = self.projects.add(request.get("path")) if action == "add-project" else None
        projects, indexed, failures = self.catalog()
        if action in ("list", "add-project"):
            return {"projects": sorted(projects.values(), key=lambda item: item["name"].casefold()),
                    "chats": [{key: item[key] for key in ("id", "title", "project", "agent", "updatedAt")}
                              for item in sorted(indexed.values(), key=lambda item: -item["updatedAt"])],
                    "unavailable": failures, **({"added": project_key(added["path"])} if added else {})}
        agent, project, identity = request.get("agent"), request.get("project"), request.get("id")
        if agent not in PROVIDERS or not isinstance(project, str) or project not in projects:
            raise WorkspaceProjectError("Escolha um projeto e uma IA da lista.")
        thread = None
        if identity is not None:
            thread = indexed.get((agent, identity)) if isinstance(identity, str) else None
            if not thread or thread["project"] != project:
                raise WorkspaceProjectError("O chat não está disponível para este projeto e IA.")
        if action == "read" and thread:
            before = request.get("before")
            if before is not None and (type(before) is not int or before < 1):
                raise WorkspaceProjectError("Posição do histórico inválida.")
            return messages(thread, before)
        if action == "open":
            cwd = Path(thread["cwd"] if thread else projects[project]["path"])
            return self.open_chat(agent, cwd, identity)
        if action != "send":
            raise WorkspaceProjectError("Ação de chat desconhecida.")
        prompt = request.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 24000:
            raise WorkspaceProjectError("Escreva uma mensagem de até 24.000 caracteres.")
        cwd = Path(thread["cwd"] if thread else projects[project]["path"])
        if not cwd.is_dir():
            raise WorkspaceProjectError("A pasta do projeto está indisponível.")
        key = identity or uuid.uuid5(uuid.NAMESPACE_URL, project).hex
        lock_path = self.projects.root / "chat-turns" / f"{agent}-{key}.lock"
        with turn_lock(lock_path):
            with self.lock:
                self.active.add(lock_path)
            try:
                identity, answer = self.run(agent, cwd, prompt.strip(), identity)
            finally:
                with self.lock:
                    self.active.discard(lock_path)
        return {"id": identity, "text": answer}
