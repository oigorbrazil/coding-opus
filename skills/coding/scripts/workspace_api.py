"""Local editor operations over the same task store as the remote panel."""

from pathlib import Path
import re
import sqlite3
import threading

import orchestrate as runner
from chat_memory import BrainError, ChatMemory, project_key
from remote_jobs import RemoteError, RemoteJobs
from workspace_playbook import playbook_options
from workspace_projects import WorkspaceProjectError, WorkspaceProjects


ACTIVE = {"starting", "running", "stopping", "needs_input"}


class WorkspaceApi:
    def __init__(self, policy, jobs=None, projects=None, brain=None):
        self.policy = policy
        self.projects = projects or WorkspaceProjects(policy)
        self.lock = threading.RLock()
        self.jobs = jobs
        self.brain = brain

    def _refresh_projects(self):
        projects = self.projects.list()
        allowed = {row["id"]: row["path"] for row in projects if row["available"]}
        if self.jobs is None:
            self.jobs = RemoteJobs({
                "projects": allowed, "state_dir": str(self.policy.parent / "remote-control"),
                "policy_path": str(self.policy), "allow_write": True, "local_accounts": True,
            })
        else:
            self.jobs.config["projects"] = allowed
        return projects

    def _state(self, projects):
        accounts = runner.accounts_summary(self.policy)["providers"]
        settings = runner.playbook_settings(self.policy)
        providers = {}
        for provider in ("codex", "claude"):
            models = []
            for value in settings.get("models", {}).get(provider, []):
                value = value.get("id") if isinstance(value, dict) else value
                if isinstance(value, str):
                    models.append(value)
            for tier in settings["tiers"].values():
                model = tier.get(provider, {}).get("model")
                if isinstance(model, str):
                    models.append(model)
            providers[provider] = {"models": list(dict.fromkeys(models)), "accounts": [
                {"name": account["name"], "email": account.get("email"), "source": account["from"],
                 "ready": account["ready"]}
                for account in accounts[provider] if account["from"] != "coding-agent"
            ]}
        return {"projects": projects, "sessions": self.jobs.list_sessions(),
                "playbooks": playbook_options(self.policy), "providers": providers,
                "remoteConfigured": (self.policy.parent / "remote-control/config.json").is_file()}

    def _checkout(self, task):
        root = self.projects.resolve(task["project"])
        path = Path(task["worktree"]).resolve() if task.get("worktree") else root
        # A worker result cannot authorize a new directory for Git or review.
        if not path.is_dir():
            raise WorkspaceProjectError("A pasta da execução não está disponível.")
        if path != root:
            git_root = runner.checkout_root(root)
            if not git_root or not runner.is_inside(path, git_root / ".coding-opus/worktrees"):
                raise WorkspaceProjectError("A pasta da execução está fora do projeto autorizado.")
            if runner.linked_path(path) or runner.checkout_root(path) != path:
                raise WorkspaceProjectError("A worktree da execução não está disponível.")
        base = task.get("base_commit") if path != root else None
        if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40,64}", base):
            base = None
        return path, base

    def _diff(self, task):
        path, base = self._checkout(task)
        return self.projects.diff(path, base=base) if base else self.projects.diff(path)

    def _memory(self, project):
        path = str(self.projects.resolve(project))
        memory = ChatMemory(self.brain)
        if not memory.enabled():
            return None, path
        return memory, path

    def _memory_entry(self, project, id):
        memory, path = self._memory(project)
        row = memory.read(id, limit=6) if memory else None
        if not row or project_key(row["project"]) != project_key(path):
            raise WorkspaceProjectError("Conversa indisponível para este projeto.")
        row["messages"] = [{"role": item["role"], "content": item["content"][:4000],
                            "timestamp": item["timestamp"]} for item in row["messages"]]
        return row

    def _dispatch(self, request):
        action = request["action"]
        with self.lock:
            projects = self._refresh_projects()
            if action == "state":
                return self._state(projects)
            if action == "add-project":
                return self.projects.add(request["path"], request.get("name"))
            if action == "task":
                task = self.jobs.get_task(request["id"])
                return {"task": task, "history": self.jobs.list_tasks(task["session_id"])}
            if action == "start":
                prompt = request["prompt"]
                if request.get("memory"):
                    row = self._memory_entry(request["project"], request["memory"])
                    context = "\n\nContexto selecionado pelo usuário, somente referência\n"
                    summary = (row.get("summary") or "")[:8000]
                    context += summary or "\n\n".join(
                        f"{message['role']}\n{message['content'][:1400]}" for message in row["messages"][-3:]
                    )
                    if row.get("next_step"):
                        context += "\nPróximo passo registrado\n" + row["next_step"][:2000]
                    prompt = prompt + context
                return self.jobs.start(request["project"], request["agent"], prompt, request["requestId"],
                    request.get("mode", "read-only"), request.get("model"), playbook=request.get("playbook"),
                    isolate=request.get("isolate") is True, account=request.get("account"))
            if action == "send":
                return self.jobs.send(request["session"], request["prompt"], request["requestId"])
            if action == "handoff":
                return self.jobs.continue_with(request["session"], request["agent"], request["prompt"], request["requestId"])
            if action == "retry":
                return self.jobs.retry(request["id"], request["requestId"])
            if action == "stop":
                return self.jobs.stop(request["id"])
            if action == "gate":
                if not isinstance(request.get("passed"), bool) or not isinstance(request.get("gateId"), str):
                    raise WorkspaceProjectError("Informe se a checagem passou.")
                return self.jobs.gate(request["id"], request["passed"], request.get("note", ""), request.get("gateId"))
            if action == "memory-list":
                memory, path = self._memory(request["project"])
                return memory.search(str(request.get("query", ""))[:280], project=path, limit=30) if memory else []
            if action == "memory-read":
                row = self._memory_entry(request["project"], request["id"])
                return {key: row[key] for key in ("id", "title", "agent", "summary", "next_step", "messages")}
            if action in ("review", "comment", "remove-comment", "send-review"):
                return self._review(action, request)
        raise WorkspaceProjectError("Ação desconhecida.")

    def _review(self, action, request):
        task = self.jobs.get_task(request["id"])
        if task["state"] in ACTIVE - {"needs_input"}:
            raise WorkspaceProjectError("Aguarde a execução chegar a um ponto de revisão.")
        if action == "review":
            return {**self._diff(task), "comments": self.projects.annotations(task["id"])}
        if action == "comment":
            diff = self._diff(task)
            if not any(request["path"] in (item["path"], item.get("oldPath")) for item in diff.get("files", [])):
                    raise WorkspaceProjectError("O arquivo não está no diff deste checkout.")
            return self.projects.add_annotation(task["id"], request["path"], request["line"],
                request["body"], request.get("side", "new"))
        if action == "remove-comment":
            return self.projects.remove_annotation(task["id"], request["comment"])

        annotations = self.projects.annotations(task["id"])
        if not annotations:
            raise WorkspaceProjectError("Adicione um comentário antes de enviar a revisão.")
        prompt = request["prompt"].strip()
        if not prompt:
            raise WorkspaceProjectError("Informe o que a IA deve fazer com a revisão.")
        prompt += "\n\nComentários selecionados pelo usuário\n" + "\n\n".join(
            f"{item['path']}:{item['line']} ({item['side']})\n{item['body']}" for item in annotations
        )[:14000]
        return self.jobs.continue_with(task["session_id"], request["agent"], prompt, request["requestId"])

    def action(self, request):
        try:
            return {"ok": True, "value": self._dispatch(request)}
        except (WorkspaceProjectError, RemoteError, runner.PlanError, BrainError) as error:
            return {"ok": False, "error": str(error)[:1200]}
        except (ValueError, KeyError, TypeError, AttributeError):
            return {"ok": False, "error": "Verifique os dados enviados."}
        except (OSError, sqlite3.Error):
            return {"ok": False, "error": "A área de trabalho não está disponível. Tente novamente."}
