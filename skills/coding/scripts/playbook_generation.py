"""Generate one validated playbook through a local CLI; never save or execute it."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

import orchestrate
from usage_refresh import UsageRefresh
from account_management import selected_account, profile_environment

LIMIT = 1 << 20
TIMEOUT = 120


class GenerationError(Exception):
    pass


def generation_schema(providers):
    string = {"type": "string"}
    conditions = ["", "narrow", "research", "light", "code", "deep", "review", "checks-failed", "checks-failed:2", "budget-low"]
    conditions += [f"{provider}-{suffix}" for provider in providers for suffix in ("low", "spare")]
    phase = {
        "id": string, "role": string, "who": {"type": "string", "enum": ["lead", "worker"]},
        "provider": {"type": "string", "enum": ["auto", *providers]},
        "tier": {"type": "string", "enum": ["cheap", "standard", "strong"]},
        "readOnly": {"type": "boolean"}, "workers": {"type": "integer", "minimum": 1, "maximum": 4},
        "does": string, "returns": string, "gate": string,
        "if": {"type": "string", "enum": conditions}, "then": {"type": "string", "enum": ["", "done", "recheck"]},
        "with": {"type": "string", "description": "Parallel main phase id, or empty for a normal sequence."},
        "after": {"type": "string", "description": "Only a gate-failure repair chain; empty for normal sequential steps."},
    }
    fields = {key: string for key in ("name", "goal", "pickWhen", "saves", "avoidWhen")}
    fields["phases"] = {"type": "array", "minItems": 1, "maxItems": 8, "items": {
        "type": "object", "properties": phase, "required": list(phase), "additionalProperties": False}}
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def validate_request(request):
    if not isinstance(request, dict) or request.get("provider") not in ("codex", "claude"):
        raise GenerationError("invalid-provider")
    instructions, text = request.get("instructions"), request.get("text")
    if not isinstance(instructions, str) or not 10 <= len(instructions.strip()) <= 8000:
        raise GenerationError("invalid-instructions")
    if not isinstance(text, str) or len(text.encode("utf-8")) > LIMIT:
        raise GenerationError("invalid-playbooks")
    try:
        settings = orchestrate.parse_playbooks_yaml(text)
        if orchestrate.playbook_structure_errors(settings):
            raise GenerationError("invalid-playbooks")
    except orchestrate.PlanError:
        raise GenerationError("invalid-playbooks") from None
    if request["provider"] not in settings["providers"]:
        raise GenerationError("invalid-provider")
    return settings


def validated_proposal(value, settings):
    if not isinstance(value, dict) or set(value) - set(generation_schema(settings["providers"])["properties"]):
        raise GenerationError("invalid-result")
    book = copy.deepcopy(value)
    phases = book.get("phases")
    if not isinstance(phases, list) or not 1 <= len(phases) <= 8:
        raise GenerationError("invalid-result")
    allowed_conditions = generation_schema(settings["providers"])["properties"]["phases"]["items"]["properties"]["if"]["enum"]
    seen = set()
    emitted = {}
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict) or set(phase) - set(generation_schema(settings["providers"])["properties"]["phases"]["items"]["properties"]):
            raise GenerationError("invalid-result")
        for key in list(phase):
            if phase[key] == "" and key in ("if", "then", "with", "after", "gate"):
                del phase[key]
        if phase.get("if", "") not in allowed_conditions:
            raise GenerationError("invalid-result")
        for key in ("with", "after"):
            if key in phase and phase[key] not in seen:
                raise GenerationError("invalid-result")
        if "after" in phase:
            target = emitted[phase["after"]]
            if "with" in phase:
                raise GenerationError("invalid-result")
            if not target.get("gate") and not target.get("after"):
                if index and phase["after"] == phases[index - 1]["id"]:
                    del phase["after"]
                else:
                    raise GenerationError("invalid-result")
        if phase.get("workers", 1) > 4 or any(isinstance(item, str) and len(item) > 4000 for item in phase.values()):
            raise GenerationError("invalid-result")
        if phase.get("workers", 1) > 1 and not phase.get("readOnly", False):
            phase["isolate"] = True
        if phase.get("then") == "recheck" and (not phase.get("after") or not any(p.get("gate") for p in phases[:len(seen)])):
            raise GenerationError("invalid-result")
        seen.add(phase.get("id"))
        emitted[phase.get("id")] = phase
    if not isinstance(book.get("name"), str) or not book["name"].strip() or len(book["name"]) > 120:
        raise GenerationError("invalid-result")
    merged = copy.deepcopy(settings)
    key = "generated"
    index = 1
    while key in merged["playbooks"]:
        key = f"generated-{index}"
        index += 1
    merged["playbooks"][key] = book
    if orchestrate.playbook_structure_errors(merged):
        raise GenerationError("invalid-result")
    text = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > LIMIT:
        raise GenerationError("invalid-result")
    return {"id": key, "text": text}


def generate_response(prompt, provider, schema, account_home=None):
    with tempfile.TemporaryDirectory(prefix="coding-playbook-") as temporary:
        folder = Path(temporary)
        worker = {"provider": provider, "mode": "read-only", "model": None, "effort": None,
                  "resume": None, "mcp": False, "task": prompt}
        cache, lock = {}, threading.Lock()
        args, _, output_format, result_path = orchestrate.build_invocation(worker, folder, folder, cache, lock, TIMEOUT)
        launch = orchestrate.launch_command(orchestrate.resolve_executable(provider))
        if provider == "codex":
            help_text = orchestrate.command_output([*launch, "exec", "--help"], cache, lock)
            if "--output-schema" not in help_text or "--ephemeral" not in help_text:
                raise GenerationError("cli-update-required")
            schema_path = folder / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            args[-1:-1] = ["--output-schema", str(schema_path), "--ephemeral"]
            features = orchestrate.command_output([*launch, "features", "list"], cache, lock)
            for feature in ("shell_tool", "apply_patch_freeform", "js_repl"):
                if re.search(rf"^{feature}\s", features, re.MULTILINE):
                    args[len(launch):len(launch)] = ["--disable", feature]
        else:
            help_text = orchestrate.command_help(launch, cache, lock)
            if any(flag not in help_text for flag in ("--tools", "--no-session-persistence", "--json-schema")):
                raise GenerationError("cli-update-required")
            args += ["--tools", "", "--no-session-persistence", "--json-schema", json.dumps(schema)]
        env = {**profile_environment(provider, account_home), orchestrate.WORKER_ENV_FLAG: "1"}
        process = orchestrate.start_process(args, folder, subprocess.PIPE, subprocess.PIPE, subprocess.PIPE, env)
        try:
            try:
                stdout, _ = process.communicate(prompt.encode("utf-8"), timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                raise GenerationError("timeout") from None
            if process.returncode or len(stdout) > LIMIT * 4:
                raise GenerationError("generation-failed")
            if provider == "codex":
                if not result_path.is_file() or result_path.stat().st_size > LIMIT:
                    raise GenerationError("invalid-result")
                return json.loads(result_path.read_text(encoding="utf-8"))
            for event in reversed(orchestrate.json_values(stdout.decode("utf-8", errors="replace"), output_format)):
                if isinstance(event, dict) and isinstance(event.get("structured_output"), dict):
                    return event["structured_output"]
                if isinstance(event, dict) and event.get("type") == "result" and isinstance(event.get("result"), str):
                    return json.loads(event["result"])
            raise GenerationError("invalid-result")
        finally:
            orchestrate.stop_process_tree(process)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()


class PlaybookGenerator:
    def __init__(self, policy_path, reader=generate_response, usage=None):
        self.policy_path = policy_path
        self.reader = reader
        self.usage = usage or UsageRefresh(policy_path)
        self.lock = threading.Lock()

    def generate(self, request):
        if not self.lock.acquire(blocking=False):
            return {"ok": False, "error": "busy"}
        try:
            settings = validate_request(request)
            provider = request["provider"]
            account, home = selected_account(self.policy_path, provider)
            if orchestrate.load_prices(self.policy_path)["billing"].get(provider, "subscription") != "subscription":
                raise GenerationError("subscription-required")
            snapshot = self.usage.refresh([provider])
            if snapshot.get("statuses", {}).get(provider, {}).get("reason") == "sign-in-required":
                raise GenerationError("sign-in-required")
            if orchestrate.quota_refusal([{"provider": provider, "account": account, "model": None}], self.policy_path):
                raise GenerationError("quota-exhausted")
            catalog = orchestrate.model_catalog(self.policy_path)
            context = {key: settings.get(key) for key in ("providers", "tiers", "profiles", "profile", "quota", "principles")}
            context["catalog"] = catalog
            context["usage"] = snapshot
            schema = generation_schema(settings["providers"])
            prompt = ("Create exactly one Coding Opus playbook from the user's instructions. Return only JSON matching the schema. "
                      "Do not execute the requested project task, call tools, read files, or change any files. "
                      "Keep 1-8 phases, use one worker unless independent work needs more. "
                      "Choose provider and tier using the real configuration; tiers resolve the actual models at execution time. "
                      "Use auto to allow quota fallback. Do not invent models or modify global configuration. "
                      "Empty strings mean absent optional fields. Main phases run sequentially in list order: leave after empty. "
                      "with references an earlier parallel main phase. after is ONLY for a gate-failure repair chain, "
                      "referencing a gated phase or a previous repair in that chain. "
                      "Use a gate for validation; then recheck is only for a repair following a gate. "
                      "Write metadata in the language of the instructions. Context:\n" + json.dumps(context, ensure_ascii=False) +
                      "\nSchema:\n" + json.dumps(schema) + "\nUser instructions:\n" + request["instructions"].strip())
            result = validated_proposal(self.reader(prompt, provider, schema, home), settings)
            return {"ok": True, "value": result}
        except GenerationError as error:
            return {"ok": False, "error": str(error)}
        except (OSError, ValueError, TypeError, KeyError, orchestrate.PlanError, subprocess.SubprocessError):
            return {"ok": False, "error": "generation-failed"}
        finally:
            self.lock.release()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(LIMIT * 2 + 1)
        if len(raw) > LIMIT * 2:
            raise ValueError("input too large")
        payload = json.loads(raw)
        response = PlaybookGenerator(arguments.policy).generate(payload)
    except (ValueError, OSError):
        response = {"ok": False, "error": "invalid-playbooks"}
    print(json.dumps(response, ensure_ascii=False))
