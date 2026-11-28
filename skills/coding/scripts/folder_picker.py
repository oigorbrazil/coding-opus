"""Open the system's folder dialog on this computer and return the chosen folder.

The editor is a web page, and a browser never hands a page the full path of a folder, so the local
editor server opens the dialog itself: Finder's "choose folder" on macOS, zenity or kdialog on Linux,
and Tk's folder dialog (the modern Windows one) elsewhere. Each runs in its own process, so the
server keeps answering while the dialog is open. Cancelling returns None.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys

TIMEOUT_SECONDS = 600
TITLE = "Escolha a pasta da automação"

TK_SCRIPT = r"""
import sys
import tkinter
from tkinter import filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
chosen = filedialog.askdirectory(parent=root, title=sys.argv[1], initialdir=sys.argv[2] or None, mustexist=True)
root.destroy()
sys.stdout.write(chosen or "")
"""


class PickerError(Exception):
    pass


def commands(initial, title=TITLE):
    """The dialog commands to try on this system, best first."""
    start = str(initial or "")
    if sys.platform == "darwin":
        script = f'POSIX path of (choose folder with prompt "{title}")'
        return [["osascript", "-e", script]]
    found = []
    if sys.platform.startswith("linux"):
        if shutil.which("zenity"):
            found.append(["zenity", "--file-selection", "--directory", "--title", title]
                         + (["--filename", start.rstrip("/") + "/"] if start else []))
        if shutil.which("kdialog"):
            found.append(["kdialog", "--getexistingdirectory", start or str(Path.home()), "--title", title])
    found.append([sys.executable, "-c", TK_SCRIPT, title, start])
    return found


def pick_folder(initial=None, run=subprocess.run):
    """The chosen folder as an absolute path, or None when the person cancels."""
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    problem = None
    for command in commands(initial):
        try:
            done = run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL, env=environment)
        except subprocess.TimeoutExpired:
            return None
        except OSError as error:
            problem = error
            continue
        chosen = (done.stdout or "").strip()
        if done.returncode == 0 and chosen:
            path = Path(chosen).expanduser()
            if path.is_absolute() and path.is_dir():
                return str(path.resolve())
            raise PickerError(f"A pasta escolhida não existe: {chosen}")
        tool = Path(command[0]).name
        if (done.returncode == 0  # Tk prints nothing on cancel
                or (done.returncode == 1 and tool in ("zenity", "kdialog"))
                or (tool == "osascript" and "-128" in (done.stderr or ""))):  # "User canceled. (-128)"
            return None
        problem = (done.stderr or "").strip()[-300:] or f"código {done.returncode}"
    raise PickerError("Não foi possível abrir a janela de pastas neste computador"
                      + (f" ({problem})" if problem else "") + ". Cole o caminho da pasta.")
