import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills/coding/scripts/orchestrate.py"
spec = importlib.util.spec_from_file_location("runtime_runner", SCRIPT)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coding-runtime-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {**os.environ, "CODING_OPUS_HOME": str(self.root / "home"),
                    "CODING_OPUS_SESSION": "", "CLAUDE_CODE_SESSION_ID": ""}

    def call(self, script, *args):
        return subprocess.run([sys.executable, str(script), *args], env=self.env,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def copy_runner(self, name):
        skill = self.root / name
        (skill / "scripts").mkdir(parents=True)
        (skill / "references").mkdir()
        script = skill / "scripts/orchestrate.py"
        shutil.copyfile(SCRIPT, script)
        (skill / "SKILL.md").write_text('---\nmetadata:\n  version: "999"\n---\n', encoding="utf-8")
        (skill / "references/briefs.md").write_text(f"Brief from {name}\n", encoding="utf-8")
        return script

    def test_same_session_reuses_runner_and_rejects_another_copy_before_action(self):
        first = self.copy_runner("first")
        second = self.copy_runner("second")
        args = ("--session-id", "fixture", "guide", "briefs")
        self.assertEqual(self.call(first, *args).returncode, 0)
        self.assertEqual(self.call(first, *args).returncode, 0)
        rejected = self.call(second, *args)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("runtime mismatch", rejected.stderr)
        self.assertIn(str(first.resolve()), rejected.stderr)
        self.assertEqual(rejected.stdout, "")
        self.assertEqual(self.call(second, "--session-id", "another-session", "guide", "briefs").returncode, 0)

    def test_runner_changed_in_place_is_not_silently_used(self):
        script = self.copy_runner("first")
        args = ("--session-id", "fixture", "guide", "briefs")
        self.assertEqual(self.call(script, *args).returncode, 0)
        with script.open("a", encoding="utf-8") as handle:
            handle.write("\n# changed runtime\n")
        self.assertEqual(self.call(script, *args).returncode, 2)

    def test_doctor_returns_an_executable_prefix_and_refuses_a_changed_python(self):
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(r, "doctor_payload", return_value={}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(r.main(["doctor"]), 0)
            runtime = json.loads(out.getvalue())["runtime"]
            self.assertEqual(runtime["command"][:2], [str(Path(sys.executable).resolve()), str(SCRIPT)])
            followup = self.call(SCRIPT, *runtime["command"][2:], "guide", "briefs")
            self.assertEqual(followup.returncode, 0, followup.stderr)
            changed = {**r.runtime_identity(), "python": str(self.root / "other-python")}
            with mock.patch.object(r, "runtime_identity", return_value=changed):
                with self.assertRaisesRegex(r.PlanError, "runtime mismatch"):
                    r.session_runtime(runtime["sessionId"])

    def test_guide_uses_only_its_own_reference_and_missing_reference_fails(self):
        script = self.copy_runner("selected")
        result = self.call(script, "guide", "briefs")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Brief from selected", result.stdout)
        self.assertIn("Coding Opus 999", result.stdout)
        missing = self.call(script, "guide", "providers")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("cannot load guide", missing.stderr)
        self.assertNotIn("# Provider adapters", missing.stdout)

    def test_hook_reports_runtime_mismatch_instead_of_running_another_copy(self):
        first = self.copy_runner("first")
        second = self.copy_runner("second")
        self.assertEqual(self.call(first, "--session-id", "fixture", "guide", "briefs").returncode, 0)
        hook = second.with_name("hook.py")
        shutil.copyfile(SCRIPT.with_name("hook.py"), hook)
        event = json.dumps({"session_id": "fixture", "hook_event_name": "UserPromptSubmit", "cwd": str(self.root)})
        result = subprocess.run([sys.executable, str(hook)], input=event, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertIn("runtime mismatch", result.stdout)
        self.assertIn(str(first.resolve()), result.stdout)

    def test_hook_launcher_keeps_the_selected_python_failure(self):
        shell = shutil.which("sh")
        if not shell and os.name == "nt":
            candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
            shell = str(candidate) if candidate.is_file() else None
        if not shell:
            self.skipTest("hook shell unavailable")
        plugin = self.root / "plugin"
        scripts = plugin / "skills/coding/scripts"
        scripts.mkdir(parents=True)
        (scripts / "hook.py").write_text("import sys\nsys.stderr.write('selected Python failed exactly')\nsys.exit(7)\n", encoding="utf-8")
        config = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
        command = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        environment = {**self.env, "CODING_OPUS_PYTHON": sys.executable, "CLAUDE_PLUGIN_ROOT": str(plugin)}
        result = subprocess.run([shell, "-c", command], env=environment, capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stderr, "selected Python failed exactly")


class HandoffTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coding-handoff-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture")
        self.policy = self.root / "policy.json"
        self.env = {**os.environ, "CODING_OPUS_HOME": str(self.root / "home"),
                    "CODING_OPUS_POLICY": str(self.policy), "CODING_OPUS_SESSION": "handoff-test",
                    "CLAUDE_CODE_SESSION_ID": "", "CODEX_HOME": str(self.root / "codex"),
                    "CODING_OPUS_PLAYBOOKS": str(self.root / "playbooks.yaml"),
                    "CODING_OPUS_BUNDLED_PLAYBOOKS": str(ROOT / "tests/fixtures/playbooks.yaml")}
        self.patch = mock.patch.dict(os.environ, self.env, clear=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.release = self.root / "release"
        self.fake = self.root / "fake.py"
        self.fake.write_text(
            "import sys,time\nfrom pathlib import Path\nsys.stdin.read()\n"
            f"while not Path({str(self.release)!r}).exists(): time.sleep(0.05)\n"
            "Path('handoff-result.txt').write_text('worker change')\nprint('Completed the fixture.')\n",
            encoding="utf-8")
        self.folder = None
        self.addCleanup(self.finish_worker)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def finish_worker(self):
        self.release.touch()
        if self.folder:
            r.wait_payload(self.folder, 20)

    def call(self, *extra):
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--session-id", "handoff-test", "handoff", "Implement the fixture.",
            "--provider", "custom", "--cwd", str(self.repo), "--command", sys.executable,
            "--arg=" + str(self.fake), *extra,
        ], cwd=self.repo, env=os.environ, capture_output=True, text=True, encoding="utf-8", timeout=40)
        return result

    def test_handoff_runs_on_its_own_branch_without_waiting_or_changing_current(self):
        lead = self.root / "lead"
        lead.mkdir()
        r.set_current(lead)
        original_branch = self.git("branch", "--show-current")
        result = self.call("--branch", "feature/handoff-test")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.folder = Path(payload["folder"])
        self.assertFalse(payload["integration"])
        worktree = Path(payload["worktree"])
        self.assertTrue(worktree.is_dir())
        branch = subprocess.run(["git", "-C", str(worktree), "branch", "--show-current"],
                                check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, "feature/handoff-test")
        self.assertEqual(self.git("branch", "--show-current"), original_branch)
        self.assertEqual(r.current_folder(), lead)
        self.assertFalse((self.repo / "handoff-result.txt").exists())
        self.assertEqual(json.loads((Path(payload["runDir"]) / "state.json").read_text())["status"], "running")
        self.release.touch()
        self.assertTrue(r.wait_payload(self.folder, 20)["done"])
        self.assertEqual((worktree / "handoff-result.txt").read_text(), "worker change")
        self.assertTrue(Path(payload["result"]).is_file())
        self.assertTrue(Path(payload["diff"]).is_file())

    def test_existing_branch_fails_without_switching_or_launching_another_worker(self):
        self.git("branch", "feature/existing")
        result = self.call("--branch", "feature/existing")
        self.assertEqual(result.returncode, 2)
        self.assertIn("already exists", result.stderr)
        self.assertFalse((self.repo / "handoff-result.txt").exists())

    def test_worker_cannot_start_a_handoff(self):
        with mock.patch.dict(os.environ, {"CODING_OPUS_WORKER": "1"}):
            result = self.call()
        self.assertEqual(result.returncode, 2)
        self.assertIn("workers cannot start handoffs", result.stderr)

    def test_missing_executable_reports_the_error_without_falling_back(self):
        missing = str(self.root / "missing-python.exe")
        result = self.call("--command", missing)
        self.assertEqual(result.returncode, 2)
        self.assertIn(missing, result.stderr)
        self.assertFalse((self.repo / "handoff-result.txt").exists())


if __name__ == "__main__":
    unittest.main()
