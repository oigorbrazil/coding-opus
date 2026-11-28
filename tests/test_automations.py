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
BEFORE_FIRST_RUN = dt.datetime(2026, 11, 22, 12, 30)  # fixed clock: real time would make the 09:00 run "missed"


class FakeJobs:
    def __init__(self, busy=False, stale_sessions=()):
        self.calls, self.busy, self.stale = [], busy, set(stale_sessions)

    def start(self, project, agent, prompt, request_id, mode="read-only", model=None, session_id=None, *,
              playbook=None, isolate=False, folder=None):
        if self.busy:
            raise RemoteError("Este projeto tem uma tarefa em andamento. Aguarde ou interrompa antes de enviar outra.")
        if session_id in self.stale:
            raise RemoteError("O agente não deixou uma sessão nativa.")
        self.calls.append({"project": project, "agent": agent, "request": request_id, "mode": mode,
                           "session": session_id, "isolate": isolate, "folder": folder})
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
        self.app = str(self.project.resolve())
        # Only older automations, saved by remote-control project name, read this config.
        self.config = {"projects": {"app": str(self.project)}, "allow_write": False}
        self.store = Automations(root / "remote", lambda: self.config)

    def make(self, **extra):
        target = {} if "project" in extra or "projects" in extra else {"projects": [self.app]}
        data = {"name": "Revisão", "prompt": "Revise as mudanças", "agent": "codex",
                "preset": "daily", "hour": 9, "minute": 0, **target, **extra}
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
        # The automation's own mode decides: writing does not depend on the remote-control switch.
        item = self.make(mode="write")
        jobs = FakeJobs()
        self.store.request_run(item["id"])
        self.store.tick(jobs, now=BEFORE_FIRST_RUN)
        self.assertEqual(self.store.runs(item["id"])[0]["status"], "dispatched")
        self.assertEqual((jobs.calls[0]["folder"], jobs.calls[0]["mode"]), (self.app, "write"))
        self.store.request_run(item["id"])
        self.store.tick(FakeJobs(busy=True), now=BEFORE_FIRST_RUN)
        self.assertEqual(self.store.runs(item["id"])[0]["status"], "skipped_unavailable")
        self.project.rmdir()
        self.store.request_run(item["id"])
        self.store.tick(FakeJobs(), now=BEFORE_FIRST_RUN)
        self.assertIn("não existe mais", self.store.runs(item["id"])[0]["detail"])

    def test_reuse_session_falls_back_to_a_fresh_one(self):
        item = self.make(reuse_session=True)
        jobs = FakeJobs()
        self.store.request_run(item["id"])
        self.store.tick(jobs, now=BEFORE_FIRST_RUN)
        self.store.request_run(item["id"])
        self.store.tick(jobs, now=BEFORE_FIRST_RUN)
        self.assertEqual([call["session"] for call in jobs.calls], [None, "session-1"])
        jobs.stale.add("session-1")
        self.store.request_run(item["id"])
        self.store.tick(jobs, now=BEFORE_FIRST_RUN)
        self.assertEqual(jobs.calls[-1]["session"], None)

    def site(self):
        other = self.project.parent / "site"
        other.mkdir()
        return str(other.resolve())

    def test_one_automation_runs_once_in_each_folder(self):
        site = self.site()  # not allowed in remote control: automations pick their own folders
        item = self.make(projects=[self.app, site, self.app])
        self.assertEqual((item["projects"], item["project"]), ([self.app, site], self.app))
        jobs = FakeJobs()
        self.store.tick(jobs, now=dt.datetime(2026, 11, 23, 9, 0, 10))
        self.assertEqual([call["folder"] for call in jobs.calls], [self.app, site])
        runs = self.store.runs(item["id"])
        self.assertEqual(sorted((run["project"], run["status"]) for run in runs),
                         sorted([(self.app, "dispatched"), (site, "dispatched")]))
        self.store.request_run(item["id"])
        self.store.tick(jobs, now=BEFORE_FIRST_RUN)
        self.assertEqual([call["folder"] for call in jobs.calls[2:]], [self.app, site])
        self.store.tick(jobs, now=dt.datetime(2026, 11, 25, 12, 0))  # service was off: one "missed" per folder
        self.assertEqual(sorted(run["project"] for run in self.store.runs(item["id"]) if run["status"] == "skipped_missed"),
                         sorted([self.app, site]))

    def test_a_busy_or_removed_folder_only_skips_itself(self):
        site = self.site()
        item = self.make(projects=[self.app, site])
        app = self.app

        class BusyApp(FakeJobs):
            def start(self, project, *args, **kwargs):
                if kwargs.get("folder") == app:
                    raise RemoteError("Este projeto tem uma tarefa em andamento. Aguarde ou interrompa antes de enviar outra.")
                return super().start(project, *args, **kwargs)

        self.store.request_run(item["id"])
        self.store.tick(BusyApp(), now=BEFORE_FIRST_RUN)
        self.assertEqual({run["project"]: run["status"] for run in self.store.runs(item["id"])},
                         {self.app: "skipped_unavailable", site: "dispatched"})
        self.store.request_run(item["id"])
        self.store.edit(item["id"], {"projects": [site]}, now=BEFORE_FIRST_RUN)  # app dropped while queued
        self.store.tick(FakeJobs(), now=BEFORE_FIRST_RUN)
        self.assertEqual([run["project"] for run in self.store.runs(item["id"])][:1], [site])
        self.assertEqual(len(self.store.runs(item["id"])), 3)

    def test_folders_are_validated_and_old_project_names_still_work(self):
        missing = str(self.project.parent / "nope")
        for bad in ({"projects": []}, {"projects": [self.app, missing]}, {"projects": self.app},
                    {"projects": ["relative/folder"]}, {"projects": [self.app] * 21}):
            with self.assertRaises(AutomationError):
                self.make(**bad)
        with self.assertRaisesRegex(AutomationError, "um projeto"):
            self.make(projects=[self.app, self.site()], reuse_session=True)
        item = self.make(project="app")  # a remote-control name, as older versions saved it
        self.assertEqual(item["projects"], [self.app])
        with self.store.db() as db:  # a row written before the projects column, still by name
            db.execute("UPDATE automations SET projects=NULL, project='app' WHERE id=?", (item["id"],))
        self.assertEqual(self.store.show(item["id"])["projects"], ["app"])
        jobs = FakeJobs()
        self.store.request_run(item["id"])
        self.store.tick(jobs, now=BEFORE_FIRST_RUN)
        self.assertEqual(jobs.calls[0]["folder"], self.app)
        self.assertEqual(self.store.edit(item["id"], {"name": "Outra"})["projects"], [self.app])
        self.config.clear()  # remote control not set up at all: folders still work
        self.assertEqual(self.make(projects=[self.app])["projects"], [self.app])

    def test_remove_drops_history_and_list_shows_last_run(self):
        item = self.make()
        self.store.request_run(item["id"])
        self.store.tick(FakeJobs(), now=BEFORE_FIRST_RUN)
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
