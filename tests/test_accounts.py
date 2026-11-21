import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Tests read the generic playbooks, not the personal default the skill ships.
os.environ.setdefault("CODING_OPUS_BUNDLED_PLAYBOOKS", str(Path(__file__).resolve().parent / "fixtures" / "playbooks.yaml"))
os.environ.setdefault("CODING_OPUS_TERMINALS", "0")

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "coding" / "scripts" / "orchestrate.py"
spec = importlib.util.spec_from_file_location("accounts_orchestrate", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

# Hits the usage limit on the default account (CODEX_HOME named "codex") and succeeds on any other.
FAKE_ACCOUNT_CLI = """
import os, sys
task = sys.stdin.read()
home = os.environ.get("CODEX_HOME", "")
if os.path.basename(home) == "codex":
    print("Error: 429 Too Many Requests. Your usage limit resets at 5:00 PM.", file=sys.stderr)
    sys.exit(1)
retried = "earlier attempt at this task stopped at a usage limit" in task
print(f"Outcome: done on {os.path.basename(home)}; retried={retried}")
"""


class AccountsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="coding-opus-accounts-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_cwd)
        self.policy = self.root / "policy.json"
        self.codex = self.root / "codex"
        self.codex.mkdir()
        (self.codex / "config.toml").write_text('model = "gpt-5.5"\n', encoding="utf-8")
        (self.codex / "auth.json").write_text("{}", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {
            "CODEX_HOME": str(self.codex),
            "CODING_OPUS_POLICY": str(self.policy),
            "CODING_OPUS_HOME": str(self.root / "orchestrations"),
            "CODING_OPUS_PLAYBOOKS": str(self.root / "coding-opus-playbooks.yaml"),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake_cli = self.root / "fake_account_cli.py"
        self.fake_cli.write_text(FAKE_ACCOUNT_CLI, encoding="utf-8")

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = runner.main(["--session-id", "accounts-test", *(str(arg) for arg in args)])
        return code, out.getvalue(), err.getvalue()

    def plan(self, name, **worker):
        path = self.root / (name + ".json")
        path.write_text(json.dumps({"version": 1, "strategy": "research", "maxConcurrent": 1, "workers": [
            {"id": "scout", "provider": "codex", "mode": "read-only", "cwd": str(self.root),
             "task": "Read the fixture.", **worker}]}), encoding="utf-8")
        return path

    def fake(self):
        def invocation(worker, cwd, worker_dir, *args):
            return [sys.executable, str(self.fake_cli)], True, "text", worker_dir / "result.md"
        return mock.patch.object(runner, "build_invocation", side_effect=invocation)

    def run_plan(self, plan):
        with self.fake():
            code, out, err = self.call("run", plan, "--run-dir", self.root / plan.stem, "--policy", self.policy)
        return code, json.loads(out), err

    def test_an_account_gets_its_own_home_with_settings_but_no_credentials(self):
        added = runner.add_account(self.policy, "codex", "work")
        home = Path(added["home"])
        self.assertEqual(home, self.root / "accounts" / "codex" / "work")
        self.assertEqual(added["copiedSettings"], ["config.toml"])
        self.assertTrue((home / "config.toml").is_file())
        self.assertFalse((home / "auth.json").exists())
        self.assertEqual(runner.account_rotation(self.policy, "codex"), ["default", "work"])
        self.assertEqual(runner.account_rotation(self.policy, "claude"), [])
        with self.assertRaisesRegex(runner.PlanError, "already has an account"):
            runner.add_account(self.policy, "codex", "work")
        with self.assertRaisesRegex(runner.PlanError, "default is the account"):
            runner.add_account(self.policy, "codex", "default")
        with self.assertRaisesRegex(runner.PlanError, "lowercase"):
            runner.add_account(self.policy, "codex", "../escape")
        with self.assertRaisesRegex(runner.PlanError, "accounts work with"):
            runner.add_account(self.policy, "agy", "work")

    def test_order_and_remove(self):
        runner.add_account(self.policy, "codex", "work")
        runner.add_account(self.policy, "codex", "spare")
        self.assertEqual(runner.order_accounts(self.policy, "codex", ["spare", "default"]), ["spare", "default", "work"])
        with self.assertRaisesRegex(runner.PlanError, "unknown: ghost"):
            runner.order_accounts(self.policy, "codex", ["ghost"])
        removed = runner.remove_account(self.policy, "codex", "spare", delete_home=True)
        self.assertTrue(removed["deletedHome"])
        self.assertFalse((self.root / "accounts" / "codex" / "spare").exists())
        self.assertEqual(runner.account_rotation(self.policy, "codex"), ["default", "work"])

    def test_the_account_cli_registers_without_logging_in(self):
        code, out, err = self.call("account", "add", "codex", "work", "--no-login", "--policy", self.policy)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["name"], "work")
        self.assertIn("account login codex work", err)
        code, out, _ = self.call("account", "list", "--no-login-check", "--policy", self.policy)
        names = [entry["name"] for entry in json.loads(out)["providers"]["codex"]]
        self.assertEqual(names, ["default", "work"])

    def test_worker_environment_points_the_cli_at_the_account_home(self):
        env = runner.worker_environment("codex", None, str(self.root / "accounts" / "codex" / "work"))
        self.assertEqual(env["CODEX_HOME"], str(self.root / "accounts" / "codex" / "work"))
        env = runner.worker_environment("claude", None, "C:/claude-home")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "C:/claude-home")
        self.assertEqual(runner.worker_environment("codex")["CODEX_HOME"], str(self.codex))

    def test_account_readings_never_block_each_other(self):
        runner.add_account(self.policy, "codex", "work")
        now = dt.datetime.now(dt.timezone.utc)
        windows = {"5h": {"usedPercent": 99, "resetsAt": (now + dt.timedelta(hours=2)).isoformat()}}
        runner.save_usage(self.policy, {"provider": "codex", "observedAt": now.isoformat(), "windows": windows})
        worker = {"provider": "codex", "model": None}
        self.assertIn("codex is at 99%", runner.quota_refusal([worker], self.policy))
        self.assertIsNone(runner.quota_refusal([{**worker, "account": "work"}], self.policy))
        self.assertIsNone(runner.account_quota_refusal([worker], self.policy))
        runner.save_usage(self.policy, {"provider": "codex", "account": "work", "observedAt": now.isoformat(),
                                        "windows": windows})
        self.assertIn("every codex account", runner.account_quota_refusal([worker], self.policy))
        usage = runner.usage_payload(self.policy, refresh=False)
        self.assertTrue(usage["accounts"]["codex@work"]["blocked"])

    def test_a_rate_limited_worker_moves_to_the_next_account(self):
        runner.add_account(self.policy, "codex", "work")
        code, result, _ = self.run_plan(self.plan("moves"))
        self.assertEqual(code, 0)
        outcome = result["workers"][0]
        self.assertEqual(outcome["status"], "succeeded")
        self.assertEqual(outcome["account"], "work")
        self.assertEqual([attempt["account"] for attempt in outcome["accountAttempts"]], ["default"])
        self.assertEqual(outcome["accountAttempts"][0]["failureKind"], "rate_limited")
        worker_dir = self.root / "moves" / "workers" / "scout"
        self.assertIn("429", (worker_dir / "attempt-1-stderr.log").read_text(encoding="utf-8"))
        self.assertIn("done on work; retried=True", (worker_dir / "stdout.log").read_text(encoding="utf-8"))
        saved = json.loads((worker_dir / "outcome.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["accountAttempts"][0]["account"], "default")
        markdown = self.call("report", self.root / "moves")[1]
        self.assertIn("default -> codex (work)", markdown)

    def test_a_pinned_account_never_moves(self):
        runner.add_account(self.policy, "codex", "work")
        code, result, _ = self.run_plan(self.plan("pinned", account="default"))
        self.assertEqual(code, 1)
        outcome = result["workers"][0]
        self.assertEqual((outcome["failureKind"], outcome["account"]), ("rate_limited", "default"))
        self.assertNotIn("accountAttempts", outcome)

    def test_without_accounts_a_worker_runs_as_before(self):
        code, result, _ = self.run_plan(self.plan("plain"))
        self.assertEqual(code, 1)
        outcome = result["workers"][0]
        self.assertEqual((outcome["failureKind"], outcome["account"]), ("rate_limited", None))

    def coding_agent_file(self, codex=(), claude=(), active=None, instance="coding-agent-2"):
        # A legacy export still present beside the policy.
        def entries(items):
            return [{"id": item_id, "email": email, "label": None, "home": str(home)} for item_id, email, home in items]
        path = self.root / f"coding-agent-accounts.{instance}.json"
        path.write_text(json.dumps({"version": 1, "source": "fixture", "updatedAt": "2026-11-11T00:00:00Z",
                                    "active": active or {"codex": None, "claude": None},
                                    "providers": {"codex": entries(codex), "claude": entries(claude)}}), encoding="utf-8")
        return path

    def managed_home(self, name):
        home = self.root / "coding-agent-2" / name / "home"
        home.mkdir(parents=True)
        return home

    def test_legacy_agent_accounts_are_excluded_from_rotation(self):
        work = self.managed_home("codex-1")
        manifest = self.coding_agent_file(codex=[("codex-1", "Me@Work.example", work)])
        runner.add_account(self.policy, "codex", "spare")
        data = runner.load_accounts(self.policy)
        data["order"]["codex"] = ["me-work-example", "spare", "default"]
        runner.save_accounts(self.policy, data)

        self.assertEqual(runner.account_rotation(self.policy, "codex"), ["spare", "default"])
        self.assertTrue(manifest.is_file())
        self.assertTrue(work.is_dir())
        with self.assertRaisesRegex(runner.PlanError, "no account me-work-example"):
            runner.account_home(self.policy, "codex", "me-work-example")

    def test_add_uses_the_opus_registry_in_the_presence_of_an_agent_export(self):
        self.coding_agent_file()
        code, _, _ = self.call("account", "add", "codex", "solo", "--no-login", "--policy", self.policy)
        self.assertEqual(code, 0)
        self.assertEqual(runner.account_rotation(self.policy, "codex"), ["default", "solo"])

    def test_a_plan_names_only_known_accounts(self):
        with self.assertRaisesRegex(runner.PlanError, "no account ghost"):
            runner.validate_plan(json.loads(self.plan("ghost", account="ghost").read_text(encoding="utf-8")),
                                 self.root / "ghost.json", policy_path=self.policy)


if __name__ == "__main__":
    unittest.main()
