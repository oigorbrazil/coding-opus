"""Coding Opus sets itself up on the first prompt: no /coding install needed."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "coding" / "scripts"
PROMPT = json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(ROOT), "prompt": "oi"})


class FirstRunSetupTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="coding-first-run-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / "home"
        (self.home / ".codex").mkdir(parents=True)
        self.brain = self.root / "brain"
        self.state = self.root / "state" / "orchestrations"
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "CODING_OPUS_BRAIN": str(self.brain), "CODING_OPUS_HOME": str(self.state),
                    "CODING_OPUS_PASSIVE": "0", "CODING_OPUS_TERMINALS": "0"}
        for key in ("CODING_OPUS_AUTO_SETUP", "CODING_OPUS_POLICY", "CODING_OPUS_WORKER"):
            self.env.pop(key, None)
        self.marker = self.root / "state" / "setup.json"

    def first_run(self, **extra):
        code = ("import hook, json, sys; sys.stdout.reconfigure(encoding='utf-8'); "
                "print(hook.first_run_setup(json.loads(sys.argv[1])), end='')")
        result = subprocess.run([sys.executable, "-c", code, PROMPT], cwd=SCRIPTS, env={**self.env, **extra},
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_first_prompt_creates_the_brain_and_rules_once(self):
        message = self.first_run()
        self.assertIn("se configurar sozinho", message)
        self.assertIn(str(self.brain), message)
        self.assertTrue((self.brain / "00-Inbox").is_dir())
        for rules in (self.home / ".claude" / "CLAUDE.md", self.home / ".codex" / "AGENTS.md"):
            self.assertIn("coding-opus:inicio", rules.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(self.marker.read_text(encoding="utf-8"))["secondBrain"], str(self.brain))
        self.assertEqual(self.first_run(), "")

    def test_an_existing_brain_is_reused_untouched(self):
        self.brain.mkdir()
        (self.brain / "minha-nota.md").write_text("x", encoding="utf-8")
        self.assertIn("reaproveitado", self.first_run())
        self.assertEqual(sorted(path.name for path in self.brain.iterdir()), ["minha-nota.md"])

    def test_a_setup_made_by_hand_is_only_remembered(self):
        rules = self.home / ".claude" / "CLAUDE.md"
        rules.parent.mkdir()
        rules.write_text("<!-- coding-opus:inicio -->\nregras\n<!-- coding-opus:fim -->\n", encoding="utf-8")
        self.assertEqual(self.first_run(), "")
        self.assertTrue(self.marker.is_file())
        self.assertFalse(self.brain.exists())

    def test_it_can_be_turned_off(self):
        self.assertEqual(self.first_run(CODING_OPUS_AUTO_SETUP="0"), "")
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.brain.exists())

    def test_the_hook_reports_the_setup_in_utf8(self):
        # Run as Claude Code does: event on stdin, context on stdout, any console code page.
        result = subprocess.run([sys.executable, "-S", str(SCRIPTS / "hook.py")], input=PROMPT.encode("utf-8"),
                                env={**self.env, "PYTHONIOENCODING": "cp1252"}, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Conte isso ao usuário", result.stdout.decode("utf-8"))

    def test_tool_events_never_set_up(self):
        code = ("import hook; print(hook.first_run_setup({'hook_event_name': 'PostToolUse'}), end='')")
        result = subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS, env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
