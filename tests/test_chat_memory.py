import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/coding/scripts" if (ROOT / "skills/coding/scripts").is_dir() else ROOT / "coding/scripts"
sys.path.insert(0, str(SCRIPTS))
import brain
from chat_memory import ChatMemory, capture_hook
from chat_memory_import import import_chats
from chat_memory_setup import install


class ChatMemoryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.memory = ChatMemory(str(self.root))
        self.memory.enable()

    def event(self, name, **values):
        return {"hook_event_name": name, "session_id": "chat-1", "turn_id": "turn-1",
                "cwd": "/project", **values}

    def json_file(self, value):
        path = self.root / "export.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_capture_checkpoint_and_recall_from_another_agent(self):
        capture_hook(self.memory, "claude", self.event("UserPromptSubmit", prompt="Corrija a autenticação"))
        capture_hook(self.memory, "claude", self.event("Stop", last_assistant_message="Alterei login.ts. Falta testar."))
        session_id = self.memory.search(project="/project")[0]["id"]
        self.memory.checkpoint(session_id, "login.ts alterado, teste ainda pendente", "Executar teste de login")
        recalled = self.memory.read(session_id)
        self.assertEqual([m["content"] for m in recalled["messages"]],
                         ["Corrija a autenticação", "Alterei login.ts. Falta testar."])
        self.assertEqual(recalled["next_step"], "Executar teste de login")
        self.assertEqual(recalled["state"], "ativo")
        other = capture_hook(self.memory, "codex", self.event("UserPromptSubmit", prompt="Continue"))
        self.assertNotEqual(session_id, self.memory.search(project="/project")[0]["id"])
        self.assertIn("additionalContext", other["hookSpecificOutput"])
        self.assertIn("teste ainda pendente", Path(recalled["context_file"]).read_text(encoding="utf-8"))

    def test_retries_do_not_duplicate_but_repeated_prompts_are_distinct_turns(self):
        event = self.event("UserPromptSubmit", prompt="Continue")
        capture_hook(self.memory, "codex", event)
        session_id = self.memory.search()[0]["id"]
        self.memory.checkpoint(session_id, "Progresso preservado", "Verificar")
        capture_hook(self.memory, "codex", event)
        self.assertEqual(self.memory.read(session_id)["summary"], "Progresso preservado")
        capture_hook(self.memory, "codex", {**event, "turn_id": "turn-2"})
        self.assertEqual(len(self.memory.read(session_id)["messages"]), 2)
        stop = self.event("Stop", turn_id="turn-2", last_assistant_message="Feito")
        capture_hook(self.memory, "codex", stop)
        capture_hook(self.memory, "codex", stop)
        self.assertEqual(len(self.memory.read(session_id)["messages"]), 3)

    def test_claude_without_turn_id_records_each_transcript_boundary(self):
        transcript = self.root / "session.jsonl"
        transcript.write_text("", encoding="utf-8")
        event = self.event("UserPromptSubmit", prompt="Continue", transcript_path=str(transcript))
        del event["turn_id"]
        capture_hook(self.memory, "claude", event)
        capture_hook(self.memory, "claude", event)
        transcript.write_text('{"type":"assistant"}\n', encoding="utf-8")
        capture_hook(self.memory, "claude", event)
        session_id = self.memory.search()[0]["id"]
        self.assertEqual(len(self.memory.read(session_id)["messages"]), 2)

    def test_project_boundaries_and_interruption(self):
        event = self.event("UserPromptSubmit", prompt="Corrigir")
        capture_hook(self.memory, "claude", event)
        capture_hook(self.memory, "claude", {**event, "cwd": "/other"})
        capture_hook(self.memory, "claude", self.event("Interrupt"))
        self.assertEqual(len(self.memory.search(project="/project")), 1)
        self.assertEqual(self.memory.search(project="/project")[0]["state"], "interrompido")
        self.assertEqual(self.memory.search(project="/other")[0]["state"], "ativo")

    def test_project_search_accepts_windows_path_separators(self):
        capture_hook(self.memory, "codex", self.event("UserPromptSubmit", cwd="C:\\Project\\", prompt="Path check"))
        self.assertEqual(len(self.memory.search(project="C:/Project")), 1)
        self.assertEqual(self.memory.search(project="C:/Different"), [])

    def test_opt_out_omits_both_sides_and_next_public_turn_resumes(self):
        capture_hook(self.memory, "codex", self.event("UserPromptSubmit", prompt="não registre minha senha"))
        capture_hook(self.memory, "codex", self.event("Stop", last_assistant_message="resposta privada"))
        self.assertEqual(self.memory.search("senha"), [])
        self.assertEqual(self.memory.search("privada"), [])
        capture_hook(self.memory, "codex", self.event("UserPromptSubmit", turn_id="2", prompt="pedido público"))
        self.assertEqual(len(self.memory.search("público")), 1)

    def test_disabled_hook_creates_nothing_and_workers_do_not_record(self):
        with mock.patch.dict(os.environ, {"CODING_OPUS_WORKER": "1"}):
            capture_hook(self.memory, "codex", self.event("UserPromptSubmit", prompt="worker"))
        self.assertEqual(self.memory.search(), [])
        (self.memory.root / "config.json").write_text('{"enabled": false}', encoding="utf-8")
        self.assertEqual(capture_hook(self.memory, "claude", self.event("UserPromptSubmit", prompt="private")), {})

    def test_import_claude_preserves_text_and_is_retryable(self):
        path = self.json_file([{"uuid": "export-1", "name": "Meu chat", "chat_messages": [
            {"uuid": "m1", "sender": "human", "text": "Pedido com acentuação", "created_at": "2026-11-15T10:00:00Z"},
            {"uuid": "m2", "sender": "assistant", "content": [{"type": "text", "text": "Resposta"}]}]}])
        imported = import_chats(self.memory, path, "claude", "/app")
        import_chats(self.memory, path, "claude", "/app")
        session = self.memory.read(imported["sessions"][0])
        self.assertEqual(len(session["messages"]), 2)
        self.assertEqual(session["messages"][0]["timestamp"], "2026-11-15T10:00:00Z")
        self.assertEqual(session["project"], "/app")

    def test_chatgpt_active_branch_and_invalid_export_are_handled(self):
        mapping = {"root": {"parent": None, "message": None},
                   "u": {"parent": "root", "message": {"id": "u", "author": {"role": "user"}, "content": {"parts": ["Pedido"]}}},
                   "a": {"parent": "u", "message": {"id": "a", "author": {"role": "assistant"}, "content": {"parts": ["Ativa"]}}},
                   "b": {"parent": "u", "message": {"id": "b", "author": {"role": "assistant"}, "content": {"parts": ["Outra"]}}}}
        chat = {"id": "gpt1", "mapping": mapping, "current_node": "a"}
        result = import_chats(self.memory, self.json_file([chat]), "chatgpt")
        self.assertEqual([m["content"] for m in self.memory.read(result["sessions"][0])["messages"]], ["Pedido", "Ativa"])
        with self.assertRaises(brain.BrainError):
            import_chats(self.memory, self.json_file([chat, {"id": "invalid"}]), "chatgpt")
        self.assertEqual(len(self.memory.search()), 1)

    def test_zip_never_extracts_its_paths(self):
        path = self.root / "export.zip"
        chat = {"id": "generic-1", "agent": "gemini", "messages": [{"id": "1", "role": "user", "content": "Olá"}]}
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../../conversations.json", json.dumps([chat]))
        result = import_chats(self.memory, path, "generic")
        self.assertEqual(result["conversations"], 1)
        self.assertFalse((self.root / "conversations.json").exists())

    def test_installation_preserves_other_hooks_and_rules_and_is_idempotent(self):
        home = self.root / "home"
        claude, codex = home / ".claude", home / ".codex"
        claude.mkdir(parents=True)
        codex.mkdir()
        original = {"theme": "dark", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "existing"}]}]}}
        (claude / "settings.json").write_text(json.dumps(original), encoding="utf-8")
        (codex / "AGENTS.md").write_text("Existing rule\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(claude), "CODEX_HOME": str(codex)}):
            install(self.memory, hooks=True, rules=True)
            install(self.memory, hooks=True, rules=True)
        config = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(config["theme"], "dark")
        self.assertEqual(len(config["hooks"]["Stop"]), 2)
        self.assertEqual(config["hooks"]["Stop"][0], original["hooks"]["Stop"][0])
        self.assertTrue((codex / "AGENTS.md").read_text(encoding="utf-8").startswith("Existing rule\n"))

    def test_concurrent_processes_do_not_lose_requests(self):
        command = [sys.executable, str(SCRIPTS / "chat_memory.py"), "--brain", str(self.root), "request",
                   "--agent", "claude", "--session", "parallel", "--project", "/app"]
        processes = [subprocess.Popen(command + ["--event-id", str(index), "--text", f"Pedido {index}"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for index in range(6)]
        for process in processes:
            output, errors = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, errors.decode())
        session_id = self.memory.search(project="/app")[0]["id"]
        self.assertEqual(len(self.memory.read(session_id)["messages"]), 6)
        transcript = (self.memory.root / "sessions" / session_id / "transcript.md").read_text(encoding="utf-8")
        for index in range(6):
            self.assertIn(f"Pedido {index}", transcript)

    def test_general_note_search_skips_transcripts(self):
        self.memory.save("claude", "1", "", [{"id": "1", "role": "user", "content": "texto bruto"}])
        (self.root / "note.md").write_text("# Curated", encoding="utf-8")
        self.assertEqual([path.name for path in brain.iter_notes(self.root)], ["note.md"])

    @unittest.skipUnless(os.name == "nt", "PowerShell wrapper runs on Windows")
    def test_windows_hook_receives_utf8_stdin(self):
        from chat_memory_setup import hook_command
        powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        process = subprocess.run([powershell, "-NoProfile", "-Command", hook_command(self.memory, "codex")],
                                 input=json.dumps(self.event("UserPromptSubmit", prompt="ação compartilhada"), ensure_ascii=False),
                                 capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("hookSpecificOutput", json.loads(process.stdout))
        self.assertEqual(len(self.memory.search("ação compartilhada")), 1)
        bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if bash.is_file():
            process = subprocess.run([str(bash), "-c", hook_command(self.memory, "claude")],
                                     input=json.dumps(self.event("UserPromptSubmit", prompt="Claude também"), ensure_ascii=False),
                                     capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("hookSpecificOutput", json.loads(process.stdout))
            self.assertEqual(len(self.memory.search("Claude também")), 1)


if __name__ == "__main__":
    unittest.main()
