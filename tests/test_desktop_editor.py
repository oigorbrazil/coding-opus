import os
import plistlib
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "coding" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import desktop_editor  # noqa: E402

NO_SSH = {key: "" for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")}


class UnixLauncherTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="desktop-editor-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.policy = self.root / "policy dir" / "coding-opus-orchestrate.json"
        patches = [
            # Simulate a non-Windows machine: never reach the real Windows app from a test.
            mock.patch.object(desktop_editor, "supported", return_value=False),
            mock.patch.object(desktop_editor, "detach", side_effect=AssertionError("unexpected launch")),
            mock.patch.object(desktop_editor.Path, "home", classmethod(lambda cls: self.home)),
            mock.patch.dict(os.environ, {**NO_SSH, "ORCA_BACKGROUND_LAUNCH": ""}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def platform(self, name, **env):
        stack = [mock.patch.object(desktop_editor.sys, "platform", name), mock.patch.dict(os.environ, env)]
        for patch in stack:
            patch.start()
            self.addCleanup(patch.stop)

    def test_mac_bundle_starts_the_editor_server(self):
        self.platform("darwin")
        with mock.patch.object(desktop_editor.subprocess, "run") as run:
            path = desktop_editor.ensure_installed(self.policy)
            self.assertEqual(path, self.home / "Applications" / "Coding Opus.app")
            info = plistlib.loads((path / "Contents" / "Info.plist").read_bytes())
            self.assertEqual((info["CFBundleExecutable"], info["CFBundleIconFile"]), ("coding-opus", "AppIcon"))
            script = (path / "Contents" / "MacOS" / "coding-opus").read_text(encoding="utf-8")
            argv = shlex.split(script.splitlines()[-1])
            self.assertEqual(argv[0], "exec")
            self.assertEqual(argv[2:], [str(SCRIPTS / "editor_server.py"), "--policy", str(self.policy), "--launch"])
            self.assertEqual(run.call_args.args[0][:4], ["sips", "-s", "format", "icns"])
            run.reset_mock()
            desktop_editor.ensure_installed(self.policy)
            run.assert_not_called()  # nothing changed, nothing rewritten
        self.assertEqual(desktop_editor.installed(), path)

    def test_linux_entry_and_icon(self):
        data = self.root / "data"
        self.platform("linux", DISPLAY=":0", XDG_DATA_HOME=str(data))
        with mock.patch.object(desktop_editor.shutil, "which", return_value=None):
            path = desktop_editor.ensure_installed(self.policy)
        self.assertEqual(path, data / "applications" / "coding-opus.desktop")
        entry = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
        self.assertEqual(entry["Name"], "Coding Opus")
        self.assertIn(desktop_editor.desktop_exec(["--policy", str(self.policy)]), entry["Exec"])
        self.assertTrue(entry["Exec"].endswith("--launch"))
        self.assertEqual(Path(entry["Icon"]).read_bytes(), desktop_editor.ICON.read_bytes())

    def test_exec_quoting_follows_the_desktop_spec(self):
        quoted = desktop_editor.desktop_exec(["/usr/bin/python3", "/a b/c$d", 'say "hi"', "100%", "plain"])
        self.assertEqual(quoted, '/usr/bin/python3 "/a b/c\\$d" "say \\"hi\\"" 100%% plain')

    def test_editor_opens_as_an_app_window_or_falls_back(self):
        self.platform("linux", DISPLAY=":0", XDG_DATA_HOME=str(self.root / "data"))
        with mock.patch.object(desktop_editor, "detach") as detach, \
                mock.patch.object(desktop_editor, "app_browser", return_value="/usr/bin/chromium"):
            self.assertTrue(desktop_editor.open_editor("http://127.0.0.1:5/#token=x", self.policy))
            self.assertEqual(detach.call_args.args[0], ["/usr/bin/chromium", "--app=http://127.0.0.1:5/#token=x",
                                                        "--new-window"])
        with mock.patch.object(desktop_editor, "app_browser", return_value=None):
            self.assertFalse(desktop_editor.open_editor("http://127.0.0.1:5/#token=x", self.policy))

    def test_mac_finds_an_installed_chromium_browser(self):
        self.platform("darwin")
        edge = self.home / "Applications" / "Microsoft Edge.app" / "Contents" / "MacOS" / "Microsoft Edge"
        edge.parent.mkdir(parents=True)
        edge.write_text("", encoding="utf-8")
        with mock.patch.object(desktop_editor.Path, "is_file", lambda path: path == edge):
            self.assertEqual(desktop_editor.app_browser(), str(edge))

    def test_no_desktop_over_ssh_or_without_a_display(self):
        self.platform("linux", DISPLAY="", WAYLAND_DISPLAY="")
        self.assertIsNone(desktop_editor.unix_desktop())
        self.platform("darwin", SSH_CONNECTION="1.2.3.4 5 6.7.8.9 22")
        self.assertIsNone(desktop_editor.unix_desktop())
        self.assertFalse(desktop_editor.open_editor("http://127.0.0.1:5/", self.policy))


if __name__ == "__main__":
    unittest.main()
