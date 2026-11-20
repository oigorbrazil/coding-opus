"""Independent account profiles; provider CLIs own sign-in and credentials."""
from __future__ import annotations

import base64
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid

import orchestrate

LOGIN_TIMEOUT = 600
MARKER = '.coding-opus-profile.json'
AUTH_HOSTS = {
    'codex': {'auth.openai.com', 'chatgpt.com'},
    'claude': {'claude.ai', 'claude.com', 'console.anthropic.com'},
}
CREDENTIAL_ENV = ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'OPENAI_BASE_URL',
                  'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_BASE_URL')


class AccountError(Exception):
    pass


def selected_account(policy, provider):
    if provider not in orchestrate.ACCOUNT_PROVIDERS:
        return 'default', None
    order = orchestrate.account_rotation(policy, provider)
    name = order[0] if order else 'default'
    return name, orchestrate.account_home(policy, provider, name)


def profile_environment(provider, home):
    env = orchestrate.account_environment(provider, home)
    if home is not None:
        for key in CREDENTIAL_ENV:
            env.pop(key, None)
    return env


def sign_in_prompt(provider, output):
    plain = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', output)
    links = []
    for raw in re.findall(r'https://[^\s<>]+(?=\s)', plain):
        value = raw.rstrip(')\'".,')
        try:
            parsed = urllib.parse.urlsplit(value)
        except ValueError:
            continue
        if parsed.hostname in AUTH_HOSTS[provider] and not parsed.username and not parsed.password:
            links.append(value)
    url = next((value for value in links if urllib.parse.parse_qs(urllib.parse.urlsplit(value).query).get('code') == ['true']), links[0] if links else None)
    needs_code = provider == 'claude' and bool(url and urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get('code') == ['true'])
    code = None
    if provider == 'codex':
        match = re.search(r'^\s*([A-Z0-9]{4,8}-[A-Z0-9]{4,8})\s*$', plain, re.MULTILINE)
        code = match.group(1) if match else None
    return {'url': url, 'userCode': code, 'needsCode': needs_code}


@contextlib.contextmanager
def account_transaction(policy):
    policy.parent.mkdir(parents=True, exist_ok=True)
    with (policy.parent / '.coding-opus-accounts.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + 3
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AccountError('busy') from None
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


def auth_info(provider, home):
    command = [*orchestrate.launch_command(orchestrate.resolve_executable(provider)),
               *orchestrate.AUTH_COMMANDS[provider]]
    process = orchestrate.start_process(command, home, subprocess.DEVNULL, subprocess.PIPE,
                                        subprocess.PIPE, profile_environment(provider, home))
    try:
        stdout, stderr = process.communicate(timeout=15)
        if provider == 'claude':
            value = json.loads(stdout)
            email = value.get('email')
            return {'authenticated': value.get('loggedIn') is True,
                    'email': email if isinstance(email, str) and len(email) <= 320 else None}
        output = (stdout + stderr).decode('utf-8', errors='replace').lower()
        email = None
        try:
            raw = json.loads((home / 'auth.json').read_text(encoding='utf-8'))
            token = raw.get('tokens', {}).get('id_token', '')
            segment = token.split('.')[1]
            email = json.loads(base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))).get('email')
        except (OSError, ValueError, IndexError, AttributeError):
            pass
        return {'authenticated': process.returncode == 0 and 'logged in' in output and 'not logged in' not in output,
                'email': email if isinstance(email, str) and len(email) <= 320 else None}
    finally:
        orchestrate.stop_process_tree(process)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()


def start_login(provider, home):
    command = [*orchestrate.launch_command(orchestrate.resolve_executable(provider))]
    command += ['login', '--device-auth'] if provider == 'codex' else ['auth', 'login', '--claudeai']
    return orchestrate.start_process(command, home, subprocess.PIPE, subprocess.PIPE,
                                     subprocess.PIPE, profile_environment(provider, home))


