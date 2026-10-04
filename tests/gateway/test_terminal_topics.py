"""Tests for mirroring active local Hermes CLI terminals into Telegram DM topics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from gateway.control_socket import GatewayControlServer, request_terminal_topic_sync


def test_collect_live_terminal_tasks_maps_current_ttys_to_breadcrumbs(tmp_path: Path):
    from gateway.terminal_topics import collect_live_terminal_tasks

    breadcrumbs = tmp_path / "terminal-sessions"
    breadcrumbs.mkdir()
    (breadcrumbs / "tty-dev-ttys000").write_text(
        json.dumps({"session_id": "session-a", "cwd": "/Users/eve/project-a", "ts": 1000}),
        encoding="utf-8",
    )
    (breadcrumbs / "tty-dev-ttys001").write_text(
        json.dumps({"session_id": "session-b", "cwd": "/Users/eve/project-b", "ts": 1000}),
        encoding="utf-8",
    )
    ps_output = """
 101 ttys000 /opt/hermes/python3 -m hermes_cli.main --cli
 102 ttys001 /opt/hermes/python3 -m hermes_cli.main --cli
 103 ttys002 /bin/zsh
"""

    tasks = collect_live_terminal_tasks(ps_output, breadcrumbs, now=1010, max_age_seconds=60)

    assert [(task.tty, task.session_id, task.cwd) for task in tasks] == [
        ("ttys000", "session-a", "/Users/eve/project-a"),
        ("ttys001", "session-b", "/Users/eve/project-b"),
    ]
    assert tasks[0].topic_name == "🟢 project-a · ttys000"


def test_collect_live_terminal_tasks_ignores_missing_or_stale_breadcrumbs(tmp_path: Path):
    from gateway.terminal_topics import collect_live_terminal_tasks

    breadcrumbs = tmp_path / "terminal-sessions"
    breadcrumbs.mkdir()
    (breadcrumbs / "tty-dev-ttys000").write_text(
        json.dumps({"session_id": "stale", "cwd": "/Users/eve/old", "ts": 1}),
        encoding="utf-8",
    )
    ps_output = " 101 ttys000 /opt/hermes/python3 -m hermes_cli.main --cli\n"

    assert collect_live_terminal_tasks(ps_output, breadcrumbs, now=1000, max_age_seconds=60) == []


def test_sync_live_terminal_tasks_creates_topic_and_posts_status():
    from gateway.terminal_topics import TerminalTask, sync_live_terminal_tasks

    class Adapter:
        def __init__(self):
            self.ensured = []
            self.sent = []

        async def ensure_dm_topic(self, chat_id, name):
            self.ensured.append((chat_id, name))
            return "42"

        async def send(self, chat_id, text, metadata=None):
            self.sent.append((chat_id, text, metadata))
            return {"success": True}

    adapter = Adapter()
    task = TerminalTask(tty="ttys000", session_id="session-a", cwd="/Users/eve/project-a")

    result = asyncio.run(sync_live_terminal_tasks(adapter, "109733868", [task]))

    assert result == {"created_or_updated": 1, "failed": 0, "topics": [{"tty": "ttys000", "thread_id": "42"}]}
    assert adapter.ensured == [("109733868", "🟢 project-a · ttys000")]
    assert adapter.sent == [
        (
            "109733868",
            "🟢 **Hermes CLI task online**\nTTY: `ttys000`\nProject: `/Users/eve/project-a`\nSession: `session-a`",
            {"thread_id": "42"},
        )
    ]


def test_sync_live_terminal_tasks_uses_terminal_status_button_when_adapter_supports_it():
    from gateway.terminal_topics import TerminalTask, sync_live_terminal_tasks

    class Adapter:
        def __init__(self):
            self.statuses = []

        async def ensure_dm_topic(self, _chat_id, _name):
            return "42"

        async def send_terminal_topic_status(self, chat_id, task, thread_id):
            self.statuses.append((chat_id, task, thread_id))
            return {"success": True}

    adapter = Adapter()
    task = TerminalTask(tty="ttys000", session_id="session-a", cwd="/Users/eve/project-a")

    result = asyncio.run(sync_live_terminal_tasks(adapter, "109733868", [task]))

    assert result == {"created_or_updated": 1, "failed": 0, "topics": [{"tty": "ttys000", "thread_id": "42"}]}
    assert adapter.statuses == [("109733868", task, "42")]


def test_terminal_task_prefers_session_title_over_project_folder():
    from gateway.terminal_topics import TerminalTask

    titled = TerminalTask(tty="ttys000", session_id="s1", cwd="/Users/eve", title="  починить импорт цен  ")
    untitled = TerminalTask(tty="ttys001", session_id="s2", cwd="/Users/eve/shop")

    assert titled.label == "починить импорт цен"
    assert titled.topic_name == "🟢 починить импорт цен · ttys000"
    assert untitled.label == "shop"


def test_request_terminal_topic_sync_calls_control_socket_handler(tmp_path: Path):
    home = tmp_path / ".hermes"
    home.mkdir()

    async def scenario():
        server = GatewayControlServer(home, verb_handlers={"sync-terminal-topics": lambda: {"created_or_updated": 2}})
        assert await server.start()
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: request_terminal_topic_sync(home))
        finally:
            await server.stop()

    assert asyncio.run(scenario()) == {"created_or_updated": 2}


def test_focus_terminal_app_activates_macos_terminal(monkeypatch):
    from gateway.terminal_topics import focus_terminal_app

    launched = []
    monkeypatch.setattr("gateway.terminal_topics.sys.platform", "darwin")
    monkeypatch.setattr("gateway.terminal_topics.subprocess.Popen", launched.append)

    assert focus_terminal_app() is True
    assert launched == [["/usr/bin/osascript", "-e", 'tell application "Terminal" to activate']]


def test_focus_terminal_app_refuses_non_macos(monkeypatch):
    from gateway.terminal_topics import focus_terminal_app

    monkeypatch.setattr("gateway.terminal_topics.sys.platform", "linux")

    assert focus_terminal_app() is False
