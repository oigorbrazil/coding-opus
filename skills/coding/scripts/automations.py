"""Scheduled agent tasks for Coding Opus, modeled on Orca automations.

An automation runs a prompt with an agent in one or more allowed remote-control projects (one task
per project, each with its own history entry) on a schedule
(hourly, daily, weekdays, weekly or a 5-field cron). The remote-control service is the host: it
checks the schedule while it runs and dispatches each run through RemoteJobs, so runs show up as
tasks in the panel too. A precheck command gates scheduled runs only; "run now" bypasses it.
A run missed while the service was off runs once if it is still within the grace window, and is
otherwise recorded as skipped_missed.
"""

import argparse
from contextlib import closing, contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import uuid

AGENTS = ("claude", "codex")
MODES = ("read-only", "write")
PRESETS = ("hourly", "daily", "weekdays", "weekly", "cron")
FINAL = ("completed", "dispatch_failed", "skipped_precheck", "skipped_missed", "skipped_unavailable")
TASK_STATUS = {"starting": "running", "running": "running", "stopping": "running", "needs_input": "needs_input",
               "completed": "completed", "failed": "failed", "stopped": "stopped"}
DEFAULT_GRACE_MINUTES = 60
DEFAULT_PRECHECK_SECONDS = 60
MAX_PRECHECK_SECONDS = 600
RUNS_KEPT = 200
MAX_PROJECTS = 20
FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
WEEKDAYS_PT = ("domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado")


class AutomationError(Exception):
    pass


def stamp(when):
    return when.replace(second=0, microsecond=0).isoformat(timespec="minutes")


def local_now():
    return dt.datetime.now()


# --- Schedules --------------------------------------------------------------------------------

def parse_field(text, low, high):
    values = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            if not raw_step.isdigit() or int(raw_step) < 1:
                raise AutomationError("Agenda cron inválida.")
            step = int(raw_step)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            first, last = part.split("-", 1)
            if not (first.isdigit() and last.isdigit()):
                raise AutomationError("Agenda cron inválida.")
            start, end = int(first), int(last)
        elif part.isdigit():
            start = int(part)
            end = high if step > 1 else start
        else:
            raise AutomationError("Agenda cron inválida.")
        if not low <= start <= end <= high:
            raise AutomationError("Agenda cron fora do intervalo.")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expression):
    parts = str(expression or "").split()
    if len(parts) != 5:
        raise AutomationError("A agenda cron precisa de 5 campos: minuto hora dia mês dia-da-semana.")
    minutes, hours, days, months, weekdays = (parse_field(part, *limits) for part, limits in zip(parts, FIELDS))
    return {"minutes": sorted(minutes), "hours": sorted(hours), "days": days, "months": months,
            "weekdays": {value % 7 for value in weekdays},
            "day_restricted": not parts[2].startswith("*"), "weekday_restricted": not parts[4].startswith("*")}


def day_matches(rule, day):
    weekday = (day.weekday() + 1) % 7  # cron: 0 = Sunday
    in_month, in_week = day.day in rule["days"], weekday in rule["weekdays"]
    if rule["day_restricted"] and rule["weekday_restricted"]:
        return in_month or in_week  # cron reads two restricted day fields as "either"
    return in_month and in_week


def next_occurrence(expression, after):
    """The first scheduled minute strictly after `after` (local, naive), within five years."""
    rule = parse_cron(expression)
    day = after.date()
    for _ in range(366 * 5):
        if day.month in rule["months"] and day_matches(rule, day):
            for hour in rule["hours"]:
                for minute in rule["minutes"]:
                    candidate = dt.datetime(day.year, day.month, day.day, hour, minute)
                    if candidate > after:
                        return candidate
        day += dt.timedelta(days=1)
    raise AutomationError("Esta agenda nunca acontece.")


def schedule_cron(preset, hour=9, minute=0, weekday=1, cron=None):
    if preset not in PRESETS:
        raise AutomationError("Agenda desconhecida.")
    if preset == "cron":
        parse_cron(cron)
        next_occurrence(cron, local_now())
        return " ".join(str(cron).split())
    if not (isinstance(hour, int) and 0 <= hour <= 23 and isinstance(minute, int) and 0 <= minute <= 59):
        raise AutomationError("Horário inválido.")
    if preset == "hourly":
        return f"{minute} * * * *"
    if preset == "daily":
        return f"{minute} {hour} * * *"
    if preset == "weekdays":
        return f"{minute} {hour} * * 1-5"
    if not (isinstance(weekday, int) and 0 <= weekday <= 6):
        raise AutomationError("Dia da semana inválido.")
    return f"{minute} {hour} * * {weekday}"


