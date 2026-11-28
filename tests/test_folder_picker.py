"""The folder dialog: what each system runs and how its answers are read, without opening a window."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "coding" / "scripts"))
import folder_picker  # noqa: E402


def answer(code=0, out="", err=""):
    return lambda command, **kwargs: subprocess.CompletedProcess(command, code, out, err)


class FolderPickerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name) / "minha pasta"
        self.folder.mkdir()

    def test_a_chosen_folder_comes_back_absolute(self):
        self.assertEqual(folder_picker.pick_folder(run=answer(out=str(self.folder) + "\n")), str(self.folder.resolve()))

    def test_cancel_returns_none(self):
        self.assertIsNone(folder_picker.pick_folder(run=answer(out="")))
        with mock.patch.object(folder_picker.sys, "platform", "darwin"):
            self.assertIsNone(folder_picker.pick_folder(run=answer(1, err="execution error: User canceled. (-128)")))

    def test_a_broken_dialog_is_an_error_not_a_cancel(self):
        with mock.patch.object(folder_picker.sys, "platform", "darwin"):
            with self.assertRaisesRegex(folder_picker.PickerError, "Cole o caminho"):
                folder_picker.pick_folder(run=answer(1, err="Not authorized to send Apple events"))
        with self.assertRaises(folder_picker.PickerError):
            folder_picker.pick_folder(run=answer(1, err="Traceback: no display"))
        with self.assertRaisesRegex(folder_picker.PickerError, "não existe"):
            folder_picker.pick_folder(run=answer(out=str(self.folder / "sumiu")))

    def test_each_system_uses_its_own_dialog(self):
        with mock.patch.object(folder_picker.sys, "platform", "darwin"):
            self.assertEqual(folder_picker.commands(None)[0][0], "osascript")
        with mock.patch.object(folder_picker.sys, "platform", "linux"), \
                mock.patch.object(folder_picker.shutil, "which", lambda name: "/usr/bin/" + name):
            names = [command[0] for command in folder_picker.commands(str(self.folder))]
            self.assertEqual(names[:2], ["zenity", "kdialog"])
            self.assertEqual(names[2], sys.executable)  # Tk last
        with mock.patch.object(folder_picker.sys, "platform", "win32"):
            command = folder_picker.commands(str(self.folder))[0]
            self.assertEqual((command[0], command[-1]), (sys.executable, str(self.folder)))

    def test_falls_back_to_the_next_dialog_when_one_is_missing(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command[0])
            if command[0] == "zenity":
                raise FileNotFoundError("zenity")
            return subprocess.CompletedProcess(command, 0, str(self.folder), "")

        with mock.patch.object(folder_picker.sys, "platform", "linux"), \
                mock.patch.object(folder_picker.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None):
            self.assertEqual(folder_picker.pick_folder(run=run), str(self.folder.resolve()))
        self.assertEqual(calls, ["zenity", sys.executable])


if __name__ == "__main__":
    unittest.main()
