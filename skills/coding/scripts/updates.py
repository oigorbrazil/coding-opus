"""Check whether the installed Coding Opus skill matches the latest one on GitHub.

The installed copy does not record the commit it came from, and the version number does not change
on every commit, so this compares content: GitHub's tree for skills/coding on main lists a git blob
hash per file, and the same hash is computed for each installed file. Read-only: nothing is
downloaded or changed. Only public data goes out (the repository name), with a generic User-Agent.
"""

import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

REPOSITORY = "oigorbrazil/coding-opus"
BRANCH = "main"
PREFIX = "skills/coding/"
API = "https://api.github.com/repos/" + REPOSITORY
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


def check(root=SKILL_ROOT, fetch=fetch_json):
    """Compare the installed skill with GitHub. Returns a JSON-ready report."""
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
    changed, missing = [], []
    for item in tree.get("tree", []):
        path = item.get("path", "")
        if item.get("type") != "blob" or not path.startswith(PREFIX):
            continue
        relative = path[len(PREFIX):]
        try:
            data = (root / relative).read_bytes()
        except OSError:
            missing.append(relative)
            continue
        if not same_file(data, item.get("sha")):
            changed.append(relative)
    return {
        "upToDate": not changed and not missing,
        "version": local_version(root),
        "latest": {"commit": sha[:7], "date": date, "title": title},
        "changed": sorted(changed),
        "missing": sorted(missing),
        "howto": UPDATE_HOWTO,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(check(), ensure_ascii=False, indent=2))
    except UpdateError as error:
        print(str(error))
        raise SystemExit(1)
