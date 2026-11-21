"""Install and open the optional Coding Opus application.

Windows gets a small WebView2 app (assets/windows-editor.zip). macOS and Linux get a launcher, a
`Coding Opus.app` in ~/Applications or a `coding-opus.desktop` entry, that starts the editor server
and shows the page as an app window of Chrome, Edge, Chromium or Brave (`--app`); without one of
those browsers the page opens in the default browser.
"""

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile


SCRIPT = Path(__file__).resolve()
ASSET = SCRIPT.parent.parent / "assets" / "windows-editor.zip"
ICON = SCRIPT.parent.parent / "assets" / "coding-opus-app.png"
NAME = "Coding Opus.exe"
APP_NAME = "Coding Opus"
MAC_BROWSERS = (
    "Google Chrome.app/Contents/MacOS/Google Chrome",
    "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "Chromium.app/Contents/MacOS/Chromium",
    "Brave Browser.app/Contents/MacOS/Brave Browser",
)
LINUX_BROWSERS = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
    "microsoft-edge-stable", "brave-browser",
)
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


def unix_desktop():
    """macOS or Linux with a local desktop session (not over SSH)."""
    if any(os.environ.get(key) for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")):
        return None
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "linux"
    return None


def interactive():
    return (supported() or bool(unix_desktop())) and os.environ.get("ORCA_BACKGROUND_LAUNCH") != "1"


def app_browser(kind=None):
    """A Chromium-based browser that can open a page as an app window, or None."""
    kind = kind or unix_desktop()
    if kind == "mac":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            for relative in MAC_BROWSERS:
                if (root / relative).is_file():
                    return str(root / relative)
        return None
    if kind == "linux":
        for name in LINUX_BROWSERS:
            found = shutil.which(name)
            if found:
                return found
    return None


def launcher_command(policy):
    return [sys.executable, str(SCRIPT.with_name("editor_server.py")), "--policy", str(policy), "--launch"]


def desktop_exec(argv):
    """Quote an argv for a .desktop Exec key (freedesktop rules: double quotes, escape \\ \" ` $)."""
    def quote(arg):
        arg = arg.replace("%", "%%")  # a lone % starts a field code such as %f
        if arg and not any(char in arg for char in ' \t\n"\'\\><~|&;$*?#()`'):
            return arg
        escaped = "".join("\\" + char if char in '"`$\\' else char for char in arg)
        return f'"{escaped}"'
    return " ".join(quote(arg) for arg in argv)


def unix_launcher_files(kind, policy):
    """The files that make up the launcher, as {path: (bytes, mode)}."""
    command = launcher_command(policy)
    if kind == "mac":
        app = Path.home() / "Applications" / f"{APP_NAME}.app" / "Contents"
        script = "#!/bin/sh\n# Starts the Coding Opus editor; rewritten by desktop_editor.py.\nexec " + \
            " ".join(shlex.quote(arg) for arg in command) + "\n"
        info = {
            "CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME, "CFBundleIdentifier": "com.codingopus.editor",
            "CFBundleExecutable": "coding-opus", "CFBundleIconFile": "AppIcon", "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0", "LSUIElement": True,
        }
        return {
            app / "Info.plist": (plistlib.dumps(info), 0o644),
            app / "MacOS" / "coding-opus": (script.encode("utf-8"), 0o755),
        }
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    icon = data / "icons" / "hicolor" / "128x128" / "apps" / "coding-opus.png"
    entry = "\n".join([
        "[Desktop Entry]", "Type=Application", f"Name={APP_NAME}",
        "Comment=Coding Opus playbooks, second brain and memory", f"Exec={desktop_exec(command)}",
        f"Icon={icon}", "Terminal=false", "Categories=Development;", "",
    ])
    files = {data / "applications" / "coding-opus.desktop": (entry.encode("utf-8"), 0o644)}
    if ICON.is_file():
        files[icon] = (ICON.read_bytes(), 0o644)
    return files


def unix_launcher_path(kind):
    if kind == "mac":
        return Path.home() / "Applications" / f"{APP_NAME}.app"
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data / "applications" / "coding-opus.desktop"


def install_unix_launcher(kind, policy):
    """Write the launcher, rewriting only files whose content changed. Returns its path."""
    changed = False
    for path, (content, mode) in unix_launcher_files(kind, policy).items():
        try:
            current = path.read_bytes()
        except OSError:
            current = None
        if current != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, content)
            changed = True
        os.chmod(path, mode)
    if kind == "mac" and changed and ICON.is_file():
        resources = unix_launcher_path(kind) / "Contents" / "Resources"
        resources.mkdir(parents=True, exist_ok=True)
        try:
            # sips ships with macOS and turns the PNG into the bundle icon.
            subprocess.run(["sips", "-s", "format", "icns", str(ICON), "--out", str(resources / "AppIcon.icns")],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    if kind == "linux" and changed and shutil.which("update-desktop-database"):
        try:
            subprocess.run(["update-desktop-database", str(unix_launcher_path(kind).parent)],
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    return unix_launcher_path(kind)


def installed():
    if not supported():
        kind = unix_desktop()
        path = unix_launcher_path(kind) if kind else None
        return path if path and path.exists() else None
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
    if os.name != "nt":
        return subprocess.Popen([str(arg) for arg in args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
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
        kind = unix_desktop()
        if not kind:
            return None
        if policy is None:
            from orchestrate import default_policy_path
            policy = default_policy_path().expanduser().resolve()
        try:
            return install_unix_launcher(kind, policy)
        except OSError as error:
            raise DesktopError(str(error)) from error
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
    kind = unix_desktop() if not supported() else None
    if kind:
        try:
            ensure_installed(policy)
        except DesktopError:
            pass
        browser = app_browser(kind)
        if not browser:
            return False
        try:
            detach([browser, f"--app={url}", "--new-window"])
            return True
        except OSError:
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
        kind = unix_desktop()
        if not kind or args.action == "smoke":
            print(json.dumps({"available": bool(kind), "installed": bool(installed())}))
            return 0
        path = installed()
        if args.action == "status":
            print(json.dumps({"available": True, "installed": bool(path), "app": str(path) if path else None,
                              "browser": app_browser(kind)}))
            return 0
        from orchestrate import default_policy_path
        policy = (args.policy or default_policy_path()).expanduser().resolve()
        path = install_unix_launcher(kind, policy)
        print(json.dumps({"installed": True, "app": str(path), "browser": app_browser(kind)}))
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
