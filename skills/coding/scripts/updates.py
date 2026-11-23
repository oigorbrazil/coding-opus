"""Check whether the installed Coding Opus skill matches the latest one on GitHub.

The installed copy does not record the commit it came from, and the version number does not change
on every commit, so this compares content: GitHub's tree for skills/coding on main lists a git blob
hash per file, and the same hash is computed for each installed file. Only public data goes out
(the repository name), with a generic User-Agent.

`apply` updates in place: it downloads only the files that differ, from that exact commit, checks
each one against GitHub's blob hash before anything is written, then replaces them one by one.
A Claude Code plugin copy or a git checkout is left to its own tools.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "oigorbrazil/coding-opus"
BRANCH = "main"
PREFIX = "skills/coding/"
API = "https://api.github.com/repos/" + REPOSITORY
RAW = "https://raw.githubusercontent.com/" + REPOSITORY
SKILL_ROOT = Path(__file__).resolve().parent.parent
UPDATE_HOWTO = (
    "Para atualizar, rode de novo `npx skills add oigorbrazil/coding-opus --skill coding -g`; "
    "com o plugin do Claude Code, atualize o marketplace em /plugin."
)


class UpdateError(Exception):
    pass


def blob_hash(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def same_file(data, remote_sha):
    """Equal to GitHub's blob, also when a Windows checkout turned LF into CRLF."""
    if blob_hash(data) == remote_sha:
        return True
    return b"\0" not in data and b"\r\n" in data and blob_hash(data.replace(b"\r\n", b"\n")) == remote_sha


def fetch_json(url, timeout=10):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "coding-opus-update-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            raise UpdateError("O GitHub limitou as consultas por agora. Tente de novo em alguns minutos.") from error
        raise UpdateError(f"O GitHub respondeu com erro {error.code}.") from error
    except (OSError, ValueError) as error:
        raise UpdateError("Não foi possível falar com o GitHub. Confira a conexão e tente de novo.") from error


def local_version(root=SKILL_ROOT):
    try:
        match = re.search(r'^\s*version:\s*"?([^"\n]+)"?', (root / "SKILL.md").read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        return None
    return match.group(1).strip() if match else None


def fetch_bytes(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "coding-opus-update-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise UpdateError(f"O GitHub respondeu com erro {error.code} ao baixar um arquivo.") from error
    except OSError as error:
        raise UpdateError("Não foi possível baixar a atualização. Confira a conexão e tente de novo.") from error


def install_kind(root=SKILL_ROOT):
    """'skills' for a copy this can update; otherwise who owns the files."""
    resolved = Path(root).resolve()
    if "plugins" in [part.lower() for part in resolved.parts] and ".claude" in [part.lower() for part in resolved.parts]:
        return "plugin"
    if any((folder / ".git").exists() for folder in (resolved, *resolved.parents)):
        return "git"
    return "skills"


def scan(root, fetch):
    commit = fetch(f"{API}/commits/{BRANCH}")
    commit = fetch(f"{API}/commits/{BRANCH}")
    try:
        sha = commit["sha"]
        tree_sha = commit["commit"]["tree"]["sha"]
        date = commit["commit"]["committer"]["date"]
        title = commit["commit"]["message"].splitlines()[0][:120]
    except (KeyError, TypeError, IndexError) as error:
        raise UpdateError("O GitHub respondeu num formato inesperado.") from error
    tree = fetch(f"{API}/git/trees/{tree_sha}?recursive=1")
    if not isinstance(tree, dict) or tree.get("truncated"):
        raise UpdateError("A lista de arquivos do GitHub veio incompleta.")
    changed, missing, remote = [], [], {}
    for item in tree.get("tree", []):
        path = item.get("path", "")
        if item.get("type") != "blob" or not path.startswith(PREFIX):
            continue
        relative = path[len(PREFIX):]
        remote[relative] = (item.get("sha"), item.get("mode"))
        try:
            data = (root / relative).read_bytes()
        except OSError:
            missing.append(relative)
            continue
        if not same_file(data, item.get("sha")):
            changed.append(relative)
    report = {
        "upToDate": not changed and not missing,
        "version": local_version(root),
        "latest": {"commit": sha[:7], "date": date, "title": title},
        "changed": sorted(changed),
        "missing": sorted(missing),
        "howto": UPDATE_HOWTO,
        "canApply": install_kind(root) == "skills",
    }
    return report, sha, remote


def check(root=SKILL_ROOT, fetch=fetch_json):
    """Compare the installed skill with GitHub. Returns a JSON-ready report."""
    return scan(root, fetch)[0]


def target_path(root, relative):
    parts = relative.split("/")
    if not relative or any(part in ("", ".", "..") for part in parts) or ":" in relative or "\\" in relative:
        raise UpdateError(f"Caminho inválido na atualização: {relative}")
    current = Path(root)
    for part in parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise UpdateError(f"A atualização não segue links: {current}")
    return current


def write_file(path, data, executable):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else (0o755 if executable else 0o644)
    descriptor, temporary = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def apply(root=SKILL_ROOT, fetch=fetch_json, download=fetch_bytes):
    """Bring the installed skill to GitHub's latest commit. Returns the files it replaced."""
    kind = install_kind(root)
    if kind == "plugin":
        raise UpdateError("Esta cópia é o plugin do Claude Code: atualize o marketplace em /plugin.")
    if kind == "git":
        raise UpdateError("Esta cópia é um repositório git: atualize com git pull.")
    report, commit, remote = scan(root, fetch)
    paths = report["changed"] + report["missing"]
    downloads = {}
    for relative in paths:  # everything is checked before anything is written
        target = target_path(root, relative)
        sha, mode = remote[relative]
        data = download(f"{RAW}/{commit}/{PREFIX}{urllib.parse.quote(relative)}")
        if blob_hash(data) != sha:
            raise UpdateError(f"O arquivo baixado não confere com o GitHub: {relative}. Nada foi alterado.")
        downloads[relative] = (target, data, mode == "100755")
    for relative, (target, data, executable) in downloads.items():
        try:
            write_file(target, data, executable)
        except OSError as error:
            raise UpdateError(f"Não foi possível gravar {relative}: {error}. Tente de novo.") from error
    return {"updated": sorted(paths), "version": local_version(root), "latest": report["latest"]}


if __name__ == "__main__":
    try:
        print(json.dumps(check(), ensure_ascii=False, indent=2))
    except UpdateError as error:
        print(str(error))
        raise SystemExit(1)