class AccountManager:
    def __init__(self, policy, starter=start_login, checker=auth_info):
        self.policy = policy
        self.starter, self.checker = starter, checker
        self.lock = threading.RLock()
        self.jobs = {}
        self.identities = {}
        self.usage = None

    def _entries(self, provider):
        return orchestrate.load_accounts(self.policy)['providers'][provider]

    def _select(self, provider, name):
        entries = {row['name']: row for row in orchestrate.account_entries(self.policy, provider)}
        if name != 'default' and (name not in entries or not entries[name]['available']):
            raise AccountError('account-not-ready')
        order = orchestrate.account_rotation(self.policy, provider) or ['default']
        orchestrate.order_accounts(self.policy, provider, [name, *(item for item in order if item != name)])

    def _owned_delete(self, home, provider, name):
        root = orchestrate.accounts_root(self.policy).resolve()
        path = Path(home)
        try:
            relative = path.resolve().relative_to(root)
            marker = json.loads((path / MARKER).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise AccountError('external-data-preserved') from None
        if not isinstance(marker, dict) or len(relative.parts) != 2 or relative.parts[0] != provider or path.is_symlink() or \
                getattr(path, 'is_junction', lambda: False)() or marker.get('provider') != provider or marker.get('name') != name:
            raise AccountError('external-data-preserved')
        shutil.rmtree(path)

    def snapshot(self):
        with self.lock:
            accounts = orchestrate.accounts_summary(self.policy)
            selected = {}
            for provider, rows in accounts['providers'].items():
                selected[provider] = selected_account(self.policy, provider)[0]
                for row in rows:
                    row['selected'] = row['name'] == selected[provider]
                    row['manageable'] = row['from'] == 'coding-opus'
                    identity = self.identities.get((provider, row['name']), {})
                    if not identity and row['manageable']:
                        entry = next((entry for entry in self._entries(provider) if entry['name'] == row['name']), None)
                        try:
                            marker = json.loads((Path(entry['home']) / MARKER).read_text(encoding='utf-8')) if entry else {}
                            if isinstance(marker, dict):
                                email = marker.get('email')
                                identity = {'authenticated': marker.get('verified') is True,
                                            'email': email if isinstance(email, str) and len(email) <= 320 else None}
                        except (OSError, ValueError):
                            pass
                    row['authenticated'] = identity.get('authenticated')
                    row['email'] = identity.get('email') or row['email']
            logins = [{key: job.get(key) for key in ('id', 'provider', 'name', 'state', 'url', 'userCode', 'needsCode', 'error')}
                      for job in self.jobs.values()]
            return {'ok': True, 'accounts': accounts, 'selected': selected, 'logins': logins}

    def _scan(self, job, stream):
        try:
            while True:
                chunk = stream.read1(1024)
                if not chunk:
                    return
                with self.lock:
                    if job['state'] != 'pending':
                        return
                    job['output'] = (job['output'] + chunk.decode('utf-8', errors='replace'))[-32000:]
                    prompt = sign_in_prompt(job['provider'], job['output'])
                    if prompt['url']:
                        job.update(prompt)
        except (OSError, ValueError):
            return

    def _run_login(self, job):
        process = None
        registered = False
        try:
            process = self.starter(job['provider'], job['home'])
            with self.lock:
                job['process'] = process
            for stream in (process.stdout, process.stderr):
                threading.Thread(target=self._scan, args=(job, stream), daemon=True).start()
            deadline = time.monotonic() + LOGIN_TIMEOUT
            while process.poll() is None and not job['cancel'].is_set() and time.monotonic() < deadline:
                job['cancel'].wait(0.1)
            if job['cancel'].is_set():
                raise AccountError('cancelled')
            if process.poll() is None:
                raise AccountError('login-timeout')
            if process.returncode != 0:
                raise AccountError('login-failed')
            identity = self.checker(job['provider'], job['home'])
            if identity.get('authenticated') is not True:
                raise AccountError('login-failed')
            with self.lock, account_transaction(self.policy):
                data = orchestrate.load_accounts(self.policy)
                rows = data['providers'][job['provider']]
                previous = next((row for row in rows if row['name'] == job['name']), None)
                if (previous is not None) != job['reauth']:
                    raise AccountError('account-changed')
                if job['cancel'].is_set():
                    raise AccountError('cancelled')
                current = selected_account(self.policy, job['provider'])[0]
                entry = {'name': job['name'], 'home': str(job['home']), 'addedAt': orchestrate.now_iso()}
                if previous:
                    previous.update(entry)
                else:
                    rows.append(entry)
                (job['home'] / MARKER).write_text(json.dumps({'provider': job['provider'], 'name': job['name'],
                    'verified': True, 'email': identity.get('email')}), encoding='utf-8')
                orchestrate.save_accounts(self.policy, data)
                registered = True
                if current == job['previousSelected']:
                    self._select(job['provider'], job['name'])
                self.identities[(job['provider'], job['name'])] = identity
                job['state'] = 'complete'
        except AccountError as error:
            with self.lock:
                job.update(state='cancelled' if str(error) == 'cancelled' else 'error', error=str(error))
        except (OSError, ValueError, TypeError, orchestrate.PlanError, subprocess.SubprocessError):
            with self.lock:
                job.update(state='error', error='login-failed')
        finally:
            if process:
                orchestrate.stop_process_tree(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()
            if not registered:
                try:
                    self._owned_delete(job['home'], job['provider'], job['name'])
                except (OSError, AccountError):
                    pass
            with self.lock:
                job.update(url=None, userCode=None, needsCode=False, output='', process=None)

    def _begin(self, provider, name, reauth):
        if name == 'default':
            raise AccountError('system-account')
        entries = self._entries(provider)
        existing = next((row for row in entries if row['name'] == name), None)
        if reauth and existing is None:
            raise AccountError('linked-account')
        if not reauth and any(row['name'] == name for row in orchestrate.account_entries(self.policy, provider)):
            raise AccountError('account-exists')
        if any(job['provider'] == provider and job['state'] == 'pending' for job in self.jobs.values()):
            raise AccountError('login-busy')
        folder = orchestrate.accounts_root(self.policy) / provider / f'{name}.{uuid.uuid4().hex}'
        folder.mkdir(parents=True, mode=0o700)
        (folder / MARKER).write_text(json.dumps({'provider': provider, 'name': name}), encoding='utf-8')
        job = {'id': uuid.uuid4().hex, 'provider': provider, 'name': name, 'state': 'pending',
               'home': folder, 'reauth': reauth, 'previousSelected': selected_account(self.policy, provider)[0],
               'cancel': threading.Event(), 'process': None, 'output': ''}
        self.jobs[provider] = job
        thread = threading.Thread(target=self._run_login, args=(job,), daemon=True)
        job['thread'] = thread
        thread.start()

    def action(self, request):
        try:
            if not isinstance(request, dict):
                raise AccountError('invalid-request')
            action, provider = request.get('action'), request.get('provider')
            if action == 'state':
                return self.snapshot()
            if action == 'usage':
                with self.lock:
                    if self.usage is None:
                        from usage_refresh import UsageRefresh
                        self.usage = UsageRefresh(self.policy)
                _, settings = orchestrate.loaded_playbooks(self.policy)
                return {'ok': True, 'value': self.usage.refresh(settings.get('providers', ['codex', 'claude']))}
            if provider not in orchestrate.ACCOUNT_PROVIDERS:
                raise AccountError('invalid-provider')
            name = request.get('name')
            if action in ('add', 'login', 'select', 'remove'):
                try:
                    orchestrate.validate_account_name(name)
                except orchestrate.PlanError:
                    raise AccountError('invalid-name') from None
            with self.lock:
                if action in ('add', 'login'):
                    self._begin(provider, name, action == 'login')
                elif action == 'order':
                    names = request.get('names')
                    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                        raise AccountError('invalid-request')
                    with account_transaction(self.policy):
                        orchestrate.order_accounts(self.policy, provider, names)
                elif action == 'select':
                    with account_transaction(self.policy):
                        self._select(provider, name)
                elif action in ('cancel', 'input'):
                    job = self.jobs.get(provider)
                    if not job or job['id'] != request.get('loginId') or job['state'] != 'pending':
                        raise AccountError('login-not-pending')
                    if action == 'cancel':
                        job['cancel'].set()
                    else:
                        code = request.get('code')
                        if not job.get('needsCode') or not job.get('process') or not isinstance(code, str) or \
                                not code.strip() or len(code) > 4096 or any(ord(ch) < 32 for ch in code):
                            raise AccountError('invalid-code')
                        job['process'].stdin.write((code.strip() + '\n').encode('utf-8'))
                        job['process'].stdin.flush()
                        job['needsCode'] = False
                elif action == 'remove':
                    if name == 'default':
                        raise AccountError('system-account')
                    if any(job['name'] == name and job['provider'] == provider and job['state'] == 'pending' for job in self.jobs.values()):
                        raise AccountError('login-busy')
                    with account_transaction(self.policy):
                        orchestrate.remove_account(self.policy, provider, name, False)
                    self.identities.pop((provider, name), None)
                    if request.get('deleteData') is True:
                        folder = orchestrate.accounts_root(self.policy) / provider
                        for home in folder.glob(f'{name}.*') if folder.exists() else []:
                            try:
                                self._owned_delete(home, provider, name)
                            except AccountError:
                                continue
                else:
                    raise AccountError('invalid-action')
            return self.snapshot()
        except AccountError as error:
            return {'ok': False, 'error': str(error)}
        except (OSError, ValueError, TypeError, orchestrate.PlanError, subprocess.SubprocessError):
            return {'ok': False, 'error': 'account-update-failed'}

    def close(self):
        with self.lock:
            jobs = list(self.jobs.values())
            for job in jobs:
                job['cancel'].set()
        for job in jobs:
            job['thread'].join(timeout=8)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', type=Path, required=True)
    args = parser.parse_args()
    manager = AccountManager(args.policy)
    output_lock = threading.Lock()
    def respond(request):
        result = manager.action(request.get('request'))
        with output_lock:
            print(json.dumps({'id': request.get('id'), 'result': result}, ensure_ascii=False), flush=True)
    try:
        for line in sys.stdin.buffer:
            try:
                request = json.loads(line) if len(line) <= 65536 else {}
                if not isinstance(request, dict):
                    raise ValueError('invalid request')
                threading.Thread(target=respond, args=(request,), daemon=True).start()
            except (ValueError, AttributeError):
                print(json.dumps({'result': {'ok': False, 'error': 'invalid-request'}}), flush=True)
    finally:
        manager.close()
