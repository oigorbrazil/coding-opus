import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/coding/scripts" if (ROOT / "skills/coding/scripts").is_dir() else ROOT / "coding/scripts"
sys.path.insert(0, str(SCRIPTS))
from chat_memory import ChatMemory
from remote_control import handler, rpc
from remote_jobs import RemoteError, RemoteJobs


class RemoteTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        project = self.root / "project"
        project.mkdir()
        brain = self.root / "brain"
        brain.mkdir()
        ChatMemory(str(brain)).enable()
        self.config = {"state_dir": str(self.root / "state"), "projects": {"project": str(project.resolve())},
                       "token": "test-token-" + "a" * 32, "origins": ["https://private.example"], "brain": str(brain),
                       "allow_write": False}
        self.launches = []

        def launch(folder, task_id):
            self.launches.append(task_id)
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("fake_remote_runner.py")), str(folder)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.addCleanup(lambda: process.wait(timeout=10))
            return process
        self.jobs = RemoteJobs(self.config, launch=launch)

    def finished(self, task_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = self.jobs.get_task(task_id)
            if task["state"] not in ("starting", "running", "stopping"):
                return task
            time.sleep(.02)
        self.fail("Fake task did not finish")

    def test_real_process_lifecycle_retry_resume_and_memory(self):
        task = self.jobs.start("project", "codex", "Find the issue", "request-1")
        retry = self.jobs.start("project", "codex", "Find the issue", "request-1")
        self.assertEqual(retry["id"], task["id"])
        self.assertEqual(len(self.launches), 1)
        done = self.finished(task["id"])
        self.assertEqual(done["state"], "succeeded")
        self.assertIn("ação concluída", done["result"])
        followup = self.jobs.send(task["session_id"], "Continue", "request-2")
        plan = json.loads((self.jobs.task_folder(followup["id"]) / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["workers"][0]["resume"], "fake-native")
        self.finished(followup["id"])
        sessions = self.jobs.list_sessions()
        self.assertEqual(len(sessions), 1)
        memory = ChatMemory(self.config["brain"])
        self.assertEqual(len(memory.read(sessions[0]["memory_id"])["messages"]), 4)

    def test_explicit_agent_transfer_and_project_boundary(self):
        first = self.jobs.start("project", "claude", "Review", "first")
        self.finished(first["id"])
        transferred = self.jobs.continue_with(first["session_id"], "codex", "Finish", "transfer")
        plan = json.loads((self.jobs.task_folder(transferred["id"]) / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["workers"][0]["provider"], "codex")
        self.assertNotIn("resume", plan["workers"][0])
        self.assertIn("Review", plan["workers"][0]["task"])
        self.finished(transferred["id"])
        with self.assertRaises(RemoteError):
            self.jobs.start("../other", "claude", "No", "unsafe")
        with self.assertRaises(RemoteError):
            self.jobs.start("project", "claude", "No", "write", mode="write")

    def test_busy_project_refuses_overlap_and_stop_interrupts(self):
        task = self.jobs.start("project", "codex", "wait for stop", "slow")
        with self.assertRaises(RemoteError):
            self.jobs.start("project", "claude", "Overlap", "overlap")
        self.jobs.stop(task["id"])
        done = self.finished(task["id"])
        self.assertIn(done["state"], ("stopped", "interrupted"))

    def test_controller_restart_recovers_saved_session(self):
        task = self.jobs.start("project", "claude", "One", "one")
        self.finished(task["id"])
        replacement = RemoteJobs(self.config)
        self.assertEqual(replacement.get_task(task["id"])["state"], "succeeded")
        self.assertEqual(replacement.list_sessions()[0]["native_id"], "fake-native")

    def test_request_id_cannot_change_its_operation(self):
        task = self.jobs.start("project", "claude", "One", "one")
        self.finished(task["id"])
        with self.assertRaises(RemoteError):
            self.jobs.start("project", "claude", "Different", "one")
        self.assertEqual(len(self.launches), 1)

    def test_private_remote_request_does_not_enter_shared_memory(self):
        task = self.jobs.start("project", "codex", "não registre este pedido privado", "private")
        self.finished(task["id"])
        self.assertEqual(ChatMemory(self.config["brain"]).search(), [])

    def test_disabled_memory_is_not_backfilled_after_reenabling(self):
        memory = ChatMemory(self.config["brain"])
        (memory.root / "config.json").write_text('{"enabled":false}', encoding="utf-8")
        task = self.jobs.start("project", "codex", "Private while disabled", "disabled")
        self.finished(task["id"])
        memory.enable()
        self.jobs.list_sessions()
        self.assertEqual(memory.search(), [])

    def test_server_shutdown_keeps_running_tasks_available(self):
        task = self.jobs.start("project", "codex", "wait until explicitly stopped", "running")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.jobs, self.config))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/_stop", data=b"{}",
                                         headers={"Authorization": "Bearer " + self.config["token"]})
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertTrue(json.load(response)["stopped"])
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.jobs.get_task(task["id"])["state"], "running")
        self.jobs.stop(task["id"])
        self.assertIn(self.finished(task["id"])["state"], ("stopped", "interrupted"))

    def test_transport_auth_origin_protocol_and_tool_errors(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.jobs, self.config))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/mcp"
        def request(body, token=None, origin=None):
            headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
            if token:
                headers["Authorization"] = "Bearer " + token
            if origin:
                headers["Origin"] = origin
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
            return urllib.request.urlopen(req, timeout=5)
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}
        with self.assertRaises(urllib.error.HTTPError) as error:
            request(initialize)
        self.assertEqual(error.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError) as error:
            request(initialize, self.config["token"], "https://untrusted.example")
        self.assertEqual(error.exception.code, 403)
        with request(initialize, self.config["token"]) as response:
            self.assertEqual(json.load(response)["result"]["serverInfo"]["name"], "coding-opus-remote")
        with request({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.config["token"]) as response:
            self.assertEqual(response.status, 202)
        with request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "projects"}}, self.config["token"]) as response:
            self.assertEqual(json.load(response)["result"]["structuredContent"]["result"][0]["id"], "project")
        bad = rpc(self.jobs, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "start_agent", "arguments": {"project": "outside"}}})
        self.assertTrue(bad["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
