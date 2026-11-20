"""Local project registry and read-only review of a task checkout."""

from __future__ import annotations

from contextlib import contextmanager
import difflib
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import subprocess
import threading
import uuid

import orchestrate as runner


MAX_PROJECTS = 200
MAX_FILES = 200
MAX_PATCH_BYTES = 256_000
MAX_NEW_FILE_BYTES = 48_000
MAX_ANNOTATIONS = 100
GIT_TIMEOUT = 12
GIT_DIFF_ARGS = ["--no-ext-diff", "--no-textconv", "--no-color", "--ignore-submodules=all", "--relative"]
GIT_REVISION = re.compile(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?")


class WorkspaceProjectError(ValueError):
    pass


def _git(path: Path, arguments: list[str], limit: int = MAX_PATCH_BYTES):
    """Read a fixed amount of Git output and terminate the command if it exceeds it."""
    executable = Path(runner.resolve_executable("git"))
    if not executable.is_absolute() or runner.is_batch_file(str(executable)):
        raise WorkspaceProjectError("Git executable is unavailable")
    command = [str(executable), "--no-pager", "--literal-pathspecs", "-c",
               "core.hooksPath=" + runner.git_hooks_directory().name, "-c", "core.fsmonitor=false",
               "-c", "core.bigFileThreshold=1m", "-C", str(path), *arguments]
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="", GIT_NO_LAZY_FETCH="1")
    process = runner.start_process(command, path, subprocess.DEVNULL, subprocess.PIPE, subprocess.DEVNULL, env)
    result = []

    def read():
        try:
            result.append(process.stdout.read(limit + 1))
        except OSError:
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        reader.join(GIT_TIMEOUT)
        if reader.is_alive():
            raise WorkspaceProjectError("Git review took too long")
        if not result:
            raise WorkspaceProjectError("Could not read Git output")
        output = result[0]
        if len(output) > limit:
            return 0, output[:limit], True
        return process.wait(timeout=2), output, False
    except subprocess.TimeoutExpired as error:
        raise WorkspaceProjectError("Git review took too long") from error
    finally:
        if process.poll() is None or reader.is_alive():
            runner.stop_process_tree(process)
        runner.close_process_job(process)
        reader.join(1)
        if not reader.is_alive():
            process.stdout.close()


def _checked_git(path: Path, arguments: list[str], limit: int = MAX_PATCH_BYTES):
    code, output, truncated = _git(path, arguments, limit)
    if code != 0:
        raise WorkspaceProjectError("Git could not read this checkout")
    return output, truncated


def _existing_folder(value) -> Path:
    if not isinstance(value, (str, Path)) or not value or any(ord(ch) < 32 for ch in str(value)):
        raise WorkspaceProjectError("Informe uma pasta absoluta válida")
    path = Path(value)
    if not path.is_absolute():
        raise WorkspaceProjectError("Informe o caminho absoluto da pasta")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WorkspaceProjectError("Pasta de projeto indisponível") from error
    if not resolved.is_dir():
        raise WorkspaceProjectError("Pasta de projeto indisponível")
    return resolved


def _canonical_folder(value: str) -> Path:
    resolved = _existing_folder(value)
    if Path(value) != resolved:
        raise WorkspaceProjectError("O caminho cadastrado mudou. Cadastre a pasta atual.")
    return resolved


def _project(id: str, name: str, value: str, source: str):
    try:
        path = _canonical_folder(value)
        git = any((folder / ".git").exists() for folder in (path, *path.parents))
        available = True
    except (WorkspaceProjectError, OSError):
        available = git = False
    return {"id": id, "name": name, "path": value, "source": source, "available": available, "git": git}


def _note_path(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or not value.strip() or any(ord(ch) < 32 for ch in value):
        raise WorkspaceProjectError("Caminho do arquivo inválido")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("..", ".git") for part in path.parts):
        raise WorkspaceProjectError("Use um caminho relativo do projeto")
    if os.name == "nt" and ("\\" in value or ":" in value):
        raise WorkspaceProjectError("Use um caminho relativo do projeto")
    return path.as_posix()


def _note_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise WorkspaceProjectError("Identificador inválido")
    return value


def _project_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9-]{1,50}", value):
        raise WorkspaceProjectError("Identificador de projeto inválido")
    return value


def _disable_filters(path: Path) -> list[str]:
    code, output, truncated = _git(path, ["config", "--null", "--name-only", "--get-regexp",
                                         r"^filter\..*\.(clean|process|smudge|required)$"], 8192)
    if truncated or code not in (0, 1):
        raise WorkspaceProjectError("Não foi possível verificar os filtros do Git")
    keys = sorted(set(output.decode("utf-8").split("\0")) - {""})
    return [arg for key in keys for arg in ("-c", key + ("=false" if key.endswith(".required") else "="))]


