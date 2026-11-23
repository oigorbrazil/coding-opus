"""The playbooks editor: one self-contained page served on 127.0.0.1 that reads and saves the file."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

# Tests read the generic playbooks, not the personal default the skill ships.
os.environ.setdefault("CODING_OPUS_BUNDLED_PLAYBOOKS", str(Path(__file__).resolve().parent / "fixtures" / "playbooks.yaml"))
os.environ.setdefault("CODING_OPUS_TERMINALS", "0")

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "coding" / "scripts" / "orchestrate.py"
PAGE = ROOT / "skills" / "coding" / "assets" / "editor.html"
BUNDLED = Path(os.environ["CODING_OPUS_BUNDLED_PLAYBOOKS"])


class EditorPageTest(unittest.TestCase):
    def test_page_is_one_file_without_external_resources(self):
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn('<div id="root">', page)
        self.assertNotRegex(page, r'<script[^>]+src=')
        self.assertNotRegex(page, r'<link[^>]+href=(?!["\']data:)')
        # The page talks only to the server that served it, through relative /api paths.
        self.assertNotRegex(page, r'fetch\(\s*["\']https?://')
        self.assertIn("/api/playbooks", page)


class EditorServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="coding-opus-editor-")
        self.root = Path(self.temp.name)
        self.policy = self.root / "coding-opus-orchestrate.json"
        self.copy = self.root / "coding-opus-playbooks.yaml"
        self.env = {**os.environ, "CODING_OPUS_POLICY": str(self.policy), "CODING_OPUS_HOME": str(self.root)}
        self.env.pop("CODING_OPUS_PLAYBOOKS", None)
        self.pids = []

    def tearDown(self):
        for pid in self.pids:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                else:
                    os.kill(pid, 9)
            except OSError:
                pass
        self.temp.cleanup()

    def start(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "editor", "--no-open"], env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.pids.append(payload["pid"])
        self.assertFalse(payload["opened"])
        match = re.fullmatch(r"(http://127\.0\.0\.1:\d+)/#token=(\S+)", payload["url"])
        self.assertIsNotNone(match, payload["url"])
        return match.group(1), match.group(2), payload

    def request(self, base, path, token=None, body=None, host=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(base + path, data=data, method="POST" if data else "GET")
        request.add_header("Content-Type", "application/json")
        if token is not None:
            request.add_header("X-Coding-Opus-Token", token)
        if host is not None:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_serves_the_page_and_guards_the_api_with_token_and_host(self):
        base, token, _ = self.start()
        status, page = self.request(base, "/")
        self.assertEqual(status, 200)
        self.assertEqual(page, PAGE.read_bytes())
        self.assertEqual(self.request(base, "/api/playbooks")[0], 401)
        self.assertEqual(self.request(base, "/api/playbooks", token="wrong")[0], 401)
        self.assertEqual(self.request(base, "/api/playbooks", token=token, host="evil.example:80")[0], 403)
        self.assertEqual(self.request(base, "/api/ping", token=token)[0], 200)

    def test_starts_when_the_token_begins_with_a_hyphen(self):
        # token_urlsafe starts with "-" about once in 64 launches; argparse must not read it as an option.
        sys.path.insert(0, str(SCRIPT.parent))
        import editor_server
        from unittest import mock
        with mock.patch("secrets.token_urlsafe", return_value="-" + "a" * 31):
            payload = editor_server.launch(self.policy, open_browser=False)
        self.pids.append(payload["pid"])
        self.assertIn("#token=-aaa", payload["url"])
        base = payload["url"].split("/#")[0]
        self.assertEqual(self.request(base, "/api/stamp", token="-" + "a" * 31)[0], 200)

    def test_lists_the_agent_clis_on_the_computer(self):
        base, token, _ = self.start()
        self.assertEqual(self.request(base, "/api/clis")[0], 401)
        body = json.loads(self.request(base, "/api/clis", token=token)[1])
        self.assertTrue(body["ok"], body)
        ids = [cli["id"] for cli in body["clis"]]
        self.assertEqual(ids[:4], ["codex", "claude", "agy", "kimi"])
        self.assertIn("gemini", ids)
        self.assertEqual({cli["kind"] for cli in body["clis"]}, {"builtin", "custom"})

    def test_lists_the_models_each_provider_offers(self):
        codex_home = self.root / "codex"
        codex_home.mkdir()
        (codex_home / "models_cache.json").write_text(json.dumps({"models": [
            {"slug": "gpt-9-sol", "visibility": "list", "description": "Latest workhorse."},
            {"slug": "gpt-8-sol", "visibility": "list", "upgrade": {"model": "gpt-9-sol"}},
            {"slug": "internal-review", "visibility": "hide"},
        ]}), encoding="utf-8")
        self.env["CODEX_HOME"] = str(codex_home)
        base, token, _ = self.start()
        self.assertEqual(self.request(base, "/api/models")[0], 401)
        body = json.loads(self.request(base, "/api/models", token=token)[1])
        self.assertTrue(body["ok"], body)
        codex = body["catalog"]["providers"]["codex"]
        self.assertEqual(codex[:2], [
            {"id": "gpt-9-sol", "source": "cli", "description": "Latest workhorse.", "upgrade": None},
            {"id": "gpt-8-sol", "source": "cli", "description": None, "upgrade": "gpt-9-sol"},
        ])
        self.assertNotIn("internal-review", [model["id"] for model in codex])
        self.assertIn("claude-opus-5-5", [model["id"] for model in body["catalog"]["providers"]["claude"]])

    def test_lists_and_orders_accounts(self):
        codex_home = self.root / "codex"
        codex_home.mkdir()
        managed = self.root / "managed" / "home"
        managed.mkdir(parents=True)
        self.env["CODEX_HOME"] = str(codex_home)
        # An account added in Coding Opus (`account add`); Coding Agent accounts are no longer imported.
        (self.root / "coding-opus-accounts.json").write_text(json.dumps({
            "providers": {"codex": [{"name": "work", "home": str(managed)}], "claude": []}, "order": {},
        }), encoding="utf-8")
        base, token, _ = self.start()
        self.assertEqual(self.request(base, "/api/accounts")[0], 401)
        body = json.loads(self.request(base, "/api/accounts", token=token)[1])
        self.assertTrue(body["ok"], body)
        codex = body["accounts"]["providers"]["codex"]
        self.assertEqual([row["name"] for row in codex], ["default", "work"])
        self.assertEqual(codex[0]["from"], "cli")
        status, raw = self.request(base, "/api/accounts/order", token=token,
                                   body={"provider": "codex", "names": ["work", "default"]})
        body = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual([row["name"] for row in body["accounts"]["providers"]["codex"]],
                         ["work", "default"])
        body = json.loads(self.request(base, "/api/accounts/order", token=token,
                                       body={"provider": "codex", "names": ["ghost"]})[1])
        self.assertFalse(body["ok"])
        self.assertIn("unknown: ghost", body["error"])

    def test_reads_the_bundled_playbooks_until_a_user_copy_exists(self):
        base, token, payload = self.start()
        # Compare resolved folders: the temp dir may come back as an 8.3 short name on Windows.
        save_to = Path(payload["saveTo"])
        self.assertEqual(save_to.name, self.copy.name)
        self.assertTrue(os.path.samefile(save_to.parent, self.root))
        body = json.loads(self.request(base, "/api/playbooks", token=token)[1])
        self.assertFalse(body["custom"])
        self.assertEqual(body["text"], BUNDLED.read_text(encoding="utf-8"))
        self.copy.write_text(BUNDLED.read_text(encoding="utf-8") + "# mine\n", encoding="utf-8")
        body = json.loads(self.request(base, "/api/playbooks", token=token)[1])
        self.assertTrue(body["custom"])
        self.assertTrue(body["text"].endswith("# mine\n"))

    def test_save_writes_the_user_copy_with_a_backup_and_moves_the_stamp(self):
        original = BUNDLED.read_text(encoding="utf-8")
        self.copy.write_text(original, encoding="utf-8")
        base, token, _ = self.start()
        before = json.loads(self.request(base, "/api/stamp", token=token)[1])["stamp"]
        edited = original + "# saved from the editor\n"
        status, raw = self.request(base, "/api/playbooks", token=token, body={"text": edited})
        result = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.copy.read_text(encoding="utf-8"), edited)
        self.assertEqual(self.copy.with_name(self.copy.name + ".bak").read_text(encoding="utf-8"), original)
        after = json.loads(self.request(base, "/api/stamp", token=token)[1])["stamp"]
        self.assertGreaterEqual(after, before)

    def test_save_refuses_playbooks_the_runner_would_reject(self):
        original = BUNDLED.read_text(encoding="utf-8")
        self.copy.write_text(original, encoding="utf-8")
        base, token, _ = self.start()
        for text in ("", "version: 1\nprofile: missing\n", original.replace("playbooks:", "playbookz:", 1)):
            with self.subTest(text=text[:30]):
                result = json.loads(self.request(base, "/api/playbooks", token=token, body={"text": text})[1])
                self.assertFalse(result["ok"])
                self.assertEqual(self.copy.read_text(encoding="utf-8"), original)

    def test_editor_refuses_to_start_on_a_broken_user_copy(self):
        self.copy.write_text("version: 1\nprofiles: nope\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "editor", "--no-open"], env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid playbooks", result.stderr + result.stdout)



class SandboxBlockedTest(unittest.TestCase):
    """A sandbox that refuses the local port gets a clear way out, not a traceback."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPT.parent))
        import editor_server

        self.server = editor_server
        temp = tempfile.TemporaryDirectory(prefix="coding-opus-sandbox-")
        self.addCleanup(temp.cleanup)
        self.policy = Path(temp.name) / "coding-opus-orchestrate.json"
        (Path(temp.name) / "editor-server.log").write_text("Old PermissionError from another day\n", encoding="utf-8")

    def child(self, stderr_line, code):
        import subprocess as real
        from unittest import mock

        original = real.Popen

        def fake(command, **options):
            script = f"import sys; sys.stderr.write({stderr_line!r} + '\n'); sys.exit({code})"
            return original([sys.executable, "-c", script], **options)

        return mock.patch("subprocess.Popen", side_effect=fake)

    def test_a_refused_port_probe_explains_the_sandbox(self):
        from unittest import mock

        with mock.patch("socket.socket.bind", side_effect=PermissionError(1, "Operation not permitted")), \
                mock.patch.dict(os.environ, {"CODEX_SANDBOX": "seatbelt"}):
            with self.assertRaises(SystemExit) as raised:
                self.server.launch(self.policy, open_browser=False)
        self.assertIn("sandbox", str(raised.exception.code))
        self.assertIn("network_access", str(raised.exception.code))

    def test_a_server_refused_by_the_sandbox_explains_it(self):
        from unittest import mock

        with self.child("PermissionError: [Errno 1] Operation not permitted", 1), \
                mock.patch.dict(os.environ, {"CODEX_SANDBOX": "", "CODEX_SANDBOX_NETWORK_DISABLED": ""}):
            with self.assertRaises(SystemExit) as raised:
                self.server.launch(self.policy, open_browser=False)
        message = str(raised.exception.code)
        self.assertIn("Abra o app Coding Opus", message)
        self.assertNotIn("network_access", message)

    def test_other_failures_keep_their_own_error(self):
        # Only this launch's output counts: the old PermissionError in the log is ignored.
        with self.child("ValueError: playbooks unreadable", 1):
            with self.assertRaises(SystemExit) as raised:
                self.server.launch(self.policy, open_browser=False)
        message = str(raised.exception.code)
        self.assertIn("did not start", message)
        self.assertIn("playbooks unreadable", message)
        self.assertNotIn("sandbox", message)


if __name__ == "__main__":
    unittest.main()
