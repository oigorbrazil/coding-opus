#!/usr/bin/env python3
"""Coding Opus — local server for the playbooks editor.

`orchestrate.py editor` starts this in the background. It serves `assets/editor.html` (built from
the repository's `editor/` folder) on 127.0.0.1 and lets that page read and save the playbooks file the
skill plans with. Every API call needs the one-time token from the page URL. The server stops on
its own a little after the page is closed. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socketserver
from pathlib import Path
from typing import Any, Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orchestrate  # noqa: E402  (same folder; imported for its playbook rules)
from usage_refresh import UsageRefresh
from playbook_generation import PlaybookGenerator
from account_management import AccountManager
from workspace_api import WorkspaceApi
from knowledge_library import KnowledgeLibrary
from automations import AutomationError, Automations
from remote_control import (RemoteError, manage_projects, read_config, remote_status, restart_if_running,
    revoke_device, server_call, service_action, set_panel_address, tailscale_info)

PAGE = Path(__file__).resolve().parent.parent / "assets" / "editor.html"
MAX_BODY = 1 << 20
# Stop when the page has not pinged for this long (it pings every 20 s), or if it never connects.
IDLE_AFTER_PING = 90
IDLE_BEFORE_FIRST_PING = 600


class LocalHTTPServer(ThreadingHTTPServer):
    """A loopback server that skips HTTPServer's reverse DNS lookup of its own address.

    `HTTPServer.server_bind` calls `socket.getfqdn(host)` only to fill `server_name`; on some
    macOS machines resolving 127.0.0.1 takes tens of seconds and delays every start.
    """

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port


class EditorState:
    def __init__(self, policy_path: Path, token: str) -> None:
        self.policy_path = policy_path
        self.token = token
        self.last_ping = 0.0
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.remote_lock = threading.Lock()
        self.usage_refresh = UsageRefresh(policy_path)
        self.generator = PlaybookGenerator(policy_path, usage=self.usage_refresh)
        self.account_manager = AccountManager(policy_path)
        self.workspace = WorkspaceApi(policy_path)
        self.library = KnowledgeLibrary(policy_path)

    def remote_home(self) -> Path:
        return self.policy_path.resolve().parent / "remote-control"

    def open_remote_panel(self) -> Dict[str, str]:
        """Start the panel and open it on this computer, already paired through a single-use code."""
        home = self.remote_home()
        with self.remote_lock:
            if not (home / "config.json").is_file():
                return {"status": "setup-required"}
            try:
                port = service_action(home, "start")["port"]
                code = server_call(home, "POST", "/pair/new", {"kind": "pc"})["code"]
                opened = (isinstance(port, int) and 1024 <= port <= 65535 and isinstance(code, str)
                          and code.isalnum() and webbrowser.open(f"http://127.0.0.1:{port}/#pair={code}"))
            except (OSError, ValueError, KeyError, TypeError, RemoteError, webbrowser.Error):
                opened = False
        return {"status": "opened" if opened else "unavailable"}

    def remote(self) -> Dict[str, Any]:
        try:
            return {"ok": True, "remote": remote_status(self.remote_home())}
        except (OSError, ValueError, KeyError, RemoteError) as error:
            return {"ok": False, "error": str(error)}

    def remote_action(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Projects, writing and the service, from this computer only (the editor never leaves 127.0.0.1)."""
        home = self.remote_home()
        action = body.get("action")
        with self.remote_lock:
            try:
                if action in ("start", "stop"):
                    if (home / "config.json").is_file():
                        service_action(home, action)
                    return {"ok": True, "remote": remote_status(home)}
                if action == "restart":
                    restart_if_running(home)
                    return {"ok": True, "remote": remote_status(home)}
                if action == "detect":
                    port = (read_config(home) or {}).get("port", 8769)
                    return {"ok": True, "tailscale": tailscale_info(port)}
                if action == "revoke":
                    revoke_device(home, body.get("id"))
                    return {"ok": True, "remote": remote_status(home)}
                if action == "panel":
                    set_panel_address(home, body.get("address"))
                    restart_if_running(home)  # origins are read when the panel starts
                    return {"ok": True, "remote": remote_status(home)}
                status = manage_projects(home, action, path=body.get("path"), key=body.get("key"),
                                         allow_write=body.get("allowWrite"))
                restart_if_running(home)  # the panel reads its projects when it starts
                return {"ok": True, "remote": {**status, "running": remote_status(home)["running"]}}
            except (OSError, ValueError, KeyError, RemoteError) as error:
                return {"ok": False, "error": str(error)}

    def automations(self) -> Dict[str, Any]:
        home = self.remote_home()
        try:
            status = remote_status(home)
            items = Automations(home).listed() if status["configured"] else []
            return {"ok": True, "automations": items, "running": status["running"], "allowWrite": status["allow_write"],
                    "projects": [project["key"] for project in status["projects"] if project["exists"]]}
        except (OSError, ValueError, KeyError, RemoteError, AutomationError, sqlite3.Error) as error:
            return {"ok": False, "error": str(error)}

    def automation_action(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Create, edit, remove, switch, run now or read history. Only from this computer."""
        home = self.remote_home()
        action, automation_id = body.get("action"), body.get("id")
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        try:
            store = Automations(home)
            if action == "create":
                store.create(data)
            elif action == "edit":
                store.edit(str(automation_id), data)
            elif action == "remove":
                store.remove(str(automation_id))
            elif action == "run":
                if not service_action(home, "status")["running"]:
                    raise AutomationError("Ligue o serviço na aba Controle remoto: é ele que executa as automações.")
                store.request_run(str(automation_id))
            elif action == "runs":
                return {"ok": True, "runs": store.runs(str(automation_id), 30)}
            else:
                raise AutomationError("Ação desconhecida.")
        except (OSError, ValueError, KeyError, TypeError, RemoteError, AutomationError, sqlite3.Error) as error:
            return {"ok": False, "error": str(error)}
        return self.automations()

    def playbooks(self) -> Dict[str, Any]:
        user = orchestrate.user_playbooks_path(self.policy_path)
        effective = orchestrate.effective_playbooks_path(self.policy_path)
        try:
            backup = user.with_name(user.name + ".bak").read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            backup = None
        return {
            "backupText": backup,
            "text": orchestrate.read_playbooks(effective),
            "path": str(user),
            "custom": user.is_file(),
        }

    def stamp(self) -> int:
        path = orchestrate.effective_playbooks_path(self.policy_path)
        try:
            return int(path.stat().st_mtime * 1000)
        except OSError:
            return 0

    def accounts(self) -> Dict[str, Any]:
        try:
            return self.account_manager.snapshot()
        except orchestrate.PlanError as error:
            return {"ok": False, "error": str(error)}

    def models(self) -> Dict[str, Any]:
        try:
            return {"ok": True, "catalog": orchestrate.model_catalog(self.policy_path)}
        except (OSError, orchestrate.PlanError) as error:
            return {"ok": False, "error": str(error)}

    def clis(self) -> Dict[str, Any]:
        try:
            return {"ok": True, "clis": orchestrate.detect_clis()}
        except (OSError, orchestrate.PlanError) as error:
            return {"ok": False, "error": str(error)}

    def usage(self) -> Dict[str, Any]:
        try:
            _, settings = orchestrate.loaded_playbooks(self.policy_path)
            providers = settings.get("providers", ["claude", "codex"])
            return {"ok": True, "value": self.usage_refresh.refresh(providers)}
        except (OSError, orchestrate.PlanError) as error:
            return {"ok": False, "error": str(error)}

    def order_accounts(self, provider: Any, names: Any) -> Dict[str, Any]:
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            return {"ok": False, "error": "names must be a list of account names"}
        try:
            with self.lock:
                orchestrate.order_accounts(self.policy_path, provider, names)
        except orchestrate.PlanError as error:
            return {"ok": False, "error": str(error)}
        return self.accounts()

    def save(self, text: str) -> Dict[str, Any]:
        if not text.strip() or len(text.encode("utf-8")) > MAX_BODY:
            return {"ok": False, "error": "empty or too large"}
        try:
            data = orchestrate.parse_playbooks_yaml(text)
            errors = orchestrate.playbook_structure_errors(data)
        except orchestrate.PlanError as error:
            return {"ok": False, "error": str(error)}
        if errors:
            return {"ok": False, "error": "; ".join(errors)}
        path = orchestrate.user_playbooks_path(self.policy_path)
        with self.lock:
            if path.is_file():
                current = path.read_text(encoding="utf-8")
                if current != text:
                    orchestrate.atomic_write_text(path.with_name(path.name + ".bak"), current)
            path.parent.mkdir(parents=True, exist_ok=True)
            orchestrate.atomic_write_text(path, text)
        return {"ok": True, "playbooks": self.playbooks()}


def make_handler(state: EditorState, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:  # keep the background process silent
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

        def _guard(self, api: bool) -> bool:
            # Host check blocks DNS rebinding; the token keeps other local pages out of the API.
            if self.headers.get("Host") not in allowed_hosts:
                self._json(403, {"error": "forbidden host"})
                return False
            if api and self.headers.get("X-Coding-Opus-Token") != state.token:
                self._json(401, {"error": "bad token"})
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                if self._guard(api=False):
                    self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                return
            if not self._guard(api=True):
                return
            try:
                if path == "/api/playbooks":
                    self._json(200, state.playbooks())
                elif path == "/api/models":
                    self._json(200, state.models())
                elif path == "/api/clis":
                    self._json(200, state.clis())
                elif path == "/api/remote":
                    self._json(200, state.remote())
                elif path == "/api/automations":
                    self._json(200, state.automations())
                elif path == "/api/accounts":
                    self._json(200, state.accounts())
                elif path == "/api/usage":
                    self._json(200, state.usage())
                elif path == "/api/stamp":
                    self._json(200, {"stamp": state.stamp()})
                elif path == "/api/ping":
                    state.last_ping = time.monotonic()
                    self._json(200, {"ok": True})
                else:
                    self._json(404, {"error": "not found"})
            except orchestrate.PlanError as error:
                self._json(500, {"error": str(error)})

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard(api=True):
                return
            path = self.path.split("?", 1)[0]
            if path not in ("/api/playbooks", "/api/accounts/order", "/api/playbooks/generate",
                            "/api/accounts/manage", "/api/workspace", "/api/library", "/api/remote/open",
                            "/api/remote", "/api/automations"):
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._json(400, {"ok": False, "error": "body size"})
                return
            if length <= 0 or length > MAX_BODY * 2:
                self._json(413, {"ok": False, "error": "body size"})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError:
                body = None
            body = body if isinstance(body, dict) else {}
            if path == "/api/remote":
                if self.headers.get_content_type() != "application/json":
                    self._json(415, {"ok": False, "error": "application/json required"})
                    return
                self._json(200, state.remote_action(body))
                return
            if path == "/api/automations":
                if self.headers.get_content_type() != "application/json":
                    self._json(415, {"ok": False, "error": "application/json required"})
                    return
                self._json(200, state.automation_action(body))
                return
            if path == "/api/remote/open":
                if self.headers.get_content_type() != "application/json":
                    self._json(415, {"ok": False, "error": "application/json required"})
                    return
                self._json(200, state.open_remote_panel())
                return
            if path in ("/api/workspace", "/api/library"):
                if self.headers.get_content_type() != "application/json":
                    self._json(415, {"ok": False, "error": "application/json required"})
                    return
                target = state.library if path == "/api/library" else state.workspace
                self._json(200, target.action(body))
                return
            if path == '/api/accounts/manage':
                self._json(200, state.account_manager.action(body))
                return
            if path == "/api/playbooks/generate":
                self._json(200, state.generator.generate(body))
                return
            if path == "/api/accounts/order":
                self._json(200, state.order_accounts(body.get("provider"), body.get("names")))
                return
            text = body.get("text")
            if not isinstance(text, str):
                self._json(400, {"ok": False, "error": "text required"})
                return
            self._json(200, state.save(text))

    return Handler


def serve(policy_path: Path, port: int, token: str) -> None:
    state = EditorState(policy_path, token)
    server = LocalHTTPServer(("127.0.0.1", port), make_handler(state, port))

    def watchdog() -> None:
        while True:
            time.sleep(5)
            now = time.monotonic()
            idle = now - state.last_ping if state.last_ping else now - state.started
            limit = IDLE_AFTER_PING if state.last_ping else IDLE_BEFORE_FIRST_PING
            if idle > limit and not state.generator.lock.locked() and not any(
                    job['state'] == 'pending' for job in state.account_manager.jobs.values()):
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        state.account_manager.close()


SANDBOX_BLOCKED = (
    "O sandbox de quem rodou o comando bloqueou o servidor local do editor (127.0.0.1). "
    "Abra o app Coding Opus fora do chat (Launchpad, Spotlight, menu Iniciar ou de aplicativos), "
    "ou rode o comando fora do sandbox."
)
CODEX_SANDBOX_HINT = (
    " No Codex: aprove rodar o comando fora do sandbox ou habilite network_access na seção "
    "[sandbox_workspace_write] de ~/.codex/config.toml."
)


def sandbox_blocked(cause: object) -> bool:
    """A local bind or connect refused by a sandbox (Codex's seatbelt, Claude Code's sandbox...),
    not a busy port: EPERM/EACCES, as an exception or in the server's error output."""
    import errno

    if isinstance(cause, OSError):
        return cause.errno in (errno.EPERM, errno.EACCES)
    text = str(cause)
    return "Operation not permitted" in text or "PermissionError" in text or "Permission denied" in text


def sandbox_message() -> str:
    import os

    codex = bool(os.environ.get("CODEX_SANDBOX") or os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED"))
    return SANDBOX_BLOCKED + (CODEX_SANDBOX_HINT if codex else "")


def launch(policy_path: Path, open_browser: bool) -> Dict[str, Any]:
    """Start the server as a detached process, wait until it answers, and open the page."""
    import os
    import secrets
    import socket
    import subprocess

    token = secrets.token_urlsafe(24)
    log_path = policy_path.parent / "editor-server.log"
    try:
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("ab")
        start = log.tell()
    except OSError:
        log, start = None, 0
    options: Dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                               "stderr": log if log is not None else subprocess.DEVNULL}

    def failed() -> SystemExit:
        try:
            with log_path.open("rb") as handle:  # only what this launch wrote, not older runs
                handle.seek(start)
                tail = handle.read().decode("utf-8", errors="replace").strip().splitlines()[-6:]
        except OSError:
            tail = []
        if sandbox_blocked("\n".join(tail)):
            return SystemExit(sandbox_message())
        return SystemExit("the editor server did not start" + (": " + " | ".join(tail) if tail else ""))

    if os.name == "nt":
        options["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
    else:
        options["start_new_session"] = True
    def start_server() -> Tuple[int, Any]:
        deadline = time.monotonic() + 30  # slow CI machines can take a while to bind
        for _attempt in range(3):
            # The port is free when probed but released before the server binds it; another process
            # can take it in between, and the server then exits at once. Try again on a fresh port.
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind(("127.0.0.1", 0))
                    port = probe.getsockname()[1]
            except OSError as error:
                if sandbox_blocked(error):
                    raise SystemExit(sandbox_message()) from error
                raise
            command = [sys.executable, str(Path(__file__).resolve()), "--policy", str(policy_path),
                       "--port", str(port), "--token=" + token]  # a token may start with "-"
            process = subprocess.Popen(command, **options)
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        return port, process
                except OSError as error:
                    if sandbox_blocked(error):
                        process.kill()
                        raise SystemExit(sandbox_message()) from error
                    if process.poll() is not None:
                        break
                    if time.monotonic() > deadline:
                        process.kill()
                        raise failed()
                    time.sleep(0.2)
        raise failed()

    try:
        port, process = start_server()
    finally:
        if log is not None:
            log.close()  # the server keeps its own copy of the handle
    url = f"http://127.0.0.1:{port}/#token={token}"
    opened = False
    if open_browser:
        from desktop_editor import open_editor
        opened = open_editor(url, policy_path) or webbrowser.open(url)
    return {"url": url, "pid": process.pid, "opened": bool(opened)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Coding Opus playbooks editor on 127.0.0.1")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--launch", action="store_true", help="start a detached server and print its URL")
    parser.add_argument("--no-open", action="store_true", help="with --launch, do not open a browser")
    parser.add_argument("--port", type=int)
    parser.add_argument("--token")
    args = parser.parse_args()
    policy_path = args.policy.expanduser().resolve()
    if args.launch:
        print(json.dumps(launch(policy_path, not args.no_open)))
        return 0
    if args.port is None or not args.token:
        parser.error("--port and --token are required without --launch")
    serve(policy_path, args.port, args.token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
