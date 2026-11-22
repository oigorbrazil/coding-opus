import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/coding/scripts" if (ROOT / "skills/coding/scripts").is_dir() else ROOT / "coding/scripts"
sys.path.insert(0, str(SCRIPTS))
from automations import AutomationError, Automations, next_occurrence, parse_cron, schedule_cron
from remote_jobs import RemoteError

MONDAY_9 = dt.datetime(2026, 11, 23, 9, 0)  # a Monday


class FakeJobs:
    def __init__(self, busy=False, stale_sessions=()):
        self.calls, self.busy, self.stale = [], busy, set(stale_sessions)

    def start(self, project, agent, prompt, request_id, mode="read-only", model=None, session_id=None, *,
              playbook=None, isolate=False):
        if self.busy:
            raise RemoteError("Este projeto tem uma tarefa em andamento. Aguarde ou interrompa antes de enviar outra.")
        if session_id in self.stale:
            raise RemoteError("O agente não deixou uma sessão nativa.")
        self.calls.append({"project": project, "agent": agent, "request": request_id, "mode": mode,
                           "session": session_id, "isolate": isolate})
        return {"id": f"task-{len(self.calls)}", "session_id": session_id or f"session-{len(self.calls)}"}


class ScheduleTest(unittest.TestCase):
    def test_presets_and_cron(self):
        self.assertEqual(schedule_cron("weekdays", 8, 30), "30 8 * * 1-5")
        self.assertEqual(schedule_cron("weekly", 18, 0, 5), "0 18 * * 5")
        self.assertEqual(next_occurrence("30 8 * * 1-5", dt.datetime(2026, 11, 21, 10, 0)), dt.datetime(2026, 11, 23, 8, 30))
        self.assertEqual(next_occurrence("15 * * * *", MONDAY_9), dt.datetime(2026, 11, 23, 9, 15))
        self.assertEqual(next_occurrence("0 9 * * *", MONDAY_9), dt.datetime(2026, 11, 24, 9, 0))
        self.assertEqual(next_occurrence("0 0 1,15 * 0", dt.datetime(2026, 11, 23)), dt.datetime(2026, 11, 29))  # OR
        self.assertEqual(next_occurrence("*/20 9 * * 7", dt.datetime(2026, 11, 29, 9, 5)), dt.datetime(2026, 11, 29, 9, 20))
        self.assertEqual(sorted(parse_cron("0 0 * * *")["weekdays"]), list(range(7)))
        for bad in ("* * *", "60 * * * *", "0 0 31 2 *", "a b c d e"):
            with self.assertRaises(AutomationError):
                next_occurrence(bad, MONDAY_9)


class AutomationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.project = root / "app"
        self.project.mkdir()
        self.config = {"projects": {"app": str(self.project)}, "allow_write": False}
        self.store = Automations(root / "remote", lambda: self.config)

    def make(self, **extra):
        data = {"name": "Revisão", "prompt": "Revise as mudanças", "agent": "codex", "project": "app",
                "preset": "daily", "hour": 9, "minute": 0, **extra}
        return self.store.create(data, now=dt.datetime(2026, 11, 22, 12, 0))

    def test_create_validates_and_plans_the_next_run(self):
        item = self.make()
        self.assertEqual((item["next_run"], item["schedule"], item["mode"]), ("2026-11-23T09:00", "Todo dia às 09:00", "read-only"))
        for bad in ({"project": "outro"}, {"agent": "gpt"}, {"isolate": True}, {"preset": "cron", "cron": "1 2 3"},
                    {"mode": "write", "isolate": True, "reuse_session": True}, {"precheck": "a\nb"}):
            with self.assertRaises(AutomationError):
                self.make(**bad)
        edited = self.store.edit(item["id"], {"preset": "weekly", "weekday": 5}, now=dt.datetime(2026, 11, 22, 12, 0))
        self.assertEqual((edited["cron"], edited["next_run"]), ("0 9 * * 5", "2026-11-27T09:00"))
        self.assertIsNone(self.store.edit(item["id"], {"enabled": False})["next_run"])

    def test_due_runs_dispatch_once_and_missed_runs_are_skipped(self):
        item = self.make()
        jobs = FakeJobs()
        self.store.tick(jobs, now=dt.datetime(2026, 11, 23, 8, 59))
        self.assertEqual(jobs.calls, [])
        self.store.tick(jobs, now=dt.datetime(2026, 11, 23, 9, 0, 10))
        self.store.tick(jobs, now=dt.datetime(2026, 11, 23, 9, 0, 40))
        self.assertEqual(len(jobs.calls), 1)
        self.assertEqual(self.store.show(item["id"])["next_run"], "2026-11-24T09:00")
        self.store.tick(jobs, now=dt.datetime(2026, 11, 24, 12, 0))  # service was off for three hours
        self.assertEqual(len(jobs.calls), 1)
        self.assertEqual([run["status"] for run in self.store.runs(item["id"])], ["skipped_missed", "dispatched"])
        self.assertEqual(self.store.show(item["id"])["next_run"], "2026-11-25T09:00")

    def test_precheck_gates_schedules_but_run_now_bypasses_it(self):
        failing = f'"{sys.executable}" -c "import sys; sys.exit(3)"'
        item = self.make(precheck=failing)
        jobs = FakeJobs()
        self.store.tick(jobs, now=dt.datetime(2026, 11, 23, 9, 1))
        run = self.store.runs(item["id"])[0]
        self.assertEqual(run["status"], "skipped_precheck")
        self.assertIn("código 3", run["detail"])
        self.store.request_run(item["id"])
        self.store.tick(jobs, now=dt.datetime(2026, 11, 23, 10, 0))
        self.assertEqual(len(jobs.calls), 1)
        self.assertEqual(self.store.runs(item["id"])[0]["trigger"], "manual")

    def test_unavailable_and_failed_dispatches(self):
        item = self.make(mode="write")
        self.store.request_run(item["id"])
        self.store.tick(FakeJobs())
        self.assertEqual(self.store.runs(item["id"])[0]["status"], "skipped_unavailable")
        self.config["allow_write"] = True
        self.store.request_run(item["id"])
        self.store.tick(FakeJobs(busy=True))
        self.assertEqual(self.store.runs(item["id"])[0]["status"], "skipped_unavailable")
        self.config["projects"] = {}
        self.store.request_run(item["id"])
        self.store.tick(FakeJobs())
        self.assertIn("não está mais liberado", self.store.runs(item["id"])[0]["detail"])

    def test_reuse_session_falls_back_to_a_fresh_one(self):
        item = self.make(reuse_session=True)
        jobs = FakeJobs()
        self.store.request_run(item["id"])
        self.store.tick(jobs)
        self.store.request_run(item["id"])
        self.store.tick(jobs)
        self.assertEqual([call["session"] for call in jobs.calls], [None, "session-1"])
        jobs.stale.add("session-1")
        self.store.request_run(item["id"])
        self.store.tick(jobs)
        self.assertEqual(jobs.calls[-1]["session"], None)

    def test_remove_drops_history_and_list_shows_last_run(self):
        item = self.make()
        self.store.request_run(item["id"])
        self.store.tick(FakeJobs())
        listed = self.store.listed()
        self.assertEqual(listed[0]["last"]["status"], "dispatched")
        self.store.remove(item["id"])
        self.assertEqual((self.store.listed(), self.store.runs()), ([], []))
        with self.assertRaises(AutomationError):
            self.store.remove(item["id"])

    def test_cli_round_trip(self):
        from automations import main
        home = self.store.home
        (home / "config.json").write_text(json.dumps(self.config), encoding="utf-8")
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--home", str(home), "create", "--name", "Diária", "--prompt", "Oi", "--agent", "claude",
                                   "--project", "app", "--trigger", "weekdays", "--time", "08:15"]), 0)
        created = json.loads(out.getvalue())
        self.assertEqual(created["cron"], "15 8 * * 1-5")


if __name__ == "__main__":
    unittest.main()
