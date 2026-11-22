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

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/coding/scripts" if (ROOT / "skills/coding/scripts").is_dir() else ROOT / "coding/scripts"
sys.path.insert(0, str(SCRIPTS))
from chat_memory import ChatMemory
from remote_control import (Devices, LocalHTTPServer, Pairing, handler, manage_projects, private_panel_url,
                            remote_status, revoke_device, rpc, set_panel_address, tailscale_info)
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
            # A test that failed before stopping its task must not leave the fake runner waiting.
            self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait(timeout=10)))
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
        server = LocalHTTPServer(("127.0.0.1", 0), handler(self.jobs, self.config))
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
        server = LocalHTTPServer(("127.0.0.1", 0), handler(self.jobs, self.config))
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

    def test_connection_guide_shares_the_address_without_the_key(self):
        origin = "https://test-machine.private-net.ts.net"
        self.config["origins"].append(origin)
        self.assertEqual(private_panel_url(self.config), origin + "/coding-opus/")
        self.config["panel_url"] = origin + "/remote/"
        self.assertEqual(private_panel_url(self.config), origin + "/remote/")
        for suffix in ("?token=secret", "#token=secret"):
            self.assertEqual(private_panel_url({**self.config, "panel_url": origin + suffix}), "")
        server = LocalHTTPServer(("127.0.0.1", 0), handler(self.jobs, self.config))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/", timeout=5) as response:
            html = response.read().decode()
        self.assertIn(f'content="{origin}/remote/"', html)
        self.assertNotIn(self.config["token"], html)
        public = urllib.request.Request(base + "/", headers={"Host": "test-machine.private-net.ts.net"})
        with urllib.request.urlopen(public, timeout=5) as response:
            self.assertNotIn(origin.encode(), response.read())
        with urllib.request.urlopen(base + "/remote-qr.js", timeout=5) as response:
            self.assertIn(b"encodeRemoteQr", response.read())


