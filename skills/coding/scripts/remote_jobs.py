"""Persistent remote requests executed through the existing Coding Opus runner."""

from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import uuid

import orchestrate as runner
from chat_memory import ChatMemory, atomic_text, now, private_prompt
import workspace_playbook as execution


class RemoteError(Exception):
    pass


def remote_home():
    return runner.default_policy_path().parent / "remote-control"


RUNNING = ('starting', 'running', 'stopping')
BUSY = (*RUNNING, 'needs_input')


def decode_options(task):
    return json.loads(task.get('options') or '{}')


class RemoteJobs:
    def __init__(self, config, launch=None):
        self.config = config
        self.home = Path(config["state_dir"])
        self.policy_path = Path(config.get('policy_path') or runner.default_policy_path()).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.processes = {}
        self.launch = launch or self.launch_runner
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, agent TEXT NOT NULL,
                    mode TEXT NOT NULL, model TEXT, native_id TEXT, account TEXT,
                    memory_id TEXT, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    request_id TEXT UNIQUE NOT NULL, prompt TEXT NOT NULL,
                    state TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
                    pid INTEGER, process_start TEXT, error TEXT, result TEXT,
                    native_id TEXT, memory_saved INTEGER NOT NULL DEFAULT 0
                );
            """)
            db.execute('BEGIN IMMEDIATE')
            for table, additions in {
                'sessions': {'project_path': 'TEXT', 'worktree': 'TEXT', 'branch': 'TEXT', 'base_commit': 'TEXT'},
                'tasks': {'options': 'TEXT', 'failure_kind': 'TEXT'},
            }.items():
                existing = {column['name'] for column in db.execute(f'PRAGMA table_info({table})')}
                for column, value_type in additions.items():
                    if column not in existing:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {value_type}')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.home / "jobs.sqlite3", timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def projects(self):
        return [{"id": key, "name": Path(value).name, "path": value}
                for key, value in self.config["projects"].items()]

    def project_path(self, project):
        configured = self.config['projects'].get(project) if isinstance(project, str) else None
        if not configured:
            raise RemoteError("Projeto não autorizado. Escolha um dos projetos cadastrados no computador.")
        path = Path(configured)
        if not path.is_dir() or str(path.resolve()) != configured:
            raise RemoteError("A pasta do projeto mudou ou ficou indisponível. Revise o cadastro no computador.")
        return path

    def task_folder(self, task_id):
        if not isinstance(task_id, str) or not task_id.isalnum() or len(task_id) != 32:
            raise RemoteError("Identificador de tarefa inválido")
        return self.home / "tasks" / task_id

    def session_path(self, db, session):
        if session.get('project_path'):
            return session['project_path']
        first = db.execute('SELECT id FROM tasks WHERE session_id=? ORDER BY rowid LIMIT 1', (session['id'],)).fetchone()
        try:
            return self.project_path_from_plan(self.task_folder(first['id'])) if first else None
        except (OSError, ValueError, KeyError, TypeError, IndexError, runner.PlanError):
            return None

    def permitted(self, db, session):
        configured = self.config['projects'].get(session['project'])
        return bool(configured and configured == self.session_path(db, session))

    def load_session(self, db, session_id):
        row = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        session = dict(row) if row else None
        if not session or not self.permitted(db, session):
            raise RemoteError('Sessão não encontrada')
        return session

    def load_task(self, db, task_id):
        self.task_folder(task_id)
        row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if row:
            try:
                return dict(row), self.load_session(db, row['session_id'])
            except RemoteError:
                pass
        raise RemoteError('Tarefa não encontrada')

    def list_sessions(self):
        self.refresh()
        allowlist = list(self.config['projects'])
        if not allowlist:
            return []
        placeholders = ','.join('?' for _ in allowlist)
        with self.db() as db:
            rows = db.execute(f"""SELECT s.*,t.id AS task_id,t.state AS task_state,t.prompt AS last_prompt,
                t.failure_kind AS task_failure_kind,t.options AS latest_options FROM sessions s
                LEFT JOIN tasks t ON t.id=(SELECT id FROM tasks WHERE session_id=s.id ORDER BY rowid DESC LIMIT 1)
                WHERE s.project IN ({placeholders}) ORDER BY s.updated DESC,s.rowid DESC LIMIT 50""", allowlist).fetchall()
            result = []
            for row in rows:
                session = dict(row)
                if not self.permitted(db, session):
                    continue
                session["title"] = (session.pop("last_prompt") or "").split("\n\nPedido atual\n")[-1][:140]
                session['playbook'] = json.loads(session.pop('latest_options') or '{}').get('playbook')
                session['task_attention'] = session['task_state'] not in (*RUNNING, 'succeeded', None)
                result.append(session)
            return result

    def list_tasks(self, session_id):
        self.refresh()
        with self.db() as db:
            session = self.load_session(db, session_id)
            rows = db.execute('SELECT * FROM tasks WHERE session_id=? ORDER BY rowid DESC LIMIT 30', (session_id,)).fetchall()
            session['project_path'] = self.session_path(db, session)
            return [self.task_snapshot(dict(row), session) for row in reversed(rows)]

    @staticmethod
    def local_folder(folder):
        """A folder chosen on this computer (automations), outside the remote-control project list."""
        path = Path(str(folder or ""))
        if not str(folder or "").strip() or not path.is_absolute() or not path.is_dir():
            raise RemoteError("A pasta escolhida não existe mais. Escolha outra na automação.")
        return path.resolve()

    def start(self, project, agent, prompt, request_id, mode='read-only', model=None, session_id=None, *,
              playbook=None, isolate=False, account=None, _inherit=None, folder=None):
        """`folder` is only for local callers (automations): the panel and the phone always pass a project key,
        and their later actions on that session still go through the project list, so they cannot reach it."""
        if agent not in ("claude", "codex"):
            raise RemoteError("Escolha claude ou codex")
        if mode not in ("read-only", "write"):
            raise RemoteError("Modo inválido")
        if mode == "write" and folder is None and not self.config.get("allow_write", False):
            raise RemoteError("Alterações estão desativadas neste servidor. Habilite-as no computador.")
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 50000:
            raise RemoteError("O pedido deve conter entre 1 e 50000 caracteres")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise RemoteError("Envie request_id único para permitir repetição segura em falhas de rede")
        if model is not None and (not isinstance(model, str) or len(model) > 120):
            raise RemoteError("Modelo inválido")
        if not isinstance(isolate, bool) or (isolate and mode != 'write'):
            raise RemoteError('O isolamento em worktree requer modo de edição.')
        if playbook is not None and (not isinstance(playbook, str) or not playbook or len(playbook) > 128):
            raise RemoteError('Playbook inválido.')
        if folder is not None:
            path = self.local_folder(folder)
            project = str(path)  # a path is never a project key, so the project list never resolves it
        else:
            path = self.project_path(project)
        try:
            book = execution.resolve_book(self.policy_path, playbook, mode) if playbook else None
            if account is not None:
                runner.validate_account_name(account)
                if account != 'default':
                    available = next((entry for entry in runner.account_entries(self.policy_path, agent)
                                      if entry['name'] == account and entry['available']
                                      and (not self.config.get('local_accounts') or not entry['linked'])), None)
                    if not available or not Path(available['home']).is_dir():
                        raise RemoteError('A conta escolhida não está disponível para esta execução.')
            if isolate and runner.checkout_root(path) is None:
                raise RemoteError('Este projeto não possui um repositório Git para criar a worktree.')
        except runner.PlanError as error:
            raise RemoteError(str(error)) from error
        options = {'playbook': playbook, 'isolate': isolate, 'account': account,
                   'source': _inherit['id'] if _inherit else None}
        with self.lock:
            self.refresh()
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("SELECT * FROM tasks WHERE request_id=?", (request_id,)).fetchone()
                if existing:
                    owner = self.own_session(db, existing['session_id'], project, folder is not None)
                    known_options = decode_options(dict(existing))
                    if ((session_id and owner['id'] != session_id) or existing['prompt'] != prompt
                            or owner['project'] != project or owner['agent'] != agent or owner['mode'] != mode
                            or owner['model'] != model or any(known_options.get(key, False if key == 'isolate' else None) != value
                                                            for key, value in options.items())):
                        raise RemoteError("request_id já pertence a outro pedido")
                    return self.task_snapshot(dict(existing), owner)
                if db.execute("""SELECT 1 FROM tasks t JOIN sessions s ON s.id=t.session_id
                    WHERE (s.project_path=? OR (s.project_path IS NULL AND s.project=?))
                      AND t.state IN ('starting','running','stopping','needs_input')""", (str(path), project)).fetchone():
                    raise RemoteError("Este projeto tem uma tarefa em andamento. Aguarde ou interrompa antes de enviar outra.")
                if session_id:
                    session = self.own_session(db, session_id, project, folder is not None)
                    if any(session[key] != value for key, value in
                           (("project", project), ("agent", agent), ("mode", mode), ("model", model))):
                        raise RemoteError("Sessão incompatível com projeto, agente, modelo ou modo")
                    if not session["native_id"]:
                        raise RemoteError('O agente não deixou uma sessão nativa. Use Continuar com contexto.')
                else:
                    session_id = uuid.uuid4().hex
                    session = {"id": session_id, "project": project, "agent": agent, "mode": mode,
                               'model': model, 'native_id': None, 'account': account,
                               'worktree': _inherit.get('worktree') if _inherit else None,
                               'branch': _inherit.get('branch') if _inherit else None,
                               'base_commit': _inherit.get('base_commit') if _inherit else None}
                    db.execute('''INSERT INTO sessions(id,project,agent,mode,model,updated,project_path,worktree,branch,base_commit,account)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (session_id, project, agent, mode, model, now(), str(path),
                        session['worktree'], session['branch'], session['base_commit'], account))
                cwd = self.workspace_path(path, session)
                task_id = uuid.uuid4().hex
                stamp = now()
                db.execute('INSERT INTO tasks(id,session_id,request_id,prompt,state,created,updated,options) VALUES(?,?,?,?,?,?,?,?)',
                           (task_id, session_id, request_id, prompt, 'starting', stamp, stamp, json.dumps(options)))
                db.execute('UPDATE sessions SET updated=? WHERE id=?', (stamp, session_id))
            folder = self.task_folder(task_id)
            try:
                folder.mkdir(parents=True, exist_ok=True)
                local = self.config.get('local_accounts', False)
                effective_account = session.get('account') or account or execution.policy_account(self.policy_path, agent, local)
                worker = {'id': 'remote', 'provider': agent, 'mode': mode, 'cwd': str(cwd), 'task': prompt,
                          'timeoutSeconds': self.config.get('timeout_seconds', 1200)}
                if session.get('native_id'):
                    worker['resume'] = session['native_id']
                if effective_account:
                    worker['account'] = effective_account
                if model:
                    worker['model'] = model
                if isolate and not session.get('worktree') and not book:
                    worker.update(isolate=True, branch='codex/opus-' + task_id[:16])
                plan = {'version': 1, 'strategy': 'economy', 'maxConcurrent': 1, 'workers': [worker],
                        'budget': {'maxCalls': 1, 'maxWallSeconds': worker['timeoutSeconds']}}
                runner.atomic_write_json(folder / 'plan.json', plan)
                if book:
                    runner.atomic_write_json(folder / execution.REQUEST, {
                        'project_path': str(path), 'policy_path': str(self.policy_path), 'book': book, 'playbook': playbook,
                        'agent': agent, 'mode': mode, 'model': model, 'account': effective_account, 'prompt': prompt,
                        'local_accounts': local, 'isolate': isolate, 'timeout_seconds': worker['timeoutSeconds'],
                        **{key: session.get(key) for key in ('worktree', 'branch', 'base_commit')},
                    })
                elif worker.get('branch'):
                    base = runner.run_git(cwd, ['rev-parse', 'HEAD']).decode().strip()
                    with self.db() as db:
                        db.execute('UPDATE sessions SET branch=?,base_commit=? WHERE id=?', (worker['branch'], base, session_id))
                memory = ChatMemory(self.config.get("brain"))
                if memory.enabled() and not private_prompt(prompt):
                    memory_id = memory.save(agent, "remote:" + session_id, str(path),
                                            [{"id": task_id, "role": "user", "content": prompt}], pending=task_id)
                    with self.db() as db:
                        db.execute("UPDATE sessions SET memory_id=? WHERE id=?", (memory_id, session_id))
                else:
                    with self.db() as db:
                        db.execute("UPDATE tasks SET memory_saved=1 WHERE id=?", (task_id,))
                self.launch_task(folder, task_id)
            except Exception as error:
                with self.db() as db:
                    db.execute("UPDATE tasks SET state='failed',error=?,failure_kind='launch_error',updated=? WHERE id=?",
                               (str(error)[:1500], now(), task_id))
            return self.get_task(task_id, local=folder is not None)

    def own_session(self, db, session_id, project, local):
        """A local caller reaches only sessions of the same local folder; everyone else goes through the list."""
        if not local:
            return self.load_session(db, session_id)
        row = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        if not row or row['project'] != project:
            raise RemoteError('Sessão não encontrada')
        return dict(row)

    def workspace_path(self, project, session):
        worktree = session.get('worktree')
        if not worktree:
            return project
        candidate = Path(worktree)
        root = runner.checkout_root(project)
        base = root / '.coding-opus' / 'worktrees' if root else None
        if (base is None or not candidate.is_dir() or candidate.parent != base
                or candidate.resolve() != candidate or runner.checkout_root(candidate) != candidate):
            raise RemoteError('A worktree desta sessão não está mais disponível.')
        def common_dir(path):
            gitdir = Path(runner.run_git(path, ['rev-parse', '--git-common-dir']).decode('utf-8').strip())
            return (path / gitdir).resolve()
        try:
            registered = common_dir(project) == common_dir(candidate)
        except runner.PlanError:
            registered = False
        if not registered:
            raise RemoteError('A worktree desta sessão não pertence mais a este repositório.')
        return candidate

    def launch_task(self, folder, task_id):
        process = self.launch(folder, task_id)
        self.processes[task_id] = process
        with self.db() as db:
            db.execute("UPDATE tasks SET state='running',pid=?,process_start=?,updated=? WHERE id=?",
                       (process.pid, runner.process_start_time(process.pid), now(), task_id))

    def launch_runner(self, folder, task_id):
        script = Path(runner.__file__).resolve()
        command = [sys.executable, str(script), '--session-id', 'remote-' + task_id, 'run', str(folder / 'plan.json'),
                   '--run-dir', str(folder / 'run'), '--policy', str(self.policy_path), '--_no-current', '--no-terminals']
        if (folder / execution.REQUEST).is_file():
            command = [sys.executable, str(Path(execution.__file__).resolve()), str(folder)]
        plan = runner.read_json(folder / 'plan.json')
        env = execution.runner_environment(plan['workers'][0].get('account'))
        with (folder / "runner.log").open("wb") as log:
            return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    cwd=plan['workers'][0]['cwd'], env=env,
                                    creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                                   | subprocess.CREATE_NO_WINDOW) if os.name == 'nt' else 0,
                                    start_new_session=os.name != "nt")

    def project_path_from_plan(self, folder):
        return json.loads((folder / "plan.json").read_text(encoding="utf-8"))["workers"][0]["cwd"]

    def refresh(self):
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            tasks = db.execute("SELECT * FROM tasks WHERE state IN ('starting','running','stopping') OR memory_saved=0").fetchall()
            for raw in tasks:
                task = dict(raw)
                folder = self.task_folder(task["id"])
                progress = runner.read_optional_json(folder / execution.PROGRESS)
                outcome = runner.read_optional_json(folder / 'run/workers/remote/outcome.json')
                session = dict(db.execute("SELECT * FROM sessions WHERE id=?", (task["session_id"],)).fetchone())
                if task['state'] in RUNNING and progress and progress['state'] not in ('starting', 'running'):
                    phase = progress['walk'][-1] if progress.get('walk') else {}
                    finished = progress['state'] != 'needs_input'
                    evidence = progress.get('outcome', {}) if phase.get('agent') == session['agent'] and finished else {}
                    update = {**progress, 'result': '\n\n'.join(progress['summaries'])[-20000:]}
                    update['native_id'] = evidence.get('sessionId')
                    update['account'] = evidence.get('account')
                    self.settle(db, task, session, update, native_replaced=finished)
                elif task['state'] in RUNNING and isinstance(outcome, dict) and outcome.get('finishedAt'):
                    update = {'state': outcome['status'], 'error': outcome.get('error'),
                              'result': execution.read_tail(folder / 'run/workers/remote/result.md', 20000),
                              'native_id': outcome.get('sessionId'), 'account': outcome.get('account'),
                              'worktree': outcome.get('worktree'), 'failureKind': outcome.get('failureKind')}
                    self.settle(db, task, session, update)
                elif task['state'] in RUNNING:
                    process = self.processes.get(task["id"])
                    if process is not None and process.pid != task['pid']:
                        if process.poll() is not None:
                            self.processes.pop(task['id'], None)
                        process = None
                    alive = (process is None or process.poll() is None) and runner.pid_alive(task['pid']) and (
                        not task['process_start'] or runner.process_start_time(task['pid']) == task['process_start'])
                    if alive or (task['state'] == 'starting' and not task['pid'] and self.is_starting(task)):
                        continue
                    error = execution.read_tail(folder / 'runner.log', 3000) or 'Execução encerrada sem resultado.'
                    self.settle(db, task, session, {'state': 'interrupted', 'error': error, 'failureKind': 'interrupted',
                                                    'worktree': (progress or {}).get('worktree'),
                                                    'branch': (progress or {}).get('branch'),
                                                    'base_commit': (progress or {}).get('base_commit')})
                if task['state'] not in RUNNING:
                    process = self.processes.pop(task["id"], None)
                    if process is not None:
                        if process.poll() is None:
                            self.processes[task['id']] = process
                if task['state'] not in BUSY and not task['memory_saved']:
                    memory = ChatMemory(self.config.get("brain"))
                    project = self.session_path(db, session)
                    if project and memory.enabled() and not private_prompt(task["prompt"]):
                        memory_id = memory.save(session["agent"], "remote:" + session["id"], project,
                            [{"id": task["id"], "role": "user", "content": task["prompt"]},
                             {"id": task["id"] + ":result", "role": "assistant", "content": task.get("result") or task.get("error") or task["state"]}])
                        memory.checkpoint(memory_id, (task.get("result") or task.get("error") or "")[:12000],
                                          "Revisar o resultado e enviar o próximo pedido.",
                                          "ativo" if task["state"] == "succeeded" else "interrompido")
                        db.execute("UPDATE sessions SET memory_id=? WHERE id=?", (memory_id, session["id"]))
                    db.execute("UPDATE tasks SET memory_saved=1 WHERE id=?", (task["id"],))

    def is_starting(self, task):
        try:
            started = dt.datetime.fromisoformat(task['updated'].replace('Z', '+00:00'))
            return (dt.datetime.now(dt.timezone.utc) - started).total_seconds() < 20
        except (TypeError, ValueError):
            return False

    def settle(self, db, task, session, update, native_replaced=False):
        stamp = now()
        db.execute('''UPDATE tasks SET state=?,error=?,result=?,native_id=?,failure_kind=?,updated=? WHERE id=?''',
                   (update['state'], update.get('error'), update.get('result'), update.get('native_id'),
                    update.get('failureKind'), stamp, task['id']))
        native_id = update.get('native_id')
        if not native_replaced and not native_id:
            native_id = session.get('native_id')
        db.execute('''UPDATE sessions SET native_id=?,account=COALESCE(?,account),worktree=COALESCE(?,worktree),
                    branch=COALESCE(?,branch),base_commit=COALESCE(?,base_commit),updated=? WHERE id=?''',
                   (native_id, update.get('account'), update.get('worktree'), update.get('branch'),
                    update.get('base_commit'), stamp, session['id']))
        task.update(state=update['state'], result=update.get('result'), error=update.get('error'))

    def task_snapshot(self, task, session):
        folder = self.task_folder(task["id"])
        options = decode_options(task)
        task = {key: value for key, value in task.items() if key not in ('pid', 'process_start', 'memory_saved', 'options')}
        task.update(project=session['project'], project_path=session.get('project_path'),
                    agent=session['agent'], model=session['model'], mode=session['mode'], account=session.get('account'),
                    worktree=session.get('worktree'), branch=session.get('branch'), base_commit=session.get('base_commit'),
                    playbook=options.get('playbook'), failureKind=task.get('failure_kind'))
        for key in ("prompt", "result", "error"):
            if task.get(key):
                task[key] = task[key][:20000]
        request = runner.read_optional_json(folder / execution.REQUEST)
        progress = runner.read_optional_json(folder / execution.PROGRESS) or {}
        run = folder / 'run'
        if request:
            latest = {phase['id']: phase for phase in progress.get('walk', [])}
            task['phases'] = []
            for phase in request['book']['phases']:
                detail = latest.get(phase['id'], {})
                inactive = 'queued' if task['state'] in BUSY else 'skipped'
                state = 'needs_input' if (progress.get('gate') or {}).get('phase') == phase['id'] else detail.get('state', inactive)
                task['phases'].append({'id': phase['id'], 'role': phase.get('role', phase['id']), 'state': state,
                                       'agent': detail.get('agent'), 'model': detail.get('model'), 'verdict': detail.get('verdict')})
            task['phase'] = progress.get('phase')
            task['gate'] = progress.get('gate') if task['state'] == 'needs_input' else None
            task['evidence'] = progress.get('evidence')
            task['checks'] = progress.get('gates', [])
            task['next_playbook'] = progress.get('next_playbook')
            for key in ('worktree', 'branch', 'base_commit'):
                task[key] = progress.get(key) or task[key]
            if progress.get('walk'):
                last = progress['walk'][-1]
                run = folder / last['run'] / 'run'
                for key in ('agent', 'model', 'account'):
                    task[key] = last.get(key) or task[key]
                if not task.get('result'):
                    task['result'] = progress.get('result')
        run_state = runner.read_optional_json(run / 'state.json') or {}
        worker = (run_state.get('workers') or {}).get('remote', {})
        task['worker_state'] = worker.get('status')
        task['worktree'] = task['worktree'] or worker.get('worktree')
        plan = runner.read_optional_json(run / 'plan.json') or {}
        resolved = (plan.get('workers') or [{}])[0]
        task['model'] = resolved.get('model') or task['model']
        task['account'] = task['account'] or resolved.get('account')
        data = run / 'workers' / 'remote'
        if not request:
            outcome = runner.read_optional_json(data / 'outcome.json') or {}
            if outcome.get('verdict') or outcome.get('workerSummary'):
                task['evidence'] = {'verdict': outcome.get('verdict'), 'summary': outcome.get('workerSummary')}
        log = execution.read_tail(data / 'stdout.log') or execution.read_tail(data / 'stderr.log')
        if log:
            task['output_tail'] = log
        return task

    def get_task(self, task_id, local=False):
        """`local` is for the caller that started it with a local folder; the panel never passes it."""
        self.task_folder(task_id)
        self.refresh()
        with self.db() as db:
            if local:
                row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                if not row:
                    raise RemoteError('Tarefa não encontrada')
                task = dict(row)
                session = dict(db.execute('SELECT * FROM sessions WHERE id=?', (task['session_id'],)).fetchone())
            else:
                task, session = self.load_task(db, task_id)
            task = self.task_snapshot(task, session)
            task['project_path'] = task['project_path'] or self.session_path(db, session)
            return task

    def send(self, session_id, prompt, request_id):
        with self.db() as db:
            row = self.load_session(db, session_id)
        return self.start(row["project"], row["agent"], prompt, request_id, row["mode"], row["model"], session_id)

    def stop(self, task_id):
        folder = self.task_folder(task_id)
        with self.lock:
            self.refresh()
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                task, session = self.load_task(db, task_id)
                if task['state'] not in BUSY:
                    return self.task_snapshot(task, session)
                folder.mkdir(exist_ok=True, parents=True)
                if decode_options(task).get('playbook'):
                    atomic_text(folder / execution.CANCEL, now())
                    if task['state'] == 'needs_input':
                        progress = runner.read_json(folder / execution.PROGRESS)
                        execution.journal(folder, progress, state='stopped', gate=None, failureKind='stopped')
                        self.settle(db, task, session, {**progress, 'result': task.get('result')})
                    else:
                        db.execute("UPDATE tasks SET state='stopping' WHERE id=?", (task_id,))
                else:
                    db.execute("UPDATE tasks SET state='stopping' WHERE id=?", (task_id,))
                    run_dir = folder / 'run'
                    run_dir.mkdir(exist_ok=True)
                    atomic_text(run_dir / runner.STOP_FILE, now())
                    if (run_dir / 'state.json').is_file():
                        runner.stop_payload(run_dir)
            return self.get_task(task_id)

    def gate(self, task_id, passed, note='', gate_id=None):
        if not isinstance(passed, bool) or not isinstance(note, str) or len(note) > 4000:
            raise RemoteError('Informe o resultado da checagem e uma observação de até 4000 caracteres.')
        folder = self.task_folder(task_id)
        with self.lock:
            self.refresh()
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                task, session = self.load_task(db, task_id)
                if session['mode'] == 'write' and not self.config.get('allow_write', False):
                    raise RemoteError('Alterações estão desativadas neste servidor.')
                self.workspace_path(self.project_path(session['project']), session)
                progress = runner.read_optional_json(folder / execution.PROGRESS) or {}
                waiting = progress.get('gate')
                if (task['state'] != 'needs_input' or not waiting or
                        (gate_id is not None and gate_id != waiting['id'])):
                    raise RemoteError('A execução não aguarda mais esta checagem. Atualize a página.')
                execution.journal(folder, progress, state='starting', decision={'passed': passed, 'note': note.strip()})
                db.execute("UPDATE tasks SET state='starting',pid=NULL,process_start=NULL,updated=? WHERE id=?", (now(), task_id))
            try:
                self.launch_task(folder, task_id)
            except OSError as error:
                execution.journal(folder, progress, state='needs_input', decision=None)
                with self.db() as db:
                    db.execute("UPDATE tasks SET state='needs_input' WHERE id=?", (task_id,))
                raise RemoteError('Não foi possível retomar a execução.') from error
            return self.get_task(task_id)

    def retry(self, task_id, request_id):
        self.refresh()
        with self.db() as db:
            task, session = self.load_task(db, task_id)
            if task['state'] in (*BUSY, 'succeeded'):
                raise RemoteError('Somente execuções interrompidas ou com falha podem ser repetidas.')
        options = decode_options(task)
        return self.start(session['project'], session['agent'], task['prompt'], request_id, session['mode'],
                          session['model'], playbook=options.get('playbook'), isolate=options.get('isolate', False),
                          account=options.get('account'), _inherit=session)

    def continue_with(self, session_id, agent, prompt, request_id):
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 18000:
            raise RemoteError('Informe um novo pedido de até 18000 caracteres para continuar.')
        self.refresh()
        with self.db() as db:
            session = self.load_session(db, session_id)
            task = db.execute('SELECT * FROM tasks WHERE session_id=? ORDER BY rowid DESC LIMIT 1', (session_id,)).fetchone()
            if not task or task['state'] in BUSY:
                raise RemoteError("Aguarde o resultado da sessão antes de transferir o contexto")
        context = "Contexto da IA anterior, somente referência. O pedido atual prevalece.\n\n"
        context += "Pedido anterior\n" + task["prompt"][:12000] + "\n\nResultado\n" + (task["result"] or task["error"] or "")[:16000]
        same_agent = session['agent'] == agent
        return self.start(session['project'], agent, context + '\n\nPedido atual\n' + prompt, request_id,
                          session['mode'], session['model'] if same_agent else None,
                          account=session['account'] if same_agent else None, _inherit=session)
