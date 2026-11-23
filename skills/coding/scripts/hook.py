#!/usr/bin/env python3
"""Cheap Claude Code hook gate; import the runner only when a check may print."""

from __future__ import annotations

import json
import os
import re
import sys
import time


def session_state_filename(session: str) -> str:
    import hashlib

    # Kept in sync with orchestrate.session_state_filename by a parity test.
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", session)[:80] or "session"
    digest = hashlib.sha256(session.encode("utf-8")).hexdigest()[:12]
    return f"{safe}-{digest}.json"


def orchestrations_home() -> str:
    configured = os.environ.get("CODING_OPUS_HOME")
    if configured:
        return os.path.expanduser(configured)
    policy = os.environ.get("CODING_OPUS_POLICY")
    if policy:
        return os.path.join(os.path.dirname(os.path.expanduser(policy)), "orchestrations")
    if os.name == "nt":
        # orchestrate.py moved the state out of %APPDATA% (see windows_state_dir) and migrates it on first use.
        base = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), ".coding-opus")
    else:
        base = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "coding-opus")
    return os.path.join(base, "orchestrations")


def setup_marker_path() -> str:
    """Written once Coding Opus is set up (second brain and global rules), so later prompts skip the check."""
    return os.path.join(os.path.dirname(orchestrations_home()), "setup.json")


def first_run_setup(event: dict) -> str:
    """Set Coding Opus up on the first prompt after the plugin is installed: no /coding install needed.

    Creates or reuses the second brain and writes the coding-opus block of the global rules, like
    `brain.py install --no-desktop` (the app installs itself the first time the editor opens).
    CODING_OPUS_AUTO_SETUP=0 turns this off. Returns context for the model, or "".
    """
    if event.get("hook_event_name", "UserPromptSubmit") != "UserPromptSubmit":
        return ""
    if os.environ.get("CODING_OPUS_AUTO_SETUP") == "0" or os.path.exists(setup_marker_path()):
        return ""
    import brain

    report = brain.automatic_setup()
    if report is None:
        return ""  # Set up by hand before the marker existed; now remembered.
    state = "criado" if report.get("created") else "reaproveitado"
    rules = ", ".join(report.get("globalRules") or {}) or "nenhum"
    return (
        "Coding Opus acabou de se configurar sozinho, no primeiro uso. "
        f"Second brain {state} em {report['secondBrain']}. Regras globais gravadas em: {rules}. "
        "Conte isso ao usuário em uma linha antes de responder, e siga com o pedido dele.\n"
    )


def read_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def covers(scope: str, cwd: str) -> bool:
    root = os.path.realpath(scope)
    try:
        return os.path.commonpath([cwd, root]) == root
    except ValueError:
        return False


def mode_is_off(state: dict, cwd: str, now: float, post_tool: bool) -> bool:
    modes = state.get("modes") or {}
    matches = [scope for scope, mode in modes.items() if isinstance(mode, dict)
               and type(mode.get("seenAt")) in (int, float) and 0 <= mode["seenAt"] < float("inf")
               and now - mode["seenAt"] < 12 * 3600 and covers(scope, cwd)]
    if matches:
        mode = modes[max(matches, key=len)]
        return post_tool and mode.get("goal") != "passive"
    if any(covers(scope, cwd) for scope in state.get("offIn") or []):
        return True
    mode = state.get("everywhere")
    if isinstance(mode, dict) and mode:
        import datetime as dt

        expires = mode.get("expiresAt")
        if not isinstance(expires, str):
            raise ValueError("legacy mode needs the full reader to persist its expiry")
        stamp = dt.datetime.fromisoformat(expires.replace("Z", "+00:00"))
        stamp = stamp.replace(tzinfo=dt.timezone.utc) if stamp.tzinfo is None else stamp
        stamp = stamp.astimezone(dt.timezone.utc)
        if stamp.timestamp() > now:
            return post_tool and mode.get("goal") != "passive"
    return state.get("passive") is False or os.environ.get("CODING_OPUS_PASSIVE") == "0"


def skip_hook(event: dict, now: float) -> bool:
    cwd = os.path.realpath(os.path.expanduser(event.get("cwd") or os.getcwd()))
    post_tool = event.get("hook_event_name", "UserPromptSubmit") == "PostToolUse"
    home = orchestrations_home()
    try:
        if mode_is_off(read_state(os.path.join(home, "modes.json")), cwd, now, post_tool):
            return True
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        return False  # Migrate legacy expiry or sanitize malformed state in the full reader.
    if not post_tool:
        return False
    transcript = event.get("transcript_path")
    session = str(event.get("session_id") or (os.path.splitext(os.path.basename(transcript))[0] if transcript else "cwd:" + cwd))
    check = read_state(os.path.join(home, "passive", session_state_filename(session))).get("check", {})
    minutes, printed = check.get("checkEveryMinutes"), check.get("lastPrinted")
    if type(minutes) not in (int, float) or type(printed) not in (int, float):
        return False  # Old or absent state needs the full path to initialize the interval.
    return 0 < minutes < float("inf") and abs(printed) < float("inf") and now - printed < minutes * 60


def full_hook_output(stdin_text: str) -> str:
    import orchestrate

    event = json.loads(stdin_text) if stdin_text.strip() else {}
    session = os.environ.get("CODING_OPUS_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID") or event.get("session_id")
    if session:
        try:
            orchestrate.session_runtime(str(session))
        except orchestrate.PlanError as error:
            return f"Coding Opus: {error}\n"
    return orchestrate.hook_output(stdin_text)


def hook_output(stdin_text: str) -> str:
    if os.environ.get("CODING_OPUS_WORKER") == "1":
        return ""
    try:
        event = json.loads(stdin_text) if stdin_text.strip() else {}
        if not isinstance(event, dict):
            return ""
        try:
            setup = first_run_setup(event)
        except Exception:  # A failed setup is retried on the next prompt; it never blocks this one.
            setup = ""
        if skip_hook(event, time.time()):
            return setup
        return setup + full_hook_output(stdin_text)
    except Exception:  # A hook must never block or fail the prompt.
        return ""


def main() -> int:
    if os.environ.get("CODING_OPUS_WORKER") == "1":
        return 0
    try:
        stream = getattr(sys.stdin, "buffer", None)
        text = stream.read().decode("utf-8", errors="replace") if stream is not None else sys.stdin.read()
        output = hook_output(text)
        out = getattr(sys.stdout, "buffer", None)
        if out is not None:  # UTF-8 whatever the console code page (cp1252 would garble accents)
            out.write(output.encode("utf-8"))
            out.flush()
        else:
            print(output, end="")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
