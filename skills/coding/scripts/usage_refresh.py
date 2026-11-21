"""Read subscription quotas without starting an inference turn."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import orchestrate
from account_management import selected_account, profile_environment

MAX_RESPONSE = 1_000_000
REFRESH_SECONDS = 300
TIMEOUT_SECONDS = 20


class UsageError(Exception):
    def __init__(self, reason, retry_at=None):
        super().__init__(reason)
        self.reason, self.retry_at = reason, retry_at


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def stamp(value):
    if value is None:
        return None
    parsed = orchestrate.timestamp(value)
    return parsed.isoformat() if parsed else None


def window(percent, reset):
    number = orchestrate.number(percent)
    if number is None or not 0 <= number <= 100:
        return None
    return {"usedPercent": round(number, 4), "resetsAt": stamp(reset)}


def reading(windows, source, observed_at=None):
    windows = {key: value for key, value in windows.items() if value is not None}
    if not windows:
        raise UsageError("usage-unavailable")
    return {"windows": windows, "source": source, "observedAt": observed_at or utc_now().isoformat()}


def codex_reading(payload):
    buckets = payload.get("rateLimitsByLimitId") or {}
    limits = buckets.get("codex") or payload.get("rateLimits") or {}
    windows = {}
    for key in ("primary", "secondary"):
        raw = limits.get(key)
        if not isinstance(raw, dict):
            continue
        minutes = raw.get("windowDurationMins")
        name = {300: "5h", 10080: "week", 43200: "month"}.get(minutes)
        if name:
            windows[name] = window(raw.get("usedPercent"), raw.get("resetsAt"))
    return reading(windows, "codex-app-server")


def claude_reading(payload):
    windows = {}
    for key, name in (("five_hour", "5h"), ("seven_day", "week"), ("seven_day_opus", "opus")):
        raw = payload.get(key)
        if isinstance(raw, dict):
            windows[name] = window(raw.get("utilization", raw.get("used_percentage")), raw.get("resets_at"))
    return reading(windows, "claude-oauth")


def kimi_reading(payload):
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise UsageError("usage-unavailable")
    if data.get("kind") == "error":
        code = data.get("status")
        raise UsageError("sign-in-required" if code in (401, 403) else "usage-unavailable")
    quota = data.get("quota", data)
    usages = quota.get("usages") or {}
    windows = {}
    for key, name in (("limit5h", "5h"), ("limit7d", "week"), ("monthTotal", "month"), ("monthCode", "monthCode")):
        raw = usages.get(key)
        if isinstance(raw, dict):
            ratio = orchestrate.number(raw.get("usedRatio"))
            windows[name] = window(ratio * 100 if ratio is not None else None, raw.get("resetAt"))
    return reading(windows, "kimi-cli")


def opencode_reading(payload):
    usage = payload.get("usage") or {}
    return reading({name: window(raw.get("percent"), raw.get("resetsAt"))
                    for key, name in (("rolling", "5h"), ("weekly", "week"), ("monthly", "month"))
                    if isinstance((raw := usage.get(key)), dict)}, "opencode-api")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_json(url, headers=None, timeout=10):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            retry = error.headers.get("Retry-After", "300")
            try:
                retry_at = utc_now() + dt.timedelta(seconds=max(300, float(retry)))
            except ValueError:
                try:
                    retry_at = email.utils.parsedate_to_datetime(retry)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=dt.timezone.utc)
                except (TypeError, ValueError):
                    retry_at = utc_now() + dt.timedelta(seconds=REFRESH_SECONDS)
            raise UsageError("rate-limited", retry_at.isoformat()) from None
        raise UsageError("sign-in-required" if error.code in (401, 403) else "provider-error") from None
    except (OSError, urllib.error.URLError):
        raise UsageError("network") from None
    if len(raw) > MAX_RESPONSE:
        raise UsageError("usage-unavailable")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise UsageError("usage-unavailable") from None
    if not isinstance(result, dict):
        raise UsageError("usage-unavailable")
    return result


def launch(provider, args, **options):
    try:
        command = orchestrate.launch_command(orchestrate.resolve_executable(provider))
    except orchestrate.PlanError:
        raise UsageError("cli-unavailable") from None
    return subprocess.Popen([*command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, shell=False,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                            **options)


def stop(process):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream:
            stream.close()


def output_queue(process):
    messages = queue.Queue(maxsize=128)
    def read(stream):
        try:
            while True:
                line = stream.readline(MAX_RESPONSE + 1)
                if not line:
                    return
                if len(line) > MAX_RESPONSE:
                    return
                try:
                    messages.put_nowait(line.decode("utf-8", errors="replace"))
                except queue.Full:
                    return
        except (OSError, ValueError):
            return
    for stream in (process.stdout, process.stderr):
        threading.Thread(target=read, args=(stream,), daemon=True).start()
    return messages


def fetch_codex(env=None):
    process = launch("codex", ["app-server", "--listen", "stdio://"], env=env)
    messages = output_queue(process)
    try:
        process.stdin.write((json.dumps({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "coding-opus-usage", "version": "37"}}}) + "\n").encode())
        process.stdin.flush()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                value = json.loads(messages.get(timeout=max(0.01, deadline - time.monotonic())))
            except ValueError:
                continue
            except queue.Empty:
                break
            if not isinstance(value, dict) or value.get("id") not in (1, 2):
                continue
            if value.get("error"):
                message = str(value["error"].get("message", "")).lower()
                raise UsageError("sign-in-required" if any(word in message for word in ("auth", "token", "login", "sign in")) else "provider-error")
            if value["id"] == 1:
                process.stdin.write(b'{"method":"initialized"}\n{"id":2,"method":"account/rateLimits/read","params":{}}\n')
                process.stdin.flush()
            else:
                return codex_reading(value.get("result") or {})
        raise UsageError("timeout")
    finally:
        stop(process)


def claude_token(config_dir=None):
    configured = str(config_dir) if config_dir is not None else os.environ.get("CLAUDE_CONFIG_DIR")
    folder = Path(configured or Path.home() / ".claude")
    try:
        credentials = json.loads((folder / ".credentials.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        credentials = {}
    token = credentials.get("claudeAiOauth", {}).get("accessToken")
    if token:
        return token
    if sys_platform() == "darwin":
        service = "Claude Code-credentials"
        if configured:
            service += "-" + hashlib.sha256(unicodedata.normalize("NFC", configured).encode()).hexdigest()[:8]
        result = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                                capture_output=True, timeout=5)
        if result.returncode == 0:
            try:
                return json.loads(result.stdout).get("claudeAiOauth", {}).get("accessToken")
            except ValueError:
                pass
    raise UsageError("sign-in-required")


def sys_platform():
    import sys
    return sys.platform


def fetch_claude(config_dir=None):
    token = claude_token(config_dir)
    return claude_reading(request_json("https://api.anthropic.com/api/oauth/usage", {
        "Authorization": "Bearer " + token, "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "coding-opus/36"}))


def fetch_agy():
    process = launch("agy", ["-p", "/usage", "--output-format", "json"])
    try:
        try:
            stdout, _ = process.communicate(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise UsageError("timeout") from None
        if len(stdout) > MAX_RESPONSE:
            raise UsageError("usage-unavailable")
        result = orchestrate.agy_quota(orchestrate.json_values(stdout.decode("utf-8", errors="replace"), "json"), utc_now().isoformat())
        if not result:
            raise UsageError("sign-in-required" if process.returncode else "usage-unavailable")
        result["source"] = "antigravity-cli"
        return result
    finally:
        stop(process)


def fetch_kimi():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = launch("kimi", ["web", "--host", "127.0.0.1", "--port", str(port), "--no-open"])
    messages = output_queue(process)
    try:
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", messages.get(timeout=max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                break
            token = None
            for url in re.findall(r"https?://[^\s<>]+", line):
                parsed = urllib.parse.urlsplit(url)
                if parsed.hostname not in ("127.0.0.1", "localhost") or parsed.port != port:
                    continue
                params = urllib.parse.parse_qs(parsed.query + "&" + parsed.fragment)
                token = next(iter(params.get("token", [])), None)
            match = re.search(r"(?:bearer token|token)\s*[:=]\s*([A-Za-z0-9_-]{20,})", line, re.I)
            token = token or (match.group(1) if match else None)
            if token:
                return kimi_reading(request_json(f"http://127.0.0.1:{port}/api/v1/oauth/usage", {
                    "Authorization": "Bearer " + token}))
        raise UsageError("usage-unavailable")
    finally:
        stop(process)


def fetch_opencode():
    token = os.environ.get("OPENCODE_API_KEY")
    if not token:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        try:
            raw = os.environ.get("OPENCODE_AUTH_CONTENT") or (root / "opencode/auth.json").read_text(encoding="utf-8")
            auth = json.loads(raw).get("opencode-go", {})
            token = auth.get("key") if auth.get("type") == "api" else None
        except (OSError, ValueError):
            pass
    if not token:
        raise UsageError("sign-in-required")
    return opencode_reading(request_json("https://opencode.ai/zen/go/v1/usage", {"Authorization": "Bearer " + token}))


READERS = {"codex": fetch_codex, "claude": fetch_claude, "agy": fetch_agy,
           "kimi": fetch_kimi, "opencode": fetch_opencode}


class UsageRefresh:
    def __init__(self, policy_path, readers=None, clock=utc_now):
        self.policy_path = policy_path
        self.readers = READERS if readers is None else readers
        self.clock = clock
        self.next_at = {}
        self.statuses = {}
        self.readings = {}
        self.contexts = {}
        self.lock = threading.Lock()

    def refresh(self, providers):
        with self.lock:
            now = self.clock()
            providers = list(dict.fromkeys(providers))
            contexts = {provider: selected_account(self.policy_path, provider) if self.readers is READERS else ('default', None)
                        for provider in providers}
            for provider, context in contexts.items():
                if self.contexts.get(provider) != context:
                    self.next_at.pop(provider, None)
                    self.statuses.pop(provider, None)
                    self.readings.pop(provider, None)
                self.contexts[provider] = context
            due = [provider for provider in providers if now >= self.next_at.get(provider, now)]
            def fetch(provider):
                reader = self.readers.get(provider)
                if not reader:
                    return provider, None, UsageError("not-supported")
                try:
                    _, home = contexts[provider]
                    if self.readers is READERS and provider == 'codex':
                        result = fetch_codex(profile_environment(provider, home))
                    elif self.readers is READERS and provider == 'claude':
                        result = fetch_claude(home)
                    else:
                        result = reader()
                    return provider, result, None
                except UsageError as error:
                    return provider, None, error
                except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
                    return provider, None, UsageError("provider-error")
            if due:
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                    for provider, result, error in pool.map(fetch, due):
                        retry_at = now + dt.timedelta(seconds=REFRESH_SECONDS)
                        if error and error.retry_at:
                            retry_at = max(retry_at, orchestrate.timestamp(error.retry_at) or retry_at)
                        self.next_at[provider] = retry_at
                        self.statuses[provider] = {"state": "error" if error else "ok",
                                                   "reason": error.reason if error else None,
                                                   "retryAt": retry_at.isoformat()}
                        if result:
                            valid = {key: value for key, value in result["windows"].items() if value.get("resetsAt")}
                            account = contexts[provider][0]
                            if account != 'default':
                                result = {**result, 'account': account}
                            if valid and provider in orchestrate.QUOTA_PROVIDERS:
                                orchestrate.save_usage(self.policy_path, {**result, "provider": provider, "windows": valid})
                            self.readings[provider] = result
            cached = orchestrate.saved_usage(self.policy_path)
            readings = {}
            for provider in providers:
                account = contexts[provider][0]
                key = orchestrate.quota_key(provider, account) if provider in ('codex', 'claude') else provider
                if key in cached:
                    readings[provider] = cached[key]
            readings.update({key: value for key, value in self.readings.items() if key in providers})
            return {"providers": readings, "statuses": {key: value for key, value in self.statuses.items() if key in providers}}
