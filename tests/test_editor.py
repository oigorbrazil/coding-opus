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

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "coding" / "scripts" / "orchestrate.py"
PAGE = ROOT / "skills" / "coding" / "assets" / "editor.html"
BUNDLED = Path(os.environ["CODING_OPUS_BUNDLED_PLAYBOOKS"])


class EditorPageTest(unittest.TestCase):
    def test_page_is_one_file_without_external_resources(self):
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn('<div id="root"></div>', page)
        self.assertNotRegex(page, r'<script[^>]+src=')
        self.assertNotRegex(page, r'<link[^>]+href=')
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


if __name__ == "__main__":
    unittest.main()
