#!/usr/bin/env python3
"""Coding Opus — local server for the playbooks editor.

`orchestrate.py editor` starts this in the background. It serves `assets/editor.html` (the same
editor Coding Agent 2 ships) on 127.0.0.1 and lets that page read and save the playbooks file the
skill plans with. Every API call needs the one-time token from the page URL. The server stops on
its own a little after the page is closed. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orchestrate  # noqa: E402  (same folder; imported for its playbook rules)

PAGE = Path(__file__).resolve().parent.parent / "assets" / "editor.html"
MAX_BODY = 1 << 20
# Stop when the page has not pinged for this long (it pings every 20 s), or if it never connects.
IDLE_AFTER_PING = 90
IDLE_BEFORE_FIRST_PING = 600


class EditorState:
    def __init__(self, policy_path: Path, token: str) -> None:
        self.policy_path = policy_path
        self.token = token
        self.last_ping = 0.0
        self.started = time.monotonic()
        self.lock = threading.Lock()

    def playbooks(self) -> Dict[str, Any]:
        user = orchestrate.user_playbooks_path(self.policy_path)
        effective = orchestrate.effective_playbooks_path(self.policy_path)
        return {
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
            if self.path.split("?", 1)[0] != "/api/playbooks":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY * 2:
                self._json(413, {"ok": False, "error": "body size"})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                text = body.get("text") if isinstance(body, dict) else None
            except ValueError:
                text = None
            if not isinstance(text, str):
                self._json(400, {"ok": False, "error": "text required"})
                return
            self._json(200, state.save(text))

    return Handler


def serve(policy_path: Path, port: int, token: str) -> None:
    state = EditorState(policy_path, token)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, port))

    def watchdog() -> None:
        while True:
            time.sleep(5)
            now = time.monotonic()
            idle = now - state.last_ping if state.last_ping else now - state.started
            limit = IDLE_AFTER_PING if state.last_ping else IDLE_BEFORE_FIRST_PING
            if idle > limit:
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Coding Opus playbooks editor on 127.0.0.1")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    serve(args.policy.expanduser().resolve(), args.port, args.token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
