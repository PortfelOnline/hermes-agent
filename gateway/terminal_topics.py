"""Mirror active local Hermes CLI terminals into Telegram direct-message topics.

This module deliberately contains no Telegram credentials. The gateway control
socket supplies its already-running Telegram adapter, so the sync never starts a
second Bot API polling client.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, cast


_TERMINAL_ACTIVATE_SCRIPT = 'tell application "Terminal" to activate'


def focus_terminal_app() -> bool:
    """Bring Terminal.app to the foreground on the gateway's local Mac.

    The caller intentionally gets no shell input: this only activates the
    already-running terminal application that owns the mirrored CLI task.
    """
    if sys.platform != "darwin":
        return False
    try:
        subprocess.Popen(["/usr/bin/osascript", "-e", _TERMINAL_ACTIVATE_SCRIPT])
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class TerminalTask:
    """One live Hermes CLI task that owns a real terminal TTY."""

    tty: str
    session_id: str
    cwd: str
    title: str | None = None

    @property
    def label(self) -> str:
        """Short human label: the task's own title when set, else the project folder."""
        title = " ".join((self.title or "").split()).strip()
        if title:
            return title[:60]
        return Path(self.cwd).name or self.cwd or "Hermes"

    @property
    def topic_name(self) -> str:
        # Keyed by TTY, not session_id: a `hermes --cli` restart in the SAME open terminal window
        # must reuse its existing topic, not spawn a new one every time the session id changes.
        return f"🟢 {self.label} · {self.tty}"

    @property
    def status_text(self) -> str:
        return (
            "🟢 **Hermes CLI task online**\n"
            f"TTY: `{self.tty}`\n"
            f"Project: `{self.cwd}`\n"
            f"Session: `{self.session_id}`"
        )


def _live_hermes_ttys(ps_output: str) -> set[str]:
    """TTY names with a live ``hermes --cli`` process in ``ps`` output."""
    ttys: set[str] = set()
    for raw in ps_output.splitlines():
        parts = raw.split(maxsplit=2)
        if len(parts) != 3:
            continue
        _pid, tty, command = parts
        if tty.startswith("ttys") and "hermes_cli.main" in command and "--cli" in command:
            ttys.add(tty)
    return ttys


def _breadcrumb_task(path: Path, *, now: float, max_age_seconds: float) -> TerminalTask | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        timestamp_raw = data.get("ts")
        if not isinstance(timestamp_raw, (int, float)):
            return None
        timestamp = float(timestamp_raw)
        session_id = str(data.get("session_id") or "").strip()
        cwd = str(data.get("cwd") or "").strip()
        if not session_id or not cwd or now - timestamp > max_age_seconds:
            return None
        prefix = "tty-dev-"
        if not path.name.startswith(prefix):
            return None
        tty = path.name[len(prefix):]
        return TerminalTask(tty=tty, session_id=session_id, cwd=cwd)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def collect_live_terminal_tasks(
    ps_output: str,
    breadcrumbs_dir: Path,
    *,
    now: float,
    max_age_seconds: float = 300.0,
) -> list[TerminalTask]:
    """Match live Hermes CLI TTYs with their fresh terminal-session breadcrumbs."""
    live_ttys = _live_hermes_ttys(ps_output)
    if not live_ttys:
        return []
    tasks: list[TerminalTask] = []
    try:
        paths: Iterable[Path] = breadcrumbs_dir.iterdir()
    except OSError:
        return []
    for path in paths:
        task = _breadcrumb_task(path, now=now, max_age_seconds=max_age_seconds)
        if task is not None and task.tty in live_ttys:
            tasks.append(task)
    return sorted(tasks, key=lambda task: task.tty)


def enrich_with_session_titles(tasks: Iterable[TerminalTask]) -> list[TerminalTask]:
    """Attach each task's own session title (best-effort; never raises).

    Titles are what make a topic list readable — a session called
    "починить импорт цен" beats a project folder called ``evgenijgrudev``.
    """
    items = list(tasks)
    if not items:
        return items
    try:
        from hermes_state import SessionDB

        db = SessionDB(read_only=True)  # read-only: never mutates the live session store
    except Exception:
        return items
    try:
        enriched: list[TerminalTask] = []
        for task in items:
            try:
                title = db.get_session_title(task.session_id)
            except Exception:
                title = None
            enriched.append(replace(task, title=title) if title else task)
        return enriched
    finally:
        try:
            db.close()
        except Exception:
            pass


async def sync_live_terminal_tasks(adapter: Any, chat_id: str, tasks: Iterable[TerminalTask]) -> dict[str, Any]:
    """Create one named Telegram DM topic and first status message per task."""
    topics: list[dict[str, str]] = []
    failed = 0
    for task in tasks:
        try:
            thread_id = await adapter.ensure_dm_topic(chat_id, task.topic_name)
            if not thread_id:
                failed += 1
                continue
            status_sender = getattr(adapter, "send_terminal_topic_status", None)
            if callable(status_sender):
                await cast(Any, status_sender)(chat_id, task, str(thread_id))
            else:
                await adapter.send(chat_id, task.status_text, metadata={"thread_id": str(thread_id)})
            topics.append({"tty": task.tty, "thread_id": str(thread_id)})
        except Exception:
            failed += 1
    return {"created_or_updated": len(topics), "failed": failed, "topics": topics}