class PairingTest(unittest.TestCase):
    """Pairing replaces the shared key: single-use codes, one token per device, revocable."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.now = [1000.0]
        self.config = {"state_dir": str(self.home), "projects": {}, "token": "master-" + "m" * 40,
                       "origins": [], "allow_write": False}
        self.devices = Devices(self.home)
        self.pairing = Pairing(clock=lambda: self.now[0])
        server = LocalHTTPServer(("127.0.0.1", 0), handler(None, self.config, self.devices, self.pairing))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"

    def call(self, method, path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            raw = error.read()
            return error.code, json.loads(raw) if raw.strip() else {}

    def pair(self, kind, token, name):
        status, made = self.call("POST", "/pair/new", {"kind": kind}, token)
        self.assertEqual(status, 200, made)
        status, paired = self.call("POST", "/pair", {"code": made["code"].lower(), "name": name})
        self.assertEqual(status, 200, paired)
        return made["code"], paired

    def test_the_owner_pairs_a_computer_that_pairs_phones(self):
        master = self.config["token"]
        code, pc = self.pair("pc", master, "Este computador")
        self.assertEqual(pc["device"]["kind"], "pc")
        self.assertNotIn(pc["token"], (self.home / "devices.json").read_text(encoding="utf-8"))
        self.assertEqual(self.call("POST", "/pair", {"code": code})[0], 400)  # single use
        _, phone = self.pair("phone", pc["token"], "Celular")
        self.assertEqual(phone["device"]["paired_by"], pc["device"]["id"])
        # A phone uses the panel but cannot pair devices, list them or stop the server.
        self.assertEqual(self.call("POST", "/pair/new", {"kind": "phone"}, phone["token"])[0], 403)
        self.assertEqual(self.call("GET", "/devices", token=phone["token"])[0], 403)
        self.assertEqual(self.call("POST", "/_stop", {}, phone["token"])[0], 403)
        self.assertEqual(self.call("GET", "/health", token=phone["token"])[0], 200)
        # A paired computer pairs phones only.
        self.assertEqual(self.call("POST", "/pair/new", {"kind": "pc"}, pc["token"])[0], 403)
        status, listed = self.call("GET", "/devices", token=pc["token"])
        self.assertEqual((status, [d["name"] for d in listed["devices"]], listed["you"]),
                         (200, ["Este computador", "Celular"], pc["device"]["id"]))
        # Revoking the computer revokes the phone it paired.
        status, done = self.call("POST", "/devices/revoke", {"id": pc["device"]["id"]}, master)
        self.assertEqual((status, done["revoked"]), (200, 2))
        self.assertEqual(self.call("GET", "/health", token=phone["token"])[0], 401)

    def test_codes_expire_and_wrong_guesses_lock_pairing(self):
        _, made = self.call("POST", "/pair/new", {"kind": "phone"}, self.config["token"])
        self.now[0] += 301
        self.assertEqual(self.call("POST", "/pair", {"code": made["code"]})[0], 400)
        for _ in range(19):
            self.assertEqual(self.call("POST", "/pair", {"code": "WRONG123"})[0], 400)
        self.assertEqual(self.call("POST", "/pair", {"code": "WRONG123"})[0], 429)
        _, fresh = self.call("POST", "/pair/new", {"kind": "phone"}, self.config["token"])
        self.assertEqual(self.call("POST", "/pair", {"code": fresh["code"]})[0], 429)  # still locked
        self.now[0] += 601
        self.assertEqual(self.call("POST", "/pair", {"code": fresh["code"]})[0], 400)  # expired meanwhile
        _, after = self.call("POST", "/pair/new", {"kind": "phone"}, self.config["token"])
        self.assertEqual(self.call("POST", "/pair", {"code": after["code"]})[0], 200)

    def test_pairing_this_computer_again_replaces_its_entry(self):
        self.pair("pc", self.config["token"], "Este computador")
        _, second = self.pair("pc", self.config["token"], "Este computador")
        self.assertEqual([d["id"] for d in self.devices.listed()], [second["device"]["id"]])


class ProjectManagementTest(unittest.TestCase):
    def test_add_remove_and_write_from_the_editor(self):
        with tempfile.TemporaryDirectory() as temp:
            home, project = Path(temp) / "remote", Path(temp) / "My App"
            project.mkdir()
            status = manage_projects(home, "add", path=str(project))
            self.assertEqual([(p["key"], p["exists"]) for p in status["projects"]], [("my-app", True)])
            self.assertFalse(status["allow_write"])
            with self.assertRaises(RemoteError):
                manage_projects(home, "add", path=str(project))
            with self.assertRaises(RemoteError):
                manage_projects(home, "add", path="relative/folder")
            self.assertTrue(manage_projects(home, "write", allow_write=True)["allow_write"])
            project.rmdir()
            self.assertFalse(remote_status(home)["projects"][0]["exists"])
            self.assertEqual(manage_projects(home, "remove", key="my-app")["projects"], [])

    def test_status_lists_devices_and_revokes_them_while_stopped(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            manage_projects(home, "write", allow_write=False)
            pc, _ = Devices(home).create("Este computador", "pc", None)
            Devices(home).create("Android", "phone", pc["id"])
            status = remote_status(home)
            self.assertFalse(status["running"])
            self.assertEqual(sorted(d["name"] for d in status["devices"]), ["Android", "Este computador"])
            revoke_device(home, pc["id"])
            self.assertEqual(remote_status(home)["devices"], [])
            with self.assertRaises(RemoteError):
                revoke_device(home, pc["id"])

    def test_panel_address_allows_its_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            status = set_panel_address(home, "https://pc.rede.ts.net/coding-opus")
            self.assertEqual(status["panel_url"], "https://pc.rede.ts.net/coding-opus/")
            self.assertTrue(status["panel"])
            for bad in ("http://pc.rede.ts.net/", "https://pc.rede.ts.net/?token=x", "não é url"):
                with self.assertRaises(RemoteError):
                    set_panel_address(home, bad)


class TailscaleInfoTest(unittest.TestCase):
    def fake(self, outputs):
        def run(command, **_):
            key = " ".join(command[1:-1])
            return subprocess.CompletedProcess(command, 0 if key in outputs else 1, json.dumps(outputs.get(key, {})), "")
        return run

    def test_finds_the_serve_route_to_the_panel(self):
        run = self.fake({
            "status": {"BackendState": "Running", "Self": {"DNSName": "PC.rede.ts.net."}},
            "serve status": {"Web": {"pc.rede.ts.net:443": {"Handlers": {
                "/outro": {"Proxy": "http://127.0.0.1:3000"}, "/painel": {"Proxy": "http://127.0.0.1:8769"}}}}},
        })
        info = tailscale_info(8769, run=run, exe="tailscale")
        self.assertEqual((info["host"], info["serve_path"], info["command"]), ("pc.rede.ts.net", "/painel", None))
        self.assertEqual(info["suggested"], "https://pc.rede.ts.net/painel/")

    def test_suggests_the_serve_command_when_not_published(self):
        run = self.fake({"status": {"BackendState": "Running", "Self": {"DNSName": "pc.rede.ts.net."}}})
        info = tailscale_info(8769, run=run, exe="tailscale")
        self.assertIsNone(info["serve_path"])
        self.assertEqual(info["suggested"], "https://pc.rede.ts.net/coding-opus/")
        self.assertIn("--set-path /coding-opus http://127.0.0.1:8769", info["command"])
        self.assertEqual(tailscale_info(8769, run=self.fake({}), exe="tailscale")["host"], None)

    def test_never_suggests_a_route_another_service_uses(self):
        run = self.fake({
            "status": {"BackendState": "Running", "Self": {"DNSName": "pc.rede.ts.net."}},
            "serve status": {"Web": {"pc.rede.ts.net:443": {"Handlers": {
                "/coding-opus": {"Proxy": "http://127.0.0.1:8769"}}}}},
        })
        info = tailscale_info(8791, run=run, exe="tailscale")
        self.assertEqual(info["suggested"], "https://pc.rede.ts.net/coding-opus-8791/")
        self.assertIn("--set-path /coding-opus-8791 ", info["command"])


if __name__ == "__main__":
    unittest.main()