def _changed_files(raw: bytes, truncated: bool):
    values = raw.split(b"\0")
    values.pop()
    rows = []
    index = 0
    while index + 1 < len(values) and len(rows) < MAX_FILES:
        status = values[index][:1].decode("ascii", errors="replace")
        origin = values[index + 1].decode("utf-8", errors="replace")
        index += 2
        if status in ("R", "C"):
            if index >= len(values):
                return rows, True
            rows.append({"status": status, "oldPath": origin, "path": values[index].decode("utf-8", errors="replace")})
            index += 1
        else:
            rows.append({"status": status, "path": origin})
    return rows, truncated or index < len(values)


def _new_file_patch(root: Path, raw_path: bytes):
    name = raw_path.decode("utf-8", errors="surrogateescape")
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(part in ("..", ".git") for part in relative.parts):
        return None
    if os.name == "nt" and ("\\" in name or ":" in name):
        return None
    try:
        candidate = runner.safe_destination(root, root.joinpath(*relative.parts))
        if not stat.S_ISREG(candidate.lstat().st_mode):
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(candidate, flags), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode) or candidate.resolve() != candidate:
                return None
            data = handle.read(MAX_NEW_FILE_BYTES + 1)
        if len(data) > MAX_NEW_FILE_BYTES or b"\0" in data or any(ord(ch) < 32 for ch in name):
            return None
        text = data.decode("utf-8")
        name.encode("utf-8")
    except (OSError, ValueError, runner.PlanError):
        return None
    # A missing final newline needs a marker so the next patch header starts on its own line.
    lines = difflib.unified_diff([], text.splitlines(keepends=True), fromfile="/dev/null", tofile="b/" + name)
    return (f"diff --git a/{name} b/{name}\nnew file mode 100644\n" + "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines
    )).encode("utf-8")


