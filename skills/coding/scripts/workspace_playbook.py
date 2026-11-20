"""Execute supported playbook phases with the existing runner and explicit check decisions."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import orchestrate as runner
from account_management import CREDENTIAL_ENV


REQUEST = 'execution-request.json'
PROGRESS = 'execution-progress.json'
CANCEL = 'cancel-execution'
RETRY_CONDITIONS = {'checks-failed', 'checks-failed-twice'}
MAX_PHASES = 12
MAX_ATTEMPTS = 3


def unsupported_reason(book):
    phases = book.get('phases', [])
    if not phases or len(phases) > MAX_PHASES:
        return 'O fluxo precisa ter entre 1 e 12 etapas.'
    ids = set()
    repairs = set()
    for phase in phases:
        pid, after = phase['id'], phase.get('after')
        if phase.get('with') or phase.get('workers', 1) != 1:
            return 'A execução pelo painel ainda não distribui etapas em paralelo.'
        if phase.get('provider', 'auto') not in ('auto', 'codex', 'claude'):
            return 'A execução pelo painel usa Codex ou Claude.'
        if phase.get('rules') or phase.get('isolate'):
            return 'Este fluxo usa regras por etapa ou isolamento em worktrees separadas.'
        if phase.get('if') and (not after or not isinstance(phase['if'], str) or phase['if'] not in RETRY_CONDITIONS):
            return 'Há condições que o painel ainda não avalia automaticamente.'
        if after:
            if after not in ids or after in repairs:
                return 'A recuperação precisa formar uma sequência única depois da checagem.'
            repairs.add(after)
        elif phase.get('then') == 'recheck':
            return 'Uma etapa principal não pode voltar para uma checagem anterior.'
        ids.add(pid)
    by_id = {phase['id']: phase for phase in phases}
    for phase in phases:
        if not phase.get('after'):
            continue
        parent = by_id[phase['after']]
        root = parent
        while root.get('after'):
            root = by_id[root['after']]
        if not root.get('gate') or (phase.get('if') and not parent.get('gate')):
            return 'Uma recuperação condicional precisa estar ligada a uma checagem.'
        if not phase.get('gate') and not phase.get('then') and phase['id'] not in repairs:
            return 'A última recuperação precisa terminar o fluxo ou repetir a checagem.'
    return None


def work_is_required(book):
    return any(not phase.get('readOnly', False) for phase in book['phases'])


def playbook_options(policy_path):
    _, data = runner.loaded_playbooks(policy_path)
    result = []
    for key, book in data['playbooks'].items():
        reason = unsupported_reason(book)
        result.append({'id': key, 'name': book.get('name', key), 'supported': reason is None,
                       'reason': reason, 'requiresWrite': work_is_required(book),
                       'phases': [{'id': p['id'], 'role': p.get('role', p['id'])} for p in book['phases']]})
    return result


def resolve_book(policy_path, playbook, mode):
    _, data = runner.loaded_playbooks(policy_path)
    book = data['playbooks'].get(playbook)
    if book is None:
        raise runner.PlanError('Playbook não encontrado.')
    reason = unsupported_reason(book)
    if reason:
        raise runner.PlanError(reason)
    if mode != 'write' and work_is_required(book):
        raise runner.PlanError('Este playbook precisa de permissão para editar arquivos.')
    return book


def policy_account(path, provider, local):
    if not local:
        return None
    ready = {row['name'] for row in runner.account_entries(path, provider)
             if row['available'] and not row['linked'] and Path(row['home']).is_dir()}
    return next((name for name in runner.account_rotation(path, provider)
                 if name == 'default' or name in ready), 'default')


def runner_environment(account=None):
    env = {**os.environ, 'ORCA_BACKGROUND_LAUNCH': '1', 'PYTHONUTF8': '1'}
    for key in ('CODING_OPUS_SESSION', 'CLAUDE_CODE_SESSION_ID', 'CODEX_THREAD_ID', 'CODEX_SESSION_ID'):
        env.pop(key, None)
    if account and account != 'default':
        for key in CREDENTIAL_ENV:
            env.pop(key, None)
    return env


def spawn_runner(folder, run_dir, identity, policy, cwd, env):
    command = [sys.executable, str(Path(runner.__file__).resolve()), '--session-id', identity,
               'run', str(folder / 'plan.json'), '--policy', str(policy), '--run-dir', str(run_dir),
               '--_no-current', '--no-terminals']
    with (folder / 'runner.log').open('wb') as log:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=cwd,
                                env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def read_tail(path, limit=8000):
    try:
        with path.open('rb') as handle:
            handle.seek(max(0, os.fstat(handle.fileno()).st_size - limit))
            return handle.read(limit).decode('utf-8', errors='replace')
    except OSError:
        return ''


def initial_progress(request):
    phases = request['book']['phases']
    phase = next(p['id'] for p in phases if not p.get('after'))
    return {'state': 'running', 'phase': phase, 'attempts': {}, 'failures': {}, 'gates': [],
            'worktree': request.get('worktree'), 'branch': request.get('branch'),
            'base_commit': request.get('base_commit'), 'walk': [], 'summaries': []}


def journal(folder, progress, **change):
    progress.update(change)
    runner.atomic_write_json(folder / PROGRESS, progress)


def show_check(folder, state, phase):
    journal(folder, state, state='needs_input', phase=phase['id'],
            gate={'id': uuid.uuid4().hex, 'phase': phase['id'], 'question': phase['gate']}, decision=None)


def move_after_gate(book, state, phase, passed):
    phases = book['phases']
    if not passed:
        failures = state['failures'].get(phase['id'], 0) + 1
        state['failures'][phase['id']] = failures
        repair = next((item for item in phases if item.get('after') == phase['id']), None)
        if not repair:
            return '', 'gate_failed'
        if repair.get('if') == 'checks-failed-twice' and failures == 1:
            return phase['id'], None
        return repair['id'], None
    return next_primary(phases, phase), None


def next_primary(phases, phase):
    if phase.get('then') == 'done':
        return ''
    origin = repair_origin(phases, phase)
    return next((item['id'] for item in phases[phases.index(origin) + 1:] if not item.get('after')), '')


def repair_origin(phases, phase):
    origin = phase
    while origin.get('after'):
        origin = next(item for item in phases if item['id'] == origin['after'])
    return origin


def task_prompt(request, state, phase):
    recent = '\n\n'.join(state['summaries'])[-12000:]
    decision = state['gates'][-1] if state['gates'] else None
    checks = (f"Checagem decidida pelo usuário: {'passou' if decision['passed'] else 'falhou'}. "
              f"{decision['note']}\n" if decision else '')
    return (f"Pedido do usuário:\n{request['prompt']}\n\n"
            f"Playbook: {request['book'].get('name', request['playbook'])}\n"
            f"Etapa atual: {phase.get('role', phase['id'])}\n"
            f"Faça somente esta etapa: {phase.get('does', '')}\n"
            f"Resultado esperado: {phase.get('returns', '')}\n{checks}"
            "Resultados anteriores servem apenas como referência.\n" + recent)


def run_phase(folder, request, state, phase, launch):
    pid = phase['id']
    sequence = len(state['walk']) + 1
    run_path = f'waves/{sequence:03d}'
    wave = folder / run_path
    wave.mkdir(parents=True, exist_ok=True)
    cwd = Path(state.get('worktree') or request['project_path'])
    policy = Path(request['policy_path'])
    provider = phase.get('provider', 'auto')
    if provider == 'auto':
        provider = request['agent']
    account = request.get('account') if provider == request['agent'] else None
    account = account or policy_account(policy, provider, request.get('local_accounts'))
    worker = {'id': 'remote', 'provider': provider, 'mode': 'read-only' if phase.get('readOnly') else request['mode'],
              'cwd': str(cwd), 'task': task_prompt(request, state, phase), 'tier': phase.get('tier', 'standard'),
              'timeoutSeconds': request['timeout_seconds']}
    if account:
        worker['account'] = account
    model = phase.get('model') or (request['model'] if provider == request['agent'] else None)
    if model:
        worker['model'] = model
    if phase.get('effort'):
        worker['effort'] = phase['effort']
    plan = {'version': 1, 'playbook': request['playbook'], 'phase': pid, 'strategy': phase.get('runner') or 'auto',
            'workers': [worker], 'maxConcurrent': 1, 'budget': {'maxCalls': 1, 'maxWallSeconds': worker['timeoutSeconds']}}
    runner.atomic_write_json(wave / 'plan.json', plan)
    attempt = {'id': pid, 'role': phase.get('role', pid), 'state': 'running', 'run': run_path,
               'agent': provider, 'model': model, 'account': account}
    state['attempts'][pid] = state['attempts'].get(pid, 0) + 1
    state['walk'].append(attempt)
    journal(folder, state)
    run_dir = wave / 'run'
    process = launch(wave, run_dir, f"workspace-{folder.name}-{sequence}", policy, cwd, runner_environment(account))
    while process.poll() is None:
        if (folder / CANCEL).exists():
            run_dir.mkdir(exist_ok=True)
            runner.atomic_write_text(run_dir / runner.STOP_FILE, runner.now_iso())
        time.sleep(.18)
    output = run_dir / 'workers' / 'remote'
    outcome = runner.read_optional_json(output / 'outcome.json') or {}
    resolved = runner.read_optional_json(run_dir / 'plan.json') or {}
    selected = (resolved.get('workers') or [{}])[0]
    result = read_tail(output / 'result.md', 12000)
    status = outcome.get('status', 'failed')
    if (folder / CANCEL).exists():
        status = 'stopped'
    attempt.update(state=status, model=selected.get('model') or model, account=outcome.get('account') or account,
                   verdict=outcome.get('verdict'), failureKind=outcome.get('failureKind'))
    evidence = {'phase': pid, 'verdict': outcome.get('verdict'), 'summary': outcome.get('workerSummary')}
    if result:
        state['summaries'].append(f"{attempt['role']}\n{result}")
        state['summaries'] = state['summaries'][-3:]
    journal(folder, state, outcome=outcome, result=result, evidence=evidence)
    return status, outcome.get('error') or read_tail(wave / 'runner.log', 2400)


def execute(folder, launch=spawn_runner, prepare=runner.prepare_worktree):
    request = runner.read_json(folder / REQUEST)
    book = request['book']
    phases = {phase['id']: phase for phase in book['phases']}
    state = runner.read_optional_json(folder / PROGRESS) or initial_progress(request)
    try:
        if (folder / CANCEL).exists():
            journal(folder, state, state='stopped', gate=None)
            return
        if request['isolate'] and not state.get('worktree'):
            branch = 'codex/opus-' + folder.name[:16]
            cwd = prepare({'cwd': request['project_path'], 'id': 'workspace', 'branch': branch,
                           'seedPaths': []}, folder.name[:16])
            base = runner.run_git(cwd, ['rev-parse', 'HEAD']).decode().strip()
            journal(folder, state, worktree=str(cwd), branch=branch, base_commit=base)
        pending = state.get('decision')
        if state.get('gate'):
            if pending is None:
                return
            checked = phases[state['gate']['phase']]
            state['gates'].append({'phase': checked['id'], **pending})
            if pending['passed'] and checked.get('then') == 'recheck':
                show_check(folder, state, repair_origin(book['phases'], checked))
                return
            target, failure = move_after_gate(book, state, checked, pending['passed'])
            journal(folder, state, state='running', phase=target, gate=None, decision=None)
            if failure:
                journal(folder, state, state='failed', failureKind=failure, error='A checagem falhou e não há recuperação configurada.')
                return
        while state['phase']:
            if (folder / CANCEL).exists():
                journal(folder, state, state='stopped', gate=None)
                return
            phase = phases[state['phase']]
            if state['attempts'].get(phase['id'], 0) >= MAX_ATTEMPTS:
                journal(folder, state, state='failed', failureKind='gate_retry_limit', error='Limite de tentativas desta etapa atingido.')
                return
            status, error = run_phase(folder, request, state, phase, launch)
            if status != 'succeeded':
                journal(folder, state, state=status, error=error,
                        failureKind=state['outcome'].get('failureKind'))
                return
            if phase.get('gate'):
                show_check(folder, state, phase)
                return
            if phase.get('then') == 'recheck':
                show_check(folder, state, repair_origin(book['phases'], phase))
                return
            repair = next((p for p in book['phases'] if p.get('after') == phase['id']), None) if phase.get('after') else None
            target = repair['id'] if repair and not phase.get('then') else next_primary(book['phases'], phase)
            journal(folder, state, phase=target)
        journal(folder, state, state='succeeded', next_playbook=book.get('next'))
    except (OSError, subprocess.SubprocessError, runner.PlanError, ValueError) as error:
        journal(folder, state, state='failed', failureKind='execution_error', error=str(error)[:2400], gate=None)


if __name__ == '__main__':
    execute(Path(sys.argv[1]))