def describe(item):
    parts = item["cron"].split()
    if item["preset"] == "hourly":
        return f"De hora em hora, aos :{int(parts[0]):02d}"
    if item["preset"] == "cron":
        return f"Cron {item['cron']}"
    time = f"{int(parts[1]):02d}:{int(parts[0]):02d}"
    if item["preset"] == "daily":
        return f"Todo dia às {time}"
    if item["preset"] == "weekdays":
        return f"Dias úteis às {time}"
    return f"Toda {WEEKDAYS_PT[int(parts[4])]} às {time}"


# --- Store ------------------------------------------------------------------------------------

COLUMNS = ("id", "name", "prompt", "agent", "project", "mode", "model", "playbook", "isolate", "preset", "cron",
           "enabled", "precheck", "precheck_timeout", "grace_minutes", "reuse_session", "next_run", "last_run",
           "last_session", "created", "updated", "projects")
BOOLEAN = ("isolate", "enabled", "reuse_session")


class Automations:
    """Automations and their run history, stored next to the remote-control config."""

    def __init__(self, home, config_reader=None):
        self.home = Path(home)
        self.path = self.home / "automations.sqlite3"
        self.read_config = config_reader or (lambda: json.loads((self.home / "config.json").read_text(encoding="utf-8")))
        self.lock = threading.Lock()
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS automations (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL, agent TEXT NOT NULL,
                    project TEXT NOT NULL, mode TEXT NOT NULL, model TEXT, playbook TEXT,
                    isolate INTEGER NOT NULL DEFAULT 0, preset TEXT NOT NULL, cron TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, precheck TEXT, precheck_timeout INTEGER NOT NULL DEFAULT 60,
                    grace_minutes INTEGER NOT NULL DEFAULT 60, reuse_session INTEGER NOT NULL DEFAULT 0,
                    next_run TEXT, last_run TEXT, last_session TEXT, created TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, automation_id TEXT NOT NULL, trigger TEXT NOT NULL,
                    scheduled_for TEXT, created TEXT NOT NULL, status TEXT NOT NULL, task_id TEXT, detail TEXT
                );
                CREATE INDEX IF NOT EXISTS runs_by_automation ON runs(automation_id, created);
            """)
            # Added with multi-project automations; `project` stays the first one for older readers.
            if "projects" not in {row[1] for row in db.execute("PRAGMA table_info(automations)")}:
                db.execute("ALTER TABLE automations ADD COLUMN projects TEXT")
            if "project" not in {row[1] for row in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN project TEXT")

    @contextmanager
    def db(self):
        self.home.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    @staticmethod
    def row(raw):
        item = dict(raw)
        for key in BOOLEAN:
            item[key] = bool(item[key])
        try:
            projects = json.loads(item.get("projects") or "null")
        except ValueError:
            projects = None
        item["projects"] = projects if isinstance(projects, list) and projects else [item["project"]]
        item["schedule"] = describe(item)
        if item["preset"] != "cron":  # the form fields behind a preset, so an edit keeps them
            parts = item["cron"].split()
            item.update(minute=int(parts[0]), hour=9 if parts[1] == "*" else int(parts[1]),
                        weekday=int(parts[4]) if item["preset"] == "weekly" else 1)
        return item

    def config(self):
        """The remote-control config, only to resolve project names saved by older versions."""
        try:
            return self.read_config()
        except (OSError, ValueError):
            return {}

    @staticmethod
    def folder_of(entry, config):
        """A saved project: a folder path, or a remote-control project name from older versions."""
        known = config.get("projects", {}).get(entry)
        if known:
            return Path(known)
        path = Path(entry)
        return path if path.is_absolute() else None

    def normalize_folders(self, chosen, config):
        folders = []
        for entry in chosen:
            path = self.folder_of(entry.strip(), config)
            if path is None or not path.is_dir():
                raise AutomationError(f"Esta pasta não existe: {entry}")
            folders.append(str(path.resolve()))
        return list(dict.fromkeys(folders))

    def validate(self, data, current=None):
        merged = {**(current or {}), **{key: value for key, value in data.items() if key in COLUMNS or key in
                                         ("hour", "minute", "weekday")}}
        name = str(merged.get("name") or "").strip()
        prompt = str(merged.get("prompt") or "").strip()
        if not 1 <= len(name) <= 120 or "\n" in name:
            raise AutomationError("Dê um nome de até 120 caracteres.")
        if not 1 <= len(prompt) <= 50000:
            raise AutomationError("Escreva o pedido para o agente.")
        if merged.get("agent") not in AGENTS:
            raise AutomationError("Escolha claude ou codex.")
        mode = merged.get("mode") or "read-only"
        if mode not in MODES:
            raise AutomationError("Modo inválido.")
        config = self.config()
        if "projects" in data:
            chosen = data["projects"]
        elif "project" in data:
            chosen = [data["project"]]
        else:
            chosen = merged.get("projects") or ([merged["project"]] if merged.get("project") else [])
        if not isinstance(chosen, list) or not all(isinstance(key, str) for key in chosen):
            raise AutomationError("Projetos inválidos.")
        if not any(key.strip() for key in chosen):
            raise AutomationError("Escolha ao menos uma pasta.")
        if len(chosen) > MAX_PROJECTS:
            raise AutomationError(f"Escolha até {MAX_PROJECTS} pastas.")
        projects = self.normalize_folders([key for key in chosen if key.strip()], config)
        isolate = bool(merged.get("isolate"))
        if isolate and mode != "write":
            raise AutomationError("Uma worktree por execução só faz sentido no modo de edição.")
        reuse = bool(merged.get("reuse_session"))
        if reuse and isolate:
            raise AutomationError("Reaproveitar a sessão não combina com uma worktree nova por execução.")
        if reuse and len(projects) > 1:
            raise AutomationError("Reaproveitar a sessão só funciona com um projeto: cada projeto tem a sua.")
        if "preset" in data or "cron" in data or current is None or any(key in data for key in ("hour", "minute", "weekday")):
            cron = schedule_cron(merged.get("preset") or "daily", int(merged.get("hour", 9)), int(merged.get("minute", 0)),
                                 int(merged.get("weekday", 1)), merged.get("cron"))
        else:
            cron = merged["cron"]
        precheck = str(merged.get("precheck") or "").strip() or None
        if precheck and (len(precheck) > 2000 or "\n" in precheck):
            raise AutomationError("A pré-checagem é um comando de uma linha, até 2000 caracteres.")
        timeout = int(merged.get("precheck_timeout") or DEFAULT_PRECHECK_SECONDS)
        grace = int(merged.get("grace_minutes") if merged.get("grace_minutes") is not None else DEFAULT_GRACE_MINUTES)
        if not 1 <= timeout <= MAX_PRECHECK_SECONDS:
            raise AutomationError(f"O tempo da pré-checagem vai de 1 a {MAX_PRECHECK_SECONDS} segundos.")
        if not 0 <= grace <= 1440:
            raise AutomationError("A tolerância vai de 0 a 1440 minutos.")
        model = str(merged.get("model") or "").strip() or None
        playbook = str(merged.get("playbook") or "").strip() or None
        if (model and len(model) > 120) or (playbook and len(playbook) > 128):
            raise AutomationError("Modelo ou playbook inválido.")
        return {"name": name, "prompt": prompt, "agent": merged["agent"], "project": projects[0],
                "projects": json.dumps(projects), "mode": mode,
                "model": model, "playbook": playbook, "isolate": int(isolate), "preset": merged.get("preset") or "daily",
                "cron": cron, "enabled": int(merged.get("enabled", True) is not False), "precheck": precheck,
                "precheck_timeout": timeout, "grace_minutes": grace, "reuse_session": int(reuse)}

    def create(self, data, now=None):
        now = now or local_now()
        item = self.validate(data)
        item.update(id=str(uuid.uuid4()), created=stamp(now), updated=stamp(now), last_run=None, last_session=None,
                    next_run=stamp(next_occurrence(item["cron"], now)) if item["enabled"] else None)
        with self.lock, self.db() as db:
            db.execute(f"INSERT INTO automations({','.join(item)}) VALUES({','.join('?' * len(item))})", tuple(item.values()))
        return self.show(item["id"])

    def edit(self, automation_id, data, now=None):
        now = now or local_now()
        current = self.show(automation_id)
        item = self.validate(data, current)
        if item["enabled"] and (item["cron"] != current["cron"] or not current["enabled"] or not current["next_run"]):
            item["next_run"] = stamp(next_occurrence(item["cron"], now))
        elif not item["enabled"]:
            item["next_run"] = None
        if (item["reuse_session"] == 0 or json.loads(item["projects"]) != current["projects"]
                or item["agent"] != current["agent"]):
            item["last_session"] = None
        item["updated"] = stamp(now)
        with self.lock, self.db() as db:
            db.execute(f"UPDATE automations SET {','.join(key + '=?' for key in item)} WHERE id=?",
                       (*item.values(), automation_id))
        return self.show(automation_id)

    def remove(self, automation_id):
        with self.lock, self.db() as db:
            if not db.execute("DELETE FROM automations WHERE id=?", (automation_id,)).rowcount:
                raise AutomationError("Automação não encontrada.")
            db.execute("DELETE FROM runs WHERE automation_id=?", (automation_id,))

    def show(self, automation_id):
        with self.db() as db:
            raw = db.execute("SELECT * FROM automations WHERE id=?", (automation_id,)).fetchone()
        if raw is None:
            raise AutomationError("Automação não encontrada.")
        return self.row(raw)

    def listed(self):
        with self.db() as db:
            items = [self.row(raw) for raw in db.execute("SELECT * FROM automations ORDER BY name COLLATE NOCASE, id")]
            last = {raw["automation_id"]: dict(raw) for raw in db.execute("""
                SELECT * FROM runs WHERE rowid IN (SELECT MAX(rowid) FROM runs GROUP BY automation_id)""")}
        tasks = self.task_states([run["task_id"] for run in last.values() if run.get("task_id")])
        for item in items:
            run = last.get(item["id"])
            item["last"] = self.with_task(run, tasks) if run else None
        return items

    def request_run(self, automation_id, now=None):
        """Queue a manual run in each project; the host dispatches them on its next check, without the precheck."""
        item = self.show(automation_id)
        run_ids = []
        with self.lock, self.db() as db:
            for project in item["projects"]:
                run_ids.append(str(uuid.uuid4()))
                db.execute("INSERT INTO runs(id,automation_id,trigger,scheduled_for,created,status,project) "
                           "VALUES(?,?,?,?,?,?,?)",
                           (run_ids[-1], automation_id, "manual", None, stamp_seconds(now), "queued", project))
        return run_ids[0] if len(run_ids) == 1 else run_ids

    def runs(self, automation_id=None, limit=50):
        limit = max(1, min(int(limit), 200))
        with self.db() as db:
            if automation_id:
                rows = db.execute("SELECT * FROM runs WHERE automation_id=? ORDER BY rowid DESC LIMIT ?",
                                  (automation_id, limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM runs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        runs = [dict(row) for row in rows]
        tasks = self.task_states([run["task_id"] for run in runs if run.get("task_id")])
        return [self.with_task(run, tasks) for run in runs]

    def task_states(self, task_ids):
        """States and short results of dispatched runs, read from the RemoteJobs database."""
        jobs = self.home / "jobs.sqlite3"
        if not task_ids or not jobs.is_file():
            return {}
        with closing(sqlite3.connect(f"file:{jobs.as_posix()}?mode=ro", uri=True, timeout=5)) as db:
            marks = ",".join("?" * len(task_ids))
            return {row[0]: {"state": row[1], "error": row[2], "result": (row[3] or "")[-1500:]}
                    for row in db.execute(f"SELECT id,state,error,result FROM tasks WHERE id IN ({marks})", task_ids)}

    @staticmethod
    def with_task(run, tasks):
        task = tasks.get(run.get("task_id")) if run.get("task_id") else None
        if run["status"] == "dispatched" and task:
            run = {**run, "status": TASK_STATUS.get(task["state"], task["state"]),
                   "detail": run.get("detail") or task.get("error"), "result": task.get("result")}
        return run

    # --- Host side ------------------------------------------------------------------------------

    def record(self, automation_id, trigger, status, scheduled_for=None, task_id=None, detail=None, now=None,
               project=None):
        run_id = str(uuid.uuid4())
        with self.db() as db:
            db.execute("INSERT INTO runs(id,automation_id,trigger,scheduled_for,created,status,task_id,detail,project) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (run_id, automation_id, trigger, scheduled_for, stamp_seconds(now),
                                                     status, task_id, (detail or "")[:2000] or None, project))
            self.trim(db, automation_id)
        return run_id

    @staticmethod
    def trim(db, automation_id):
        db.execute("""DELETE FROM runs WHERE automation_id=? AND id NOT IN (
            SELECT id FROM runs WHERE automation_id=? ORDER BY rowid DESC LIMIT ?)
            AND status NOT IN ('queued')""", (automation_id, automation_id, RUNS_KEPT))

    def precheck(self, item, path):
        try:
            done = subprocess.run(item["precheck"], shell=True, cwd=str(path), capture_output=True, text=True,
                                  timeout=item["precheck_timeout"], stdin=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            return f"A pré-checagem passou de {item['precheck_timeout']} s."
        except OSError as error:
            return f"A pré-checagem não rodou: {error}"
        if done.returncode != 0:
            tail = (done.stdout or done.stderr or "").strip()[-300:]
            return f"A pré-checagem saiu com código {done.returncode}." + (f" {tail}" if tail else "")
        return None

    def dispatch(self, item, jobs, config, trigger, scheduled_for=None, run_id=None, now=None, project=None):
        """Start one run in one folder. Returns (status, task_id, detail) and records it."""
        from remote_jobs import RemoteError  # the host already imports it; keep this module light elsewhere
        project = project or item["projects"][0]
        path = self.folder_of(project, config)
        path = path.resolve() if path is not None and path.is_dir() else None
        status, task_id, detail = "dispatched", None, None
        if path is None:
            status, detail = "skipped_unavailable", "A pasta não existe mais."
        elif trigger == "schedule" and item["precheck"]:
            detail = self.precheck(item, path)
            if detail:
                status = "skipped_precheck"
        if status == "dispatched":
            request = "automation-" + (run_id or str(uuid.uuid4()))
            session = item["last_session"] if item["reuse_session"] else None
            try:
                try:
                    task = jobs.start(str(path), item["agent"], item["prompt"], request, item["mode"], item["model"],
                                      session, playbook=item["playbook"], isolate=item["isolate"], folder=str(path))
                except RemoteError:
                    if not session:
                        raise
                    task = jobs.start(str(path), item["agent"], item["prompt"], request + "-fresh", item["mode"],
                                      item["model"], None, playbook=item["playbook"], isolate=item["isolate"],
                                      folder=str(path))
                task_id = task["id"]
                with self.db() as db:
                    db.execute("UPDATE automations SET last_session=? WHERE id=?", (task.get("session_id"), item["id"]))
            except RemoteError as error:
                busy = "em andamento" in str(error)
                status, detail = ("skipped_unavailable" if busy else "dispatch_failed"), str(error)
        with self.db() as db:
            db.execute("UPDATE automations SET last_run=? WHERE id=?", (stamp_seconds(now), item["id"]))
            if run_id:
                db.execute("UPDATE runs SET status=?,task_id=?,detail=? WHERE id=?", (status, task_id, detail, run_id))
        if not run_id:
            self.record(item["id"], trigger, status, scheduled_for, task_id, detail, now, project)
        return status, task_id, detail

    def tick(self, jobs, now=None):
        """One scheduler pass: queued manual runs first, then due scheduled ones."""
        now = now or local_now()
        config = self.config()
        with self.db() as db:
            queued = [dict(row) for row in db.execute(
                "SELECT id, automation_id, project FROM runs WHERE status='queued' ORDER BY rowid")]
            due = [self.row(row) for row in db.execute(
                "SELECT * FROM automations WHERE enabled=1 AND next_run IS NOT NULL AND next_run<=?", (stamp(now),))]
        for run in queued:
            try:
                item = self.show(run["automation_id"])
            except AutomationError:
                with self.db() as db:
                    db.execute("DELETE FROM runs WHERE id=?", (run["id"],))
                continue
            project = run["project"] or item["projects"][0]
            if project not in item["projects"]:  # removed from the automation after "run now"
                with self.db() as db:
                    db.execute("DELETE FROM runs WHERE id=?", (run["id"],))
                continue
            with self.db() as db:
                db.execute("UPDATE runs SET status='dispatching', project=? WHERE id=?", (project, run["id"]))
            self.dispatch(item, jobs, config, "manual", run_id=run["id"], now=now, project=project)
        for item in due:
            scheduled = dt.datetime.fromisoformat(item["next_run"])
            with self.db() as db:  # move the schedule first, so a slow precheck or a crash never repeats a run
                db.execute("UPDATE automations SET next_run=? WHERE id=?", (stamp(next_occurrence(item["cron"], now)), item["id"]))
            missed = now - scheduled > dt.timedelta(minutes=item["grace_minutes"])
            for project in item["projects"]:  # one task per project; a busy one never blocks the others
                if missed:
                    self.record(item["id"], "schedule", "skipped_missed", item["next_run"],
                                detail=f"O serviço estava desligado no horário ({item['next_run'].replace('T', ' ')}).",
                                now=now, project=project)
                else:
                    self.dispatch(item, jobs, config, "schedule", scheduled_for=item["next_run"], now=now,
                                  project=project)


def stamp_seconds(now=None):
    return (now or local_now()).replace(microsecond=0).isoformat(timespec="seconds")


def run_scheduler(automations, jobs, finished, interval=15):
    """Host loop for the remote-control service."""
    while not finished.wait(interval):
        try:
            automations.tick(jobs)
        except Exception as error:  # the service must keep serving the panel
            print(f"Automation scheduler failed ({type(error).__name__}: {error})", file=sys.stderr, flush=True)


# --- CLI ----------------------------------------------------------------------------------------

def main(argv=None):
    from remote_control import remote_home
    parser = argparse.ArgumentParser(description="Automações agendadas da Coding Opus")
    parser.add_argument("--home", type=Path, default=remote_home())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    for name in ("show", "remove", "run"):
        commands.add_parser(name).add_argument("id")
    history = commands.add_parser("runs")
    history.add_argument("--id")
    history.add_argument("--limit", type=int, default=50)
    for name in ("create", "edit"):
        command = commands.add_parser(name)
        if name == "edit":
            command.add_argument("id")
        command.add_argument("--name")
        command.add_argument("--prompt")
        command.add_argument("--agent", choices=AGENTS)
        command.add_argument("--project", action="append", dest="projects",
                             help="repita para rodar em mais de um projeto")
        command.add_argument("--mode", choices=MODES)
        command.add_argument("--model")
        command.add_argument("--playbook")
        command.add_argument("--trigger", choices=PRESETS, dest="preset")
        command.add_argument("--time", help="HH:MM")
        command.add_argument("--day", type=int, help="0=domingo … 6=sábado, para weekly")
        command.add_argument("--cron")
        command.add_argument("--precheck")
        command.add_argument("--precheck-timeout", type=int, dest="precheck_timeout")
        command.add_argument("--grace-minutes", type=int, dest="grace_minutes")
        toggle = command.add_mutually_exclusive_group()
        toggle.add_argument("--enabled", action="store_true", default=None)
        toggle.add_argument("--disabled", action="store_true")
        command.add_argument("--isolate", action="store_true", default=None)
        command.add_argument("--reuse-session", action="store_true", default=None, dest="reuse_session")
    args = parser.parse_args(argv)
    store = Automations(args.home)
    try:
        if args.command == "list":
            result = store.listed()
        elif args.command == "show":
            result = store.show(args.id)
        elif args.command == "remove":
            store.remove(args.id)
            result = {"removed": args.id}
        elif args.command == "run":
            result = {"queued": store.request_run(args.id),
                      "note": "O serviço do controle remoto inicia a execução em até 15 segundos, sem a pré-checagem."}
        elif args.command == "runs":
            result = store.runs(args.id, args.limit)
        else:
            data = {key: getattr(args, key) for key in ("name", "prompt", "agent", "projects", "mode", "model", "playbook",
                                                         "preset", "cron", "precheck", "precheck_timeout", "grace_minutes",
                                                         "isolate", "reuse_session") if getattr(args, key) is not None}
            if args.time:
                hour, _, minute = args.time.partition(":")
                data.update(hour=int(hour), minute=int(minute or 0))
            if args.day is not None:
                data["weekday"] = args.day
            if args.disabled:
                data["enabled"] = False
            elif args.enabled:
                data["enabled"] = True
            result = store.create(data) if args.command == "create" else store.edit(args.id, data)
    except (AutomationError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
