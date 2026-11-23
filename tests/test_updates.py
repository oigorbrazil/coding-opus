"""Check for updates: compare the installed skill with GitHub's tree, without the network."""

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "coding" / "scripts"))
import updates  # noqa: E402


class UpdateCheckTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "scripts").mkdir()
        (self.root / "SKILL.md").write_bytes(b'---\nmetadata:\n  version: "37"\n---\n')
        (self.root / "scripts" / "a.py").write_bytes(b"print('a')\r\nprint('b')\r\n")  # a Windows checkout
        (self.root / "icon.png").write_bytes(b"\x89PNG\0\r\n")
        self.remote = {
            "skills/coding/SKILL.md": updates.blob_hash(b'---\nmetadata:\n  version: "37"\n---\n'),
            "skills/coding/scripts/a.py": updates.blob_hash(b"print('a')\nprint('b')\n"),
            "skills/coding/icon.png": updates.blob_hash(b"\x89PNG\0\r\n"),
            "README.md": "ignored-outside-the-skill",
        }

    def fetch(self, url):
        if url.endswith("/commits/main"):
            return {"sha": "a931c1e5f00d", "commit": {"tree": {"sha": "tree1"}, "message": "Usage bar\n\nbody",
                                                       "committer": {"date": "2026-11-23T01:26:38Z"}}}
        self.assertIn("/git/trees/tree1?recursive=1", url)
        return {"truncated": False,
                "tree": [{"path": path, "type": "blob", "sha": sha} for path, sha in self.remote.items()]}

    def test_up_to_date_even_with_windows_line_endings(self):
        report = updates.check(self.root, fetch=self.fetch)
        self.assertTrue(report["upToDate"], report)
        self.assertEqual(report["version"], "37")
        self.assertEqual(report["latest"], {"commit": "a931c1e", "date": "2026-11-23T01:26:38Z", "title": "Usage bar"})

    def test_changed_and_new_files_mean_an_update(self):
        self.remote["skills/coding/scripts/a.py"] = updates.blob_hash(b"print('new')\n")
        self.remote["skills/coding/scripts/new.py"] = updates.blob_hash(b"x")
        report = updates.check(self.root, fetch=self.fetch)
        self.assertFalse(report["upToDate"])
        self.assertEqual((report["changed"], report["missing"]), (["scripts/a.py"], ["scripts/new.py"]))
        self.assertIn("npx skills add", report["howto"])

    def test_binary_files_are_never_line_end_normalized(self):
        (self.root / "icon.png").write_bytes(b"\x89PNG\0\n")
        self.remote["skills/coding/icon.png"] = updates.blob_hash(b"\x89PNG\0\n".replace(b"\n", b"\r\n"))
        self.assertEqual(updates.check(self.root, fetch=self.fetch)["changed"], ["icon.png"])

    def test_errors_come_back_as_plain_messages(self):
        def offline(url):
            raise updates.UpdateError("Não foi possível falar com o GitHub.")

        with self.assertRaises(updates.UpdateError):
            updates.check(self.root, fetch=offline)
        with self.assertRaises(updates.UpdateError):
            updates.check(self.root, fetch=lambda url: {"unexpected": True})

    def test_blob_hash_matches_git(self):
        # `git hash-object` of "hello\n"
        self.assertEqual(updates.blob_hash(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")


if __name__ == "__main__":
    unittest.main()
