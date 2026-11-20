"""Install and open the optional Windows Playbooks application."""

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


SCRIPT = Path(__file__).resolve()
ASSET = SCRIPT.parent.parent / "assets" / "windows-editor.zip"
NAME = "Coding Opus.exe"
FILES = {
    NAME, "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
    "LICENSE.txt", *(f"runtimes/win-{arch}/native/WebView2Loader.dll" for arch in ("x86", "x64", "arm64")),
}


class DesktopError(Exception):
    pass


def releases():
    return Path(os.environ["LOCALAPPDATA"]) / "Coding Opus" / "Editor"


def supported():
    return os.name == "nt" and bool(os.environ.get("LOCALAPPDATA"))


def interactive():
    return supported() and os.environ.get("ORCA_BACKGROUND_LAUNCH") != "1"


def installed():
    if not supported():
        return None
    try:
        release = (releases() / "active").read_text(encoding="ascii").strip()
        if len(release) != 24 or not all(letter in "0123456789abcdef" for letter in release):
            return None
        binary = releases() / release / NAME
        if binary.is_file() and binary.with_name("launcher.json").is_file():
            return binary
    except OSError:
        pass
    return None


def detach(args):
    return subprocess.Popen(
        [str(arg) for arg in args],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
    )


def atomic_write(path, content):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".update-")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def unpack(package, target):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        if set(archive.namelist()) != FILES or len(archive.namelist()) != len(FILES):
            raise DesktopError("O pacote do editor do Windows está incompleto.")
        for file in FILES:
            path = target / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(file))


def command(binary, flag):
    result = subprocess.run([str(binary), flag], capture_output=True, encoding="utf-8",
                            errors="replace", creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
    if result.returncode:
        message = result.stderr.strip()
        raise DesktopError(message or f"O aplicativo encerrou com código {result.returncode}.")


@contextmanager
def registration():
    import msvcrt

    root = releases()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "registration.lock").open("a+b") as lock:
        locked = False
        try:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            locked = True
        except OSError:
            pass
        try:
            yield locked
        finally:
            if locked:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def install(policy, *, open_on_first_install=False):
    open_on_completion = open_on_first_install and interactive() and not installed()
    package = ASSET.read_bytes()
    release = hashlib.sha256(package).hexdigest()[:24]
    root = releases()
    target = root / release
    if not target.is_dir():
        with tempfile.TemporaryDirectory(prefix=".install-", dir=root) as folder:
            stage = Path(folder) / "release"
            unpack(package, stage)
            os.replace(stage, target)
    binary = target / NAME
    try:
        command(binary, "--check-runtime")
    except DesktopError as error:
        raise DesktopError("O aplicativo precisa do Microsoft WebView2 Runtime. " + str(error)) from error
    config = {"python": sys.executable, "script": str(SCRIPT.with_name("editor_server.py")), "policy": str(policy)}
    atomic_write(target / "launcher.json", json.dumps(config, ensure_ascii=False).encode("utf-8"))
    command(binary, "--register")
    atomic_write(root / "active", release.encode("ascii"))
    if open_on_completion:
        try:
            detach([binary])
        except OSError as error:
            raise DesktopError(f"O aplicativo foi instalado, mas não pôde ser aberto: {error}") from error
    return binary


def ensure_installed(policy=None, *, open_on_first_install=False):
    if not supported():
        return None
    binary = installed()
    if binary:
        return binary
    try:
        if not ASSET.is_file():
            return None
        with registration() as locked:
            binary = installed()
            if binary or not locked:
                return binary
            if policy is None:
                from orchestrate import default_policy_path
                policy = default_policy_path().expanduser().resolve()
            return install(policy, open_on_first_install=open_on_first_install)
    except (OSError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        raise DesktopError(str(error)) from error


def open_editor(url, policy):
    """Install the app if needed, then start it for the current editor server."""
    if not interactive():
        return False
    try:
        binary = ensure_installed(policy)
        if binary:
            detach([binary, "--url", url])
            return True
    except (DesktopError, OSError):
        pass
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "smoke"))
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args()
    if not supported():
        print(json.dumps({"available": False, "installed": False}))
        return 0
    binary = installed()
    if args.action == "status":
        print(json.dumps({"available": ASSET.is_file(), "installed": bool(binary), "app": str(binary) if binary else None}))
        return 0
    if args.action == "smoke":
        if not binary:
            raise DesktopError("O aplicativo do Windows ainda não foi instalado.")
        command(binary, "--smoke")
        print(json.dumps({"playbooks": True}))
        return 0
    from orchestrate import default_policy_path
    policy = (args.policy or default_policy_path()).expanduser().resolve()
    with registration() as locked:
        if not locked:
            raise DesktopError("Já existe uma instalação da Opus em andamento.")
        binary = install(policy, open_on_first_install=True)
    print(json.dumps({"installed": True, "app": str(binary)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DesktopError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        sys.stderr.reconfigure(encoding="utf-8")
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
