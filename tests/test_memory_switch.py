"""The Memory tab's on/off switch: the same as `memory on|off`, never touching the real home."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "coding" / "scripts"))
from brain import BrainError  # noqa: E402
from chat_memory import ChatMemory  # noqa: E402
from knowledge_library import memory_switch  # noqa: E402


class MemorySwitchTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.brain = root / "brain"
        self.brain.mkdir()
        self.claude, self.codex = root / "claude", root / "codex"
        self.claude.mkdir()
        self.codex.mkdir()
        (self.claude / "settings.json").write_text(json.dumps({"hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": "keep-me"}]}]}}), encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude), "CODEX_HOME": str(self.codex)})
        patch.start()
        self.addCleanup(patch.stop)
        self.memory = ChatMemory(str(self.brain))

    def test_on_installs_capture_and_off_keeps_the_history(self):
        result = memory_switch(self.memory, True, True)
        self.assertTrue(result["enabled"])
        self.assertTrue(self.memory.enabled())
        settings = json.loads((self.claude / "settings.json").read_text(encoding="utf-8"))
        commands = [hook["command"] for groups in settings["hooks"].values() for group in groups for hook in group["hooks"]]
        self.assertIn("keep-me", commands)
        self.assertTrue(any("chat_memory.py" in command for command in commands))
        self.assertTrue((self.codex / "hooks.json").is_file())
        self.assertEqual(sorted(Path(path).name for path in result["rules"]), ["AGENTS.md", "CLAUDE.md"])

        self.assertEqual(memory_switch(self.memory, True, False), {"enabled": False})
        self.assertFalse(self.memory.enabled())
        self.assertTrue((self.memory.root / "memory.sqlite3").is_file())
        self.assertTrue(memory_switch(self.memory, True, True)["enabled"])  # back on, idempotent
        settings = json.loads((self.claude / "settings.json").read_text(encoding="utf-8"))
        stops = [hook["command"] for group in settings["hooks"]["Stop"] for hook in group["hooks"]]
        self.assertEqual(len(stops), len(set(stops)))

    def test_refuses_bad_input_and_a_missing_brain(self):
        with self.assertRaises(BrainError):
            memory_switch(self.memory, True, "yes")
        with self.assertRaises(BrainError):
            memory_switch(self.memory, False, True)
        self.assertEqual(memory_switch(self.memory, False, False), {"enabled": False})


if __name__ == "__main__":
    unittest.main()
