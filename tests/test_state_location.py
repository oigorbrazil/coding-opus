import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "coding" / "scripts" / "orchestrate.py"
spec = importlib.util.spec_from_file_location("state_location_orchestrate", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@unittest.skipUnless(os.name == "nt", "the state folder moved out of %APPDATA% on Windows only")
class StateLocationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coding-opus-state-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / "profile"
        self.appdata = self.profile / "AppData" / "Roaming"
        self.appdata.mkdir(parents=True)
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("CODING_OPUS_POLICY", "CODING_OPUS_HOME")}
        patcher = mock.patch.dict(os.environ, {**environment, "USERPROFILE": str(self.profile),
                                               "APPDATA": str(self.appdata)}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_state_lives_in_the_home_folder(self):
        self.assertEqual(runner.default_policy_path(), self.profile / ".coding-opus" / "coding-opus-orchestrate.json")
        self.assertEqual(runner.orchestrations_home(), self.profile / ".coding-opus" / "orchestrations")

    def test_the_appdata_state_is_copied_once_and_kept(self):
        legacy = self.appdata / "CodingOpus"
        (legacy / "orchestrations" / "20261110-run").mkdir(parents=True)
        (legacy / "coding-opus-playbooks.yaml").write_text("version: 1\n", encoding="utf-8")
        (legacy / "orchestrations" / "current.json").write_text(
            json.dumps({"folder": str(legacy / "orchestrations" / "20261110-run")}), encoding="utf-8")
        target = self.profile / ".coding-opus"

        self.assertEqual(runner.default_policy_path().parent, target)
        self.assertEqual((target / "coding-opus-playbooks.yaml").read_text(encoding="utf-8"), "version: 1\n")
        current = json.loads((target / "orchestrations" / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(current["folder"]), target / "orchestrations" / "20261110-run")
        self.assertIn(str(legacy), (target / "MIGRATED_FROM.txt").read_text(encoding="utf-8"))
        self.assertTrue((legacy / "coding-opus-playbooks.yaml").is_file())

        (legacy / "coding-opus-playbooks.yaml").write_text("version: 2\n", encoding="utf-8")
        runner.default_policy_path()
        self.assertEqual((target / "coding-opus-playbooks.yaml").read_text(encoding="utf-8"), "version: 1\n")


if __name__ == "__main__":
    unittest.main()
