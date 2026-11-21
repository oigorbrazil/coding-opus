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
from chat_memory import ChatMemory, capture_hook, project_key
from chat_memory_import import import_chats
from chat_memory_setup import install
from knowledge_library import KnowledgeLibrary, conversation, conversation_index


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

    def test_memory_finds_existing_codex_chat_by_its_renamed_title(self):
        source_id = "3661e897-b38d-49b0-aad0-1e62378035fd"
        session = self.memory.save("codex", source_id, "/project", [], title="Título salvo")
        index = self.root / "session_index.jsonl"
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            self.assertEqual(conversation(self.memory, session, 0)["title"], "Título salvo")
            index.write_text(
                "\n".join(json.dumps({"id": source_id, "thread_name": name})
                          for name in ("Primeiro nome", "Revisão do editor")) + "\n{\"id\":",
                encoding="utf-8",
            )
            result = conversation_index(self.memory, "", "Revisão do editor", 0)
            self.assertEqual(result["total"], 1)
            self.assertEqual([(row["id"], row["title"]) for row in result["entries"]],
                             [(session, "Revisão do editor")])
            self.assertEqual(conversation(self.memory, session, 0)["title"], "Revisão do editor")

    def test_claude_custom_title_wins_over_generated_title(self):
        source_id = "85bfc810-4152-4dca-9454-9b159aded283"
        bucket = self.root / "projects" / "C--Users-Ana-Maria-Editor"
        bucket.mkdir(parents=True)
        transcript = bucket / f"{source_id}.jsonl"
        records = [
            {"type": "custom-title", "sessionId": source_id, "customTitle": "Ajustes no Opus"},
            {"type": "ai-title", "sessionId": source_id, "aiTitle": "Nome automático"},
            {"type": "custom-title", "sessionId": "other-session", "customTitle": "Outro chat"},
        ]
        transcript.write_text("\n".join(map(json.dumps, records)), encoding="utf-8")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root)}):
            session = self.memory.save("claude", source_id, "C:\\Users\\Ana Maria\\Editor", [])
            result = self.memory.search("Ajustes no Opus")
            self.assertEqual([(row["id"], row["title"]) for row in result], [(session, "Ajustes no Opus")])
            self.assertEqual(self.memory.read(session)["title"], "Ajustes no Opus")

    def test_memory_finds_claude_title_when_chat_was_resumed_in_another_folder(self):
        source_id = "6aa44c7a-8d1c-4541-a623-7c7bb9d4087a"
        bucket = self.root / "projects" / "C--Users-Ana-Editor"
        bucket.mkdir(parents=True)
        (bucket / f"{source_id}.jsonl").write_text(json.dumps({
            "type": "custom-title", "sessionId": source_id, "customTitle": "Sincronização dos chats"
        }), encoding="utf-8")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root)}):
            session = self.memory.save("claude", source_id, "C:\\Users\\Ana\\Outro projeto", [],
                                       title="Sim, 1 e 2")
            result = conversation_index(self.memory, "", "Sincronização dos chats", 0)
            self.assertEqual([(row["id"], row["title"]) for row in result["entries"]],
                             [(session, "Sincronização dos chats")])
            self.assertEqual(conversation(self.memory, session, 0)["title"], "Sincronização dos chats")

    def test_library_groups_chat_by_origin_and_preserves_message_folders(self):
        early = {"id": "first", "role": "user", "content": "Primeiro pedido"}
        later = {"id": "later", "role": "assistant", "content": "Retomei o projeto"}
        original = self.memory.save("claude", "one-thread", "/repo", [early], title="Mesmo chat")
        resumed = self.memory.save("claude", "one-thread", "/repo/src", [early, later])
        other = self.memory.save("codex", "one-thread", "/repo", [], title="Outro provedor")
        result = conversation_index(self.memory, "", "", 0)
        self.assertEqual(result["count"], 2)
        self.assertEqual({row["id"] for row in result["entries"]}, {original, other})
        self.assertEqual([row["id"] for row in conversation_index(
            self.memory, project_key("/repo/src"), "Retomei", 0)["entries"]], [original])
        detail = conversation(self.memory, resumed, 0)
        self.assertEqual((detail["id"], detail["count"]), (original, 2))
        self.assertEqual([(row["content"], row["project"]) for row in detail["messages"]],
                         [("Primeiro pedido", "/repo"), ("Retomei o projeto", "/repo/src")])

    def test_rename_applies_to_the_chat_and_can_restore_the_updated_native_title(self):
        source_id = "fad6f65b-5244-4bdf-b36b-0f4fa2d731e9"
        first = self.memory.save("codex", source_id, "/repo", [], title="Nome capturado")
        other_folder = self.memory.save("codex", source_id, "/repo/editor", [])
        index = self.root / "session_index.jsonl"
        index.write_text(json.dumps({"id": source_id, "thread_name": "Nome no Codex"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root)}), \
                mock.patch.object(brain, "brain_path", return_value=self.root):
            library = KnowledgeLibrary()
            result = library.action({"kind": "memory", "action": "rename", "id": other_folder,
                                     "title": "  Nome só na Memória  "})
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["value"]["id"], first)
            self.assertEqual(result["value"]["customTitle"], "Nome só na Memória")
            self.assertEqual(self.memory.read(other_folder)["title"], "Nome só na Memória")
            for query in ("Nome no Codex", "Nome só na Memória"):
                rows = conversation_index(self.memory, "", query, 0)["entries"]
                self.assertEqual([(row["id"], row["title"]) for row in rows], [(first, "Nome só na Memória")])
            index.write_text(json.dumps({"id": source_id, "thread_name": "Renomeado no Codex"}), encoding="utf-8")
            self.assertEqual(conversation(self.memory, first, 0)["title"], "Nome só na Memória")
            invalid = library.action({"kind": "memory", "action": "rename", "id": first, "title": "  "})
            self.assertFalse(invalid["ok"])
            restored = library.action({"kind": "memory", "action": "rename", "id": first, "title": None})
            self.assertTrue(restored["ok"], restored)
            self.assertEqual(restored["value"]["title"], "Renomeado no Codex")
            self.assertIsNone(restored["value"]["customTitle"])

    def test_delete_removes_only_the_confirmed_conversation_group(self):
        message = {"id": "turn-1", "role": "user", "content": "Mensagem local"}
        first = self.memory.save("codex", "to-delete", "/repo", [message], title="Excluir só no Opus")
        alias = self.memory.save("codex", "to-delete", "/repo/editor", [message])
        child = self.memory.save("claude", "related", "/repo", [], title="Conversa que fica")
        self.memory.checkpoint(child, "Resumo da continuação", "", parent=first)
        self.memory.checkpoint(first, "Resumo original", "")
        self.memory.rename(alias, "Nome na memória")
        native = self.root / "native-history.jsonl"
        native.write_text("Cópia do cliente", encoding="utf-8")
        kept = self.memory.root / "sessions" / first / "nota-pessoal.md"
        kept.write_text("Arquivo avulso", encoding="utf-8")
        with mock.patch.object(brain, "brain_path", return_value=self.root):
            library = KnowledgeLibrary()
            request = {"kind": "memory", "action": "delete", "id": alias}
            self.assertFalse(library.action(request)["ok"])
            self.assertEqual(conversation_index(self.memory, "", "", 0)["count"], 2)
            self.assertTrue(library.action({**request, "confirm": True})["ok"])
            self.assertTrue(library.action({**request, "confirm": True})["ok"])
        self.assertEqual([row["id"] for row in conversation_index(self.memory, "", "", 0)["entries"]], [child])
        self.assertEqual(conversation(self.memory, child, 0)["previous"], [])
        for identity in (first, alias):
            for name in ("context.md", "transcript.md"):
                self.assertFalse((self.memory.root / "sessions" / identity / name).exists())
        self.assertTrue(kept.is_file())
        self.assertEqual(native.read_text(encoding="utf-8"), "Cópia do cliente")
        with self.memory.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM checkpoints").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM conversation_titles").fetchone()[0], 0)

    def test_failed_delete_restores_markdown(self):
        identity = self.memory.save("codex", "to-keep", "/repo", [], title="Conversa")
        context = self.memory.root / "sessions" / identity / "context.md"
        before = context.read_bytes()
        with self.memory.connect() as db:
            db.execute("""CREATE TRIGGER simulate_write_failure BEFORE DELETE ON sessions
                BEGIN SELECT RAISE(ABORT,'Test transaction failure'); END""")
        with mock.patch.object(brain, "brain_path", return_value=self.root):
            result = KnowledgeLibrary().action({"kind": "memory", "action": "delete",
                                               "id": identity, "confirm": True})
        self.assertFalse(result["ok"])
        self.assertEqual(context.read_bytes(), before)
        self.assertEqual(self.memory.read(identity)["title"], "Conversa")

    def test_checkpoint_is_versioned_and_interruption_preserves_it(self):
        self.memory.save("codex", "chat-1", "/project",
                         [{"id": "turn-1", "role": "user", "content": "Corrigir filtros"}])
        session = self.memory.search()[0]["id"]
        self.memory.checkpoint(session, "Filtro corrigido", "Revisar filtros",
                               details={"checks": "Teste de filtro passou"})
        self.memory.checkpoint(session, "Filtro revisado", "Testar no editor",
                               details={"objective": "Corrigir filtros", "attempts": "Reprodução manual"})
        self.assertFalse(conversation(self.memory, session, 0)["checkpointStale"])
        capture_hook(self.memory, "codex", self.event("UserPromptSubmit", turn_id="turn-2",
                                                     prompt="Confira os nomes no editor"))
        capture_hook(self.memory, "codex", self.event("Interrupt", turn_id="turn-2"))
        detail = conversation(self.memory, session, 0)
        self.assertTrue(detail["checkpointStale"])
        self.assertEqual((detail["state"], detail["summary"], detail["next_step"]),
                         ("interrompido", "Filtro revisado", "Testar no editor"))
        self.assertEqual(detail["checkpointHistory"][0]["details"], {"checks": "Teste de filtro passou"})
        self.assertEqual(detail["checkpoint"]["details"]["objective"], "Corrigir filtros")
        with self.assertRaisesRegex(brain.BrainError, "Há mensagens novas"):
            self.memory.checkpoint(session, "Revisão de uma versão antiga", "",
                                   expected_position=detail["checkpoint"]["through_position"])

    def test_pasted_continuation_links_chats_without_creating_cycles(self):
        origin = self.memory.save("claude", "origin", "/repo", [], title="Trabalho no Claude")
        capture_hook(self.memory, "codex", self.event("UserPromptSubmit",
                     prompt=f"Coding Opus continuation: {origin}\n\nConfira os testes"))
        child = conversation_index(self.memory, project_key("/project"), "", 0)["entries"][0]["id"]
        self.assertEqual(conversation(self.memory, child, 0)["previous"],
                         [{"id": origin, "title": "Trabalho no Claude", "agent": "claude"}])
        followup = conversation(self.memory, origin, 0)["continuations"]
        self.assertEqual([item["id"] for item in followup], [child])
        self.assertEqual(followup[0]["title"], "Confira os testes")
        with self.assertRaisesRegex(brain.BrainError, "anterior inválida"):
            self.memory.checkpoint(origin, "Resumo", "Passo", parent=child)

    def test_saved_decision_links_to_source_conversation(self):
        (self.root / "00-Inbox").mkdir()
        origin = self.memory.save("claude", "one-thread", "/repo", [], title="Revisão do editor")
        with mock.patch.object(brain, "brain_path", return_value=self.root):
            library = KnowledgeLibrary()
            result = library.action({
                "kind": "notes", "action": "record", "type": "decisao", "group": "00-Inbox",
                "title": "Decisão sobre o editor", "text": "Manter o motor local por portabilidade.",
                "sourceConversation": origin,
            })
            self.assertTrue(result["ok"], result)
            note = library.action({"kind": "notes", "action": "read", "id": result["value"]["id"]})
            self.assertEqual(note["value"]["sourceConversation"], origin)
        body = (self.root / result["value"]["id"]).read_text(encoding="utf-8")
        self.assertIn(f"[[memory/sessions/{origin}/context|Conversa de origem]]", body)

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
