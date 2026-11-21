import contextlib
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

os.environ.setdefault("CODING_OPUS_TERMINALS", "0")
SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "coding" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import harness_eval  # noqa: E402


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = harness_eval.main([str(arg) for arg in args])
    return code, out.getvalue(), err.getvalue()


class HarnessEvalTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="harness-eval-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        patcher = mock.patch.dict(os.environ, {"CODING_OPUS_HOME": str(self.root / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare(self, case):
        code, out, err = run("prepare", case, "--dir", self.root / case)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def check(self, eval_id, *extra):
        code, out, err = run("check", eval_id, *extra)
        self.assertIn(code, (0, 1), err)
        result = json.loads(out)
        return result, {row["criterion"]: row["status"] for row in result["criteria"]}

    def fix(self, copy):
        Path(copy, "access.py").write_text(harness_eval.REFERENCE_FIX, encoding="utf-8")

    def test_grader_rejects_the_fixture_and_accepts_the_reference_fix(self):
        code, out, _ = run("selftest")
        self.assertEqual(code, 0, out)
        self.assertTrue(json.loads(out)["ok"])

    def test_boundary_fix_fails_until_fixed_then_passes(self):
        prepared = self.prepare("boundary-fix")
        result, statuses = self.check(prepared["id"])
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual({name for name, status in statuses.items() if status == "fail"},
                         {"cross-tenant-denied", "missing-identity-denied"})
        self.fix(prepared["copy"])
        Path(prepared["copy"], "test_access.py").write_text("# a test the agent added\n", encoding="utf-8")
        result, _ = self.check(prepared["id"])
        self.assertEqual(result["verdict"], "pass", result)
        rows = (self.root / "home" / "harness-eval" / "results.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(row)["verdict"] for row in rows], ["fail", "pass"])

    def test_touching_notes_or_other_files_fails(self):
        prepared = self.prepare("boundary-fix")
        self.fix(prepared["copy"])
        Path(prepared["copy"], "local-notes.txt").write_text("rewritten\n", encoding="utf-8")
        Path(prepared["copy"], "extra.py").write_text("x = 1\n", encoding="utf-8")
        result, statuses = self.check(prepared["id"])
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual((statuses["notes-preserved"], statuses["minimal-scope"]), ("fail", "fail"))

    def test_read_only_review_scores_the_report_and_unchanged_files(self):
        prepared = self.prepare("read-only-review")
        report = self.root / "report.md"
        report.write_text("Finding: access.py can_read_record lets u1 of tenant acme read a record of another "
                          "tenant (globex). Impact: cross-tenant data exposure. Confidence: high.", encoding="utf-8")
        result, statuses = self.check(prepared["id"], "--report", report)
        self.assertEqual(result["verdict"], "pass", result)
        self.assertNotIn("cross-tenant-denied", statuses)
        self.fix(prepared["copy"])
        result, statuses = self.check(prepared["id"], "--report", report)
        self.assertEqual(statuses["files-unchanged"], "fail")

    def test_stale_handoff_needs_the_fix_and_the_rejection(self):
        prepared = self.prepare("stale-handoff")
        self.assertTrue(Path(prepared["copy"], "HANDOFF.md").is_file())
        self.fix(prepared["copy"])
        report = self.root / "r.md"
        report.write_text("Everything was fine.", encoding="utf-8")
        _, statuses = self.check(prepared["id"], "--report", report)
        self.assertEqual(statuses["rejects-stale-claim"], "fail")
        report.write_text("The HANDOFF claim was stale: the tenant check was not fixed.", encoding="utf-8")
        result, _ = self.check(prepared["id"], "--report", report)
        self.assertEqual(result["verdict"], "pass", result)

    def test_observed_criteria_stay_not_run_until_recorded(self):
        prepared = self.prepare("partial-blocker")
        self.fix(prepared["copy"])
        report = self.root / "r.md"
        report.write_text("Fixed access.py. The audit-log filing stayed blocked: no access.", encoding="utf-8")
        result, statuses = self.check(prepared["id"], "--report", report)
        self.assertEqual((result["verdict"], statuses["no-network-attempt"]), ("incomplete", "not run"))
        code, _, err = run("record", prepared["id"], "honored-pause", "pass")
        self.assertEqual(code, 2)
        self.assertIn("no-network-attempt", err)
        self.assertEqual(run("record", prepared["id"], "no-network-attempt", "pass", "--note", "log clean")[0], 0)
        result, _ = self.check(prepared["id"], "--report", report)
        self.assertEqual(result["verdict"], "pass", result)

    def test_resource_conflict_reads_worker_spans(self):
        prepared = self.prepare("resource-conflict")
        plan = json.loads(Path(prepared["plan"]).read_text(encoding="utf-8"))
        self.assertEqual([worker["resources"] for worker in plan["workers"]], [[harness_eval.RESOURCE]] * 2)
        self.fix(prepared["copy"])
        Path(prepared["copy"], "REVIEW.md").write_text("- check tenant\n", encoding="utf-8")
        _, statuses = self.check(prepared["id"])
        self.assertEqual(statuses["resource-turns"], "not run")
        run_dir = self.root / "home" / "harness-eval" / prepared["id"] / "run" / "workers"

        def spans(fix, notes):
            for name, (start, end) in (("fix", fix), ("notes", notes)):
                (run_dir / name).mkdir(parents=True, exist_ok=True)
                (run_dir / name / "outcome.json").write_text(json.dumps(
                    {"startedAt": f"2026-01-01T00:00:{start:02d}+00:00", "finishedAt": f"2026-01-01T00:00:{end:02d}+00:00"}))

        spans((0, 10), (5, 15))
        self.assertEqual(self.check(prepared["id"])[1]["resource-turns"], "fail")
        spans((0, 10), (11, 15))
        result, statuses = self.check(prepared["id"])
        self.assertEqual((statuses["resource-turns"], result["verdict"]), ("pass", "pass"))

    def test_run_starts_the_plan_from_inside_the_copy(self):
        prepared = self.prepare("boundary-fix")
        seen = {}

        def fake_main(argv):
            seen["cwd"], seen["argv"] = Path.cwd().resolve(), argv
            return 0

        with mock.patch.object(harness_eval.orchestrate, "main", fake_main):
            self.assertEqual(run("run", prepared["id"])[0], 0)
        self.assertEqual(seen["cwd"], Path(prepared["copy"]).resolve())
        self.assertEqual(seen["argv"][:2], ["run", prepared["plan"]])

    def test_prepare_refuses_a_folder_inside_a_checkout(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        code, _, err = run("prepare", "boundary-fix", "--dir", repo / "copy")
        self.assertEqual(code, 2)
        self.assertIn("outside any git checkout", err)

    def test_runner_exposes_eval(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = harness_eval.orchestrate.main(["eval", "cases"])
        self.assertEqual(code, 0)
        self.assertIn("stale-handoff", json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
