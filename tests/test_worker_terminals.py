import io
import json
import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

from test_orchestrate import Fixtures, orchestrate as r


class WorkerTerminalsTest(Fixtures):
    def setUp(self):
        super().setUp()
        environment = mock.patch.dict(os.environ, {"CODING_OPUS_TERMINALS": "1", "CODING_OPUS_SESSION": "", "CLAUDE_CODE_SESSION_ID": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.launch = mock.patch.object(r, "spawn_terminal_observer")
        self.launcher = self.launch.start()
        self.addCleanup(self.launch.stop)
        self.resolve = mock.patch.object(r, "terminal_launcher", return_value=("wt", "C:/WindowsApps/wt.exe"))
        self.resolver = self.resolve.start()
        self.addCleanup(self.resolve.stop)
        self.plan = self.write_plan("terminals-plan", {
            "version": 1, "title": "Wave title", "strategy": "balanced",
            "workers": [self.worker(name, "read-only", ["say", "STATUS: DONE\nSUMMARY: Observed fixture."],
                                    "text", self.root, model="fixture-model") for name in ("first", "second")],
        })

    def run_wave(self, name="wave", *flags):
        return self.call("run", self.plan, "--run-dir", self.root / name, "--policy", self.policy, *flags)

    def test_default_is_enabled_and_policy_round_trip_is_boolean(self):
        self.assertEqual(self.run_wave()[0], 0)
        self.assertEqual(len(self.launcher.call_args_list), 2)
        self.assertTrue(r.load_policy(self.policy)["terminals"])
        self.assertTrue(r.terminals_enabled({}, None))
        self.assertEqual(self.call("policy", "set", "--file", self.policy, "--terminals", "off")[0], 0)
        code, output, _ = self.call("policy", "show", "--file", self.policy)
        self.assertEqual(code, 0)
        self.assertIs(json.loads(output)["policy"]["terminals"], False)
        self.assertEqual(self.run_wave("saved-off")[0], 0)
        self.assertEqual(len(self.launcher.call_args_list), 2)
        self.assertEqual(self.call("policy", "set", "--file", self.policy, "--terminals", "on")[0], 0)
        self.assertIs(json.loads(self.policy.read_text())["terminals"], True)
        for invalid in ("on", 1, None):
            with self.assertRaisesRegex(r.PlanError, "policy.terminals must be a boolean"):
                r.validate_policy({"terminals": invalid})

    def test_flag_launches_once_per_started_worker_with_title_and_follower_argv(self):
        folder = self.root / "orchestration"
        folder.mkdir()
        r.atomic_write_json(folder / r.ORCHESTRATION_FILE, {"title": "Orchestration title"})
        run = (folder / "01-wave").resolve()
        code, _, error = self.call("run", self.plan, "--run-dir", run, "--policy", self.policy, "--terminals")
        self.assertEqual(code, 0, error)
        self.resolver.assert_called_once()
        seen = {}
        for call in self.launcher.call_args_list:
            launcher, title, argv, cwd, directory = call.args
            worker = argv[argv.index("follow") + 2]
            seen[worker] = title
            self.assertEqual(launcher, ("wt", "C:/WindowsApps/wt.exe"))
            self.assertEqual(argv[:5], [sys.executable, "-B", str(Path(r.__file__).resolve()), "follow", str(run)])
            self.assertEqual(argv[-2:], ["--title", title])
            self.assertEqual(cwd, self.root.resolve())
            self.assertEqual(directory, run)
        self.assertEqual(seen, {
            "first": "Orchestration title · first · custom:fixture-model",
            "second": "Orchestration title · second · custom:fixture-model",
        })

    def test_no_flag_and_environment_disable_override_saved_default(self):
        r.save_policy(self.policy, {"terminals": True})
        self.assertEqual(self.run_wave("explicit-off", "--no-terminals")[0], 0)
        with mock.patch.dict(os.environ, {"CODING_OPUS_TERMINALS": "0"}):
            self.assertEqual(self.run_wave("env-off", "--terminals")[0], 0)
        self.resolver.assert_not_called()
        self.launcher.assert_not_called()

    def test_missing_launcher_warns_once_and_wave_still_completes(self):
        self.resolver.side_effect = r.PlanError("no launcher")
        code, _, errors = self.run_wave("unavailable", "--terminals")
        self.assertEqual(code, 0)
        self.assertEqual(errors.count("warning:"), 1)
        self.assertIn("no launcher", errors)
        self.launcher.assert_not_called()
        self.assertEqual(json.loads((self.root / "unavailable/state.json").read_text())["status"], "done")

    def test_failed_helper_launch_never_changes_worker_outcome_or_retries_launcher(self):
        self.launcher.side_effect = OSError("chosen launcher failed")
        code, _, errors = self.run_wave("failed-launch", "--terminals")
        self.assertEqual(code, 0)
        self.resolver.assert_called_once()
        self.assertIn("chosen launcher failed", errors)
        for name in ("first", "second"):
            outcome = json.loads((self.root / "failed-launch/workers" / name / "outcome.json").read_text())
            self.assertEqual(outcome["status"], "succeeded")

    def test_detached_runner_gets_the_effective_setting(self):
        plan = r.validate_plan(r.read_json(self.plan), self.plan.resolve(), r.load_policy(self.policy), policy_path=self.policy)
        for value in (True, False):
            process = mock.Mock(pid=123456, stdin=io.BytesIO())
            run = self.root / ("detached-on" if value else "detached-off")
            with mock.patch.object(r, "validate_plan", return_value=plan), mock.patch.object(r.subprocess, "Popen", return_value=process) as spawn:
                r.detach_run(self.plan, run, self.policy, None, terminals=value)
            argv = spawn.call_args.args[0]
            self.assertIn("--_background", argv)
            self.assertIn("--terminals" if value else "--no-terminals", argv)
        self.resolver.assert_not_called()  # Only the detached runner resolves a desktop launcher.

    def test_detached_helper_reports_launcher_failure_without_retry(self):
        with mock.patch.object(r, "launch_terminal", side_effect=OSError("chosen wt failed")) as launch:
            code, _, error = self.call("follow", self.root, "worker", "--_terminal", "wt", "--_executable", "chosen-wt.exe")
        self.assertEqual(code, 0)
        self.assertIn("warning: worker terminal for worker could not open: chosen wt failed", error)
        self.assertEqual(launch.call_args.args[0], ("wt", "chosen-wt.exe"))
        self.resolver.assert_not_called()

    def test_environment_kill_switch_also_disables_already_dispatched_helper(self):
        with mock.patch.dict(os.environ, {"CODING_OPUS_TERMINALS": "0"}), mock.patch.object(r, "launch_terminal") as launch:
            code, _, _ = self.call("follow", self.root, "worker", "--_terminal", "wt", "--_executable", "chosen-wt.exe")
        self.assertEqual(code, 0)
        launch.assert_not_called()


class TerminalLauncherTest(unittest.TestCase):
    def test_windows_selects_wt_once_or_new_console(self):
        with mock.patch.object(r.sys, "platform", "win32"), mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(r.shutil, "which", return_value="C:/WindowsApps/wt.exe") as which:
                self.assertEqual(r.terminal_launcher(), ("wt", "C:/WindowsApps/wt.exe"))
                which.assert_called_once_with("wt.exe")
            with mock.patch.object(r.shutil, "which", return_value=None):
                self.assertEqual(r.terminal_launcher(), ("console", sys.executable))

    def test_windows_paths_with_spaces_are_separate_argv_and_quoted_by_subprocess(self):
        command = [r"C:\Users\igor brazil\Python\python.exe", "-B", r"C:\Users\igor brazil\skill\orchestrate.py",
                   "follow", r"C:\Users\igor brazil\runs\one", "worker", "--title", "Title · worker · codex:model"]
        process = mock.Mock()
        process.wait.return_value = 0
        with mock.patch.object(r.subprocess, "Popen", return_value=process) as spawn:
            r.launch_terminal(("wt", r"C:\WindowsApps\wt.exe"), "Title · worker · codex:model", command, Path.cwd())
        argv = spawn.call_args.args[0]
        self.assertEqual(argv[:7], [r"C:\WindowsApps\wt.exe", "-w", "0", "nt", "--title",
                                   "Title · worker · codex:model", "--suppressApplicationTitle"])
        # The first command argument follows the seven Windows Terminal arguments.
        self.assertEqual(argv[7:], command)
        rendered = subprocess.list2cmdline(argv)
        self.assertIn('"C:\\Users\\igor brazil\\Python\\python.exe"', rendered)
        self.assertIn('"C:\\Users\\igor brazil\\skill\\orchestrate.py"', rendered)
        self.assertIs(spawn.call_args.kwargs["shell"], False)

    def test_new_console_uses_the_same_follower_without_shell(self):
        command = [sys.executable, "script.py", "follow", "run", "worker"]
        with mock.patch.object(r.subprocess, "CREATE_NEW_CONSOLE", 16, create=True), mock.patch.object(r.subprocess, "Popen") as spawn:
            r.launch_terminal(("console", sys.executable), "Title", command, Path.cwd())
        self.assertEqual(spawn.call_args.args[0], command)
        self.assertEqual(spawn.call_args.kwargs["creationflags"], 16)
        self.assertIs(spawn.call_args.kwargs["shell"], False)

    def test_observer_helper_is_detached_and_never_waited_on(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="observer-") as folder:
            run = Path(folder)
            argv = r.follower_command(run, "worker", "Title")
            with mock.patch.object(r.subprocess, "Popen") as spawn:
                r.spawn_terminal_observer(("wt", "chosen-wt.exe"), "Title", argv, run, run)
            self.assertEqual(spawn.call_args.args[0], [*argv, "--_terminal", "wt", "--_executable", "chosen-wt.exe"])
            spawn.return_value.wait.assert_not_called()
            self.assertIs(spawn.call_args.kwargs["shell"], False)

    def test_linux_selection_and_headless_or_ssh_skip(self):
        with mock.patch.object(r.sys, "platform", "linux"), mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(r.PlanError, "no DISPLAY"):
                r.terminal_launcher()
            with mock.patch.dict(os.environ, {"DISPLAY": ":0"}), mock.patch.object(r.shutil, "which", side_effect=lambda name: "/bin/" + name):
                self.assertEqual(r.terminal_launcher(), ("x-terminal-emulator", "/bin/x-terminal-emulator"))
            with mock.patch.dict(os.environ, {"DISPLAY": ":0", "SSH_CONNECTION": "fixture"}):
                with self.assertRaisesRegex(r.PlanError, "SSH session"):
                    r.terminal_launcher()

    def test_mac_quotes_command_as_data_not_applescript(self):
        command = ["/Applications/My Python/python3", "script.py", "follow", "/tmp/a b/'quoted'", "worker"]
        title = 'Title "quoted"; do not execute'
        process = mock.Mock()
        process.wait.return_value = 0
        with mock.patch.object(r.subprocess, "Popen", return_value=process) as spawn:
            r.launch_terminal(("osascript", "/usr/bin/osascript"), title, command, PurePosixPath("/tmp/a b"))
        argv = spawn.call_args.args[0]
        self.assertNotIn(title, argv[2])
        self.assertEqual(argv[-1], title)
        self.assertEqual(shlex.split(argv[-2]), ["cd", "/tmp/a b", "&&", *command])


class FollowTest(Fixtures):
    def setUp(self):
        super().setUp()
        self.worker = self.root / "run/workers/worker"
        self.worker.mkdir(parents=True)
        (self.worker / "stdout.log").write_text("live stdout\n", encoding="utf-8")
        (self.worker / "stderr.log").write_text("live stderr\n", encoding="utf-8")
        (self.worker / "result.md").write_text("STATUS: DONE\nSUMMARY: Read the fixture.\n", encoding="utf-8")

    def test_finished_follower_prints_result_and_resume_without_modifying_files(self):
        for provider, expected in (("codex", "codex resume session-123"), ("claude", "claude --resume session-123"),
                                   ("agy", "agy --conversation session-123"), ("kimi", "kimi --session session-123")):
            with self.subTest(provider=provider):
                r.atomic_write_json(self.worker / "outcome.json", {"status": "succeeded", "provider": provider,
                                                                    "sessionId": "session-123", "cwd": str(self.root)})
                before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                with mock.patch("builtins.input", return_value="") as pause:
                    code, output, error = self.call("follow", self.root / "run", "worker")
                self.assertEqual(code, 0, error)
                self.assertIn("live stdout", output)
                self.assertIn("live stderr", output)
                self.assertIn("STATUS: DONE\nSUMMARY: Read the fixture.", output)
                self.assertIn(expected, output)
                self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
                pause.assert_called_once()

    def test_live_tail_handles_a_split_utf8_character_and_observes_finish(self):
        emoji = "✓".encode("utf-8")
        (self.worker / "stdout.log").write_bytes(emoji[:1])
        r.atomic_write_json(self.root / "run/state.json", {"status": "running", "runnerPid": os.getpid(),
                                                        "workers": {"worker": {"status": "running"}}})

        def finish(_seconds):
            with (self.worker / "stdout.log").open("ab") as handle:
                handle.write(emoji[1:] + b" finished\n")
            r.atomic_write_json(self.worker / "outcome.json", {"status": "succeeded", "provider": "custom"})

        with mock.patch.object(r.time, "sleep", side_effect=finish), mock.patch("builtins.input", return_value=""):
            code, output, _ = self.call("follow", self.root / "run", "worker")
        self.assertEqual(code, 0)
        self.assertIn("✓ finished", output)
        self.assertNotIn("Resume:", output)


if __name__ == "__main__":
    unittest.main()