class WorkspaceProjects:
    def __init__(self, policy_path: Path):
        self.root = Path(policy_path).parent
        self.remote_home = self.root / "remote-control"
        self.database = self.root / "workspace.sqlite3"
        self.root.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS annotations (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, path TEXT NOT NULL,
                    line INTEGER NOT NULL, side TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS annotations_task ON annotations(task_id, created_at);
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _remote_projects(self):
        try:
            config = runner.read_optional_json(self.remote_home / "config.json")
        except UnicodeError:
            return {}
        projects = config.get("projects") if isinstance(config, dict) else None
        if not isinstance(projects, dict):
            return {}
        return {key: value for key, value in projects.items()
                if re.fullmatch(r"[a-z0-9-]{1,50}", key) and isinstance(value, str)}

    def list(self):
        remote = self._remote_projects()
        with self._db() as db:
            rows = db.execute("SELECT id, name, path FROM projects ORDER BY name COLLATE NOCASE, id").fetchall()
        return [*(_project(row["id"], row["name"], row["path"], "local") for row in rows if row["id"] not in remote),
                *(_project(id, Path(value).name or id, value, "remote") for id, value in sorted(remote.items()))]

    def add(self, path, name=None):
        resolved = _existing_folder(path)
        name = (name.strip() if isinstance(name, str) else name) or resolved.name or str(resolved)
        if not isinstance(name, str) or len(name) > 120 or any(ord(ch) < 32 for ch in name):
            raise WorkspaceProjectError("Nome de projeto inválido")
        remote = self._remote_projects()
        for id, value in remote.items():
            try:
                if _canonical_folder(value) == resolved:
                    return _project(id, resolved.name or id, value, "remote")
            except WorkspaceProjectError:
                pass
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id, name, path FROM projects").fetchall()
            for row in rows:
                if Path(row["path"]) == resolved:
                    return _project(row["id"], row["name"], row["path"], "local")
            if len(rows) >= MAX_PROJECTS:
                raise WorkspaceProjectError("Limite de projetos locais atingido")
            digest = hashlib.sha256(os.fsencode(resolved)).hexdigest()[:24]
            id = "local-" + digest
            used = {*remote, *(row["id"] for row in rows)}
            while id in used:
                id = "local-" + uuid.uuid4().hex
            db.execute("INSERT INTO projects(id, name, path) VALUES (?, ?, ?)", (id, name, str(resolved)))
        return _project(id, name, str(resolved), "local")

    def remove(self, project_id):
        project_id = _project_id(project_id)
        if project_id in self._remote_projects():
            raise WorkspaceProjectError("Remova o projeto remoto pela configuração do servidor")
        with self._db() as db:
            return db.execute("DELETE FROM projects WHERE id = ?", (project_id,)).rowcount == 1

    def resolve(self, project_id):
        project_id = _project_id(project_id)
        with self._db() as db:
            row = db.execute("SELECT path FROM projects WHERE id = ?", (project_id,)).fetchone()
        remote = self._remote_projects().get(project_id)
        if row and remote and Path(row["path"]) != Path(remote):
            raise WorkspaceProjectError("Identificador de projeto conflitante")
        value = remote or (row["path"] if row else None)
        if value is None:
            raise WorkspaceProjectError("Projeto não cadastrado")
        return _canonical_folder(value)

    def diff(self, checkout: Path, base: str | None = None):
        try:
            directory = _canonical_folder(str(checkout))
        except WorkspaceProjectError:
            return self._unavailable("unavailable")
        try:
            repository, inside, _ = _git(directory, ["rev-parse", "--is-inside-work-tree"], 64)
        except (OSError, runner.PlanError):
            return self._unavailable("git-unavailable")
        if repository or inside.strip() != b"true":
            return self._unavailable("not-git")
        if base is not None and (not isinstance(base, str) or not GIT_REVISION.fullmatch(base)):
            raise WorkspaceProjectError("A base da revisão deve ser um hash de commit completo")
        revision = base or "HEAD"
        valid_revision, _, _ = _git(directory, ["rev-parse", "--verify", revision + "^{commit}"], 128)
        if valid_revision:
            if base is not None:
                raise WorkspaceProjectError("A base da revisão não existe neste checkout")
            # Git's implicit empty tree also covers a new repository with no commits.
            object_format, kind, _ = _git(directory, ["rev-parse", "--show-object-format"], 64)
            hash_tree = hashlib.sha256 if object_format == 0 and kind.strip() == b"sha256" else hashlib.sha1
            revision = hash_tree(b"tree 0\0").hexdigest()
        on_branch, branch, _ = _git(directory, ["symbolic-ref", "--quiet", "--short", "HEAD"], 2048)
        safe_args = _disable_filters(directory)
        common = [*safe_args, "diff", *GIT_DIFF_ARGS, "--find-renames", "-l100"]
        raw_files, trimmed_files = _checked_git(directory, [*common, "--name-status", "-z", revision, "--", "."])
        files, truncated = _changed_files(raw_files, trimmed_files)
        patch, trimmed_patch = _checked_git(directory, [*common, revision, "--", "."])
        chunks = [patch]
        length = len(patch)
        others, trimmed_others = _checked_git(directory, ["ls-files", "--others", "--exclude-standard", "-z", "--", "."])
        truncated |= trimmed_patch or trimmed_others
        for path in others.split(b"\0")[:-1]:
            if len(files) >= MAX_FILES:
                truncated = True
                break
            row = {"status": "?", "path": path.decode("utf-8", errors="replace")}
            files.append(row)
            extra = _new_file_patch(directory, path) if length < MAX_PATCH_BYTES else None
            if extra is None or len(extra) + length > MAX_PATCH_BYTES:
                truncated = True
            else:
                chunks.append(extra)
                length += len(extra)
        return {"available": True, "branch": branch.decode("utf-8", errors="replace").strip() if on_branch == 0 else None,
                "files": files, "patch": b"".join(chunks).decode("utf-8", errors="replace"), "truncated": truncated}

    @staticmethod
    def _unavailable(reason):
        return {"available": False, "branch": None, "files": [], "patch": "", "truncated": False, "reason": reason}

    def annotations(self, task_id):
        with self._db() as db:
            rows = db.execute("""SELECT id, path, line, side, body, created_at AS createdAt FROM annotations
                WHERE task_id = ? ORDER BY created_at, id""", (_note_id(task_id),)).fetchall()
        return [dict(row) for row in rows]

    def add_annotation(self, task_id, path, line, body, side="new"):
        task_id = _note_id(task_id)
        path = _note_path(path)
        if type(line) is not int or not 1 <= line <= 10_000_000 or side not in ("old", "new"):
            raise WorkspaceProjectError("Linha de revisão inválida")
        if not isinstance(body, str) or not 1 <= len(body.strip()) <= 8000 or "\0" in body:
            raise WorkspaceProjectError("O comentário precisa ter de 1 a 8000 caracteres")
        note = {"id": uuid.uuid4().hex, "path": path, "line": line, "side": side,
                "body": body.strip(), "createdAt": runner.now_iso()}
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT COUNT(*) FROM annotations WHERE task_id = ?", (task_id,)).fetchone()[0]
            if count >= MAX_ANNOTATIONS:
                raise WorkspaceProjectError("Limite de comentários nesta revisão atingido")
            db.execute("""INSERT INTO annotations(id, task_id, path, line, side, body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (note["id"], task_id, path, line, side, note["body"], note["createdAt"]))
        return note

    def remove_annotation(self, task_id, id):
        with self._db() as db:
            return db.execute("DELETE FROM annotations WHERE task_id = ? AND id = ?",
                              (_note_id(task_id), _note_id(id))).rowcount == 1
